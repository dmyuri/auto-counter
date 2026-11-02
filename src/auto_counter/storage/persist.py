"""Persistir a sessão inteira, de uma vez e sem duplicar — T-07.

Comportamento em `.spec/features/persistencia-resultados/spec.md`: AC-008.1
e AC-008.5.

Lê o que `captura-clipes` e `contagem-veiculos` já deixaram em disco — o
`manifest.json` (via `capture.manifest.ler`) e o `eventos.json` (via
`counting.events.ler`) — e não reimplementa nenhum dos dois leitores. O único
cálculo próprio é a soma dos eventos por minuto, em `storage.minutes.agregar`;
tudo o mais é cópia.

Tudo numa única transação, explícita (`BEGIN` / `COMMIT` / `ROLLBACK`): ou a
sessão inteira entra, ou nada entra — uma sessão meio gravada é pior que uma
não gravada, porque parece resultado. Por isso `abrir_sessao`, `fechar_captura`
e `completar_processamento` são chamadas aqui com `comitar=False`: quem
controla a transação é esta função, não cada uma delas.

Dentro da transação, os eventos e os agregados da sessão são **apagados antes
de inseridos de novo** (D-7 de `_tasks.md`) — é o que garante AC-008.5 também
para uma sessão que encolheu entre duas execuções, o que
`ON CONFLICT ... DO UPDATE` sozinho não cobre.
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from auto_counter.cameras.model import Camera
from auto_counter.capture import manifest as manifest_da_captura
from auto_counter.capture.manifest import FORMATO_DO_ID_DE_SESSAO
from auto_counter.counting import events as eventos_da_contagem
from auto_counter.storage.events import gravar_eventos
from auto_counter.storage.minutes import agregar, gravar_agregados
from auto_counter.storage.sessions import (
    abrir_sessao,
    completar_processamento,
    fechar_captura,
)


class SessaoAindaEmCapturaError(RuntimeError):
    """Sem duração real não há grade de minutos (D-4): nada para persistir.

    Espelha SUP-037 de `exportacao-xlsx`, que recusa planilha parcial pela
    mesma razão.
    """

    def __init__(self, id_sessao: str) -> None:
        self.id_sessao = id_sessao
        super().__init__(
            f"a sessão '{id_sessao}' ainda está em captura (sem duração real "
            f"no manifest); espere a captura terminar antes de persistir"
        )


class EventosAusentesError(FileNotFoundError):
    """`eventos.json` não existe: a sessão não foi processada ainda."""

    def __init__(self, caminho: Path) -> None:
        self.caminho = caminho
        super().__init__(
            f"não há {eventos_da_contagem.NOME_DO_ARQUIVO_DE_EVENTOS} em "
            f"{caminho}; processe a sessão (`session process`) antes de "
            f"persistir"
        )


@dataclass(frozen=True)
class ResumoPersistido:
    """O que `persistir_sessao` devolve — T-08 (CLI) imprime isto."""

    id_sessao: str
    eventos_gravados: int
    minutos_capturados: int
    minutos_sem_dado: int


def _criada_em_do_id_sessao(id_sessao: str) -> datetime:
    """Recupera o relógio do comando embutido no id da sessão
    (`<id_camera>-AAAAMMDDTHHMMSSZ`, D-5 de `captura-clipes/_tasks.md`).

    Só é usado quando a linha ainda não existe no banco — uma sessão
    capturada antes desta feature, por exemplo. Quando a linha já existe
    (aberta durante a captura, T-04), `abrir_sessao` não sobrescreve nada e
    este valor é descartado.
    """
    _, _, marca = id_sessao.rpartition("-")
    try:
        return datetime.strptime(marca, FORMATO_DO_ID_DE_SESSAO).replace(
            tzinfo=timezone.utc
        )
    except ValueError as falha:
        raise ValueError(
            f"não foi possível extrair o relógio do comando do id de sessão "
            f"'{id_sessao}'; o formato esperado é "
            f"'<id_camera>-{FORMATO_DO_ID_DE_SESSAO}'"
        ) from falha


def persistir_sessao(
    conexao: sqlite3.Connection, dir_sessao: str | Path, *, camera: Camera
) -> ResumoPersistido:
    """Lê o manifest e o `eventos.json` da sessão e grava tudo no banco.

    `camera` é quem o CLI já resolveu (T-08): dela vêm os rótulos de sentido
    vigentes (D-6), usados tanto no upsert da linha de sessão quanto na
    tradução rótulo→papel dos agregados.
    """
    dir_sessao = Path(dir_sessao)
    manifest = manifest_da_captura.ler(dir_sessao)

    if manifest.duracao_real is None:
        raise SessaoAindaEmCapturaError(manifest.id_sessao)

    caminho_eventos = dir_sessao / eventos_da_contagem.NOME_DO_ARQUIVO_DE_EVENTOS
    try:
        registro = eventos_da_contagem.ler(dir_sessao)
    except FileNotFoundError as falha:
        raise EventosAusentesError(caminho_eventos) from falha

    agregados = agregar(
        registro.eventos,
        duracao_real=manifest.duracao_real,
        minutos_processados=registro.minutos_processados,
        minutos_nao_processados=registro.minutos_nao_processados,
        sentido_a=camera.sentido_a,
        sentido_b=camera.sentido_b,
    )

    conexao.execute("BEGIN")
    try:
        abrir_sessao(
            conexao,
            id_sessao=manifest.id_sessao,
            id_camera=manifest.id_camera,
            criada_em=_criada_em_do_id_sessao(manifest.id_sessao),
            duracao_pedida=manifest.duracao_pedida,
            sentido_a=camera.sentido_a,
            sentido_b=camera.sentido_b,
            nome_camera=camera.nome,
            comitar=False,
        )
        # AC-010.4: o nome gravado na captura é o vigente na sessão e não é
        # sobrescrito; só a linha que nasceu sem nome (sessão anterior à
        # migration 002, ou captura em que o banco falhou) é preenchida.
        conexao.execute(
            "UPDATE sessao SET nome_camera = COALESCE(nome_camera, ?) "
            "WHERE id_sessao = ?",
            (camera.nome, manifest.id_sessao),
        )
        fechar_captura(
            conexao,
            manifest.id_sessao,
            inicio=manifest.inicio,
            fim=manifest.fim,
            duracao_real=manifest.duracao_real,
            encerrada_pelo_usuario=manifest.encerrada_pelo_usuario,
            status=manifest.status,
            minutos_perdidos=[item.minuto for item in manifest.minutos_perdidos],
            comitar=False,
        )
        completar_processamento(
            conexao,
            manifest.id_sessao,
            versao_do_modelo=registro.versao_do_modelo,
            amostragem=registro.configuracao.amostragem,
            limiar_de_confianca=registro.configuracao.limiar_de_confianca,
            comitar=False,
        )

        # AC-008.5: apaga antes de inserir, para que uma sessão que encolheu
        # entre duas execuções não deixe resto da primeira — o que
        # `ON CONFLICT ... DO UPDATE` sozinho não garante.
        conexao.execute("DELETE FROM evento WHERE id_sessao = ?", (manifest.id_sessao,))
        conexao.execute("DELETE FROM minuto WHERE id_sessao = ?", (manifest.id_sessao,))

        gravar_eventos(conexao, manifest.id_sessao, registro.eventos)
        gravar_agregados(conexao, manifest.id_sessao, agregados)
    except Exception:
        conexao.rollback()
        raise
    else:
        conexao.commit()

    return ResumoPersistido(
        id_sessao=manifest.id_sessao,
        eventos_gravados=len(registro.eventos),
        minutos_capturados=len(registro.minutos_processados),
        minutos_sem_dado=sum(
            1 for item in agregados if item.estado.value == "SEM_DADO"
        ),
    )

"""Processar, persistir e descartar os vídeos de uma sessão — T-09.

Comportamento em `.spec/features/interface-sessao/spec.md`: SUP-038 (a linha de
comando e a interface chamam a mesma camada de aplicação) e AC-012.5 (encerrar
no processamento cancela a contagem sem gravar nada e mantém os vídeos).

A sequência é a que `session process` já tinha, extraída sem mudar a ordem
(D-3 e D-5 de `persistencia-resultados`): processa, persiste no banco e só então
descarta os vídeos, e só se o manifest não pedir para mantê-los. Falha na
persistência não apaga nada, porque a sessão ainda pode ser reprocessada.

Está dividida em duas etapas, `processar` e `persistir_e_descartar`, porque a
CLI imprime o relatório da contagem entre as duas.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from auto_counter.cameras.model import Camera
from auto_counter.capture.cleanup import descartar_videos
from auto_counter.counting import model as modelo_de_deteccao
from auto_counter.counting.clip import DetectorDoClipe
from auto_counter.counting.config import ConfiguracaoDoProcessamento
from auto_counter.counting.events import Evento
from auto_counter.counting.events import NOME_DO_ARQUIVO_DE_EVENTOS
from auto_counter.counting.model import caminho_do_modelo
from auto_counter.counting.session import (
    ParadaDoProcessamento,
    ProcessamentoCancelado,
    ResultadoDaContagem,
    processar_sessao,
)
from auto_counter.storage.connection import caminho_do_banco, conectar
from auto_counter.storage.persist import ResumoPersistido, persistir_sessao


class PersistenciaFalhouError(RuntimeError):
    """A gravação da sessão no banco falhou; os vídeos não foram apagados.

    A causa original fica em `__cause__`, e a mensagem repete a dela.
    """


@dataclass(frozen=True)
class ResultadoDaPersistencia:
    """O que `persistir_e_descartar` fez.

    `videos_apagados` é `None` quando os vídeos foram preservados por
    `manter_videos`, e é a quantidade apagada caso contrário.
    """

    resumo: ResumoPersistido
    banco: Path
    videos_apagados: int | None


def conferir_modelo(data_dir: str | Path) -> tuple[Path, str]:
    """O caminho do `.onnx` e a versão dele, antes de abrir qualquer vídeo.

    Descobrir que o modelo falta depois de minutos de processamento seria
    desperdício puro (e, numa sessão nova, depois da captura que não volta).
    `ModeloAusenteError` e `OSError` sobem como estão.
    """
    caminho = caminho_do_modelo(Path(data_dir))
    return caminho, modelo_de_deteccao.versao_do_modelo(caminho)


def processar(
    dir_sessao: str | Path,
    *,
    camera: Camera,
    detector: DetectorDoClipe,
    config: ConfiguracaoDoProcessamento,
    versao_do_modelo: str,
    parada: ParadaDoProcessamento | None = None,
    ao_resolver_minuto: Callable[[int], None] | None = None,
    ao_aceitar_evento: Callable[[int, Evento], None] | None = None,
    ao_descartar_minuto: Callable[[int], None] | None = None,
) -> ResultadoDaContagem:
    """Conta os veículos da sessão e grava o `eventos.json`.

    Cancelada a pedido do usuário (AC-012.5), apaga o `eventos.json` parcial —
    um arquivo meio escrito não pode parecer resultado — e relevanta
    `ProcessamentoCancelado`. Nada é persistido e nenhum vídeo é apagado.

    `ao_aceitar_evento` e `ao_descartar_minuto` são repassados a
    `processar_sessao` (acompanhamento ao vivo). `session process` não os passa.
    """
    try:
        return processar_sessao(
            dir_sessao,
            camera=camera,
            detector=detector,
            config=config,
            versao_do_modelo=versao_do_modelo,
            parada=parada,
            ao_resolver_minuto=ao_resolver_minuto,
            ao_aceitar_evento=ao_aceitar_evento,
            ao_descartar_minuto=ao_descartar_minuto,
        )
    except ProcessamentoCancelado:
        (Path(dir_sessao) / NOME_DO_ARQUIVO_DE_EVENTOS).unlink(missing_ok=True)
        raise


def persistir_e_descartar(
    data_dir: str | Path,
    dir_sessao: str | Path,
    *,
    camera: Camera,
    manter_videos: bool,
    persistir: Callable[..., ResumoPersistido] | None = None,
) -> ResultadoDaPersistencia:
    """Grava a sessão no banco e, só depois, descarta os vídeos.

    A persistência vem **antes** do descarte: o banco é a única coisa que
    sobrevive ao fim da sessão, e invertida a ordem uma falha de banco deixaria
    a sessão sem vídeo e sem resultado. Qualquer falha na persistência vira
    `PersistenciaFalhouError` e aborta antes do descarte.

    `persistir` é a função que grava; o padrão é `persistir_sessao`. A CLI a
    passa explicitamente para que os testes continuem trocando-a por nome.
    """
    gravar = persistir or persistir_sessao
    dir_sessao = Path(dir_sessao)
    try:
        with conectar(data_dir) as conexao:
            resumo = gravar(conexao, dir_sessao, camera=camera)
    except Exception as falha:  # noqa: BLE001 — nenhuma falha de banco crua
        raise PersistenciaFalhouError(str(falha)) from falha

    apagados = None if manter_videos else descartar_videos(dir_sessao)
    return ResultadoDaPersistencia(
        resumo=resumo, banco=caminho_do_banco(data_dir), videos_apagados=apagados
    )

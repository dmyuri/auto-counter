"""Orquestração da sessão completa: captura, processamento e planilha — T-10.

Comportamento em `.spec/features/interface-sessao/spec.md`: AC-011.4 (o pipeline
roda até o XLSX sem a interface web), AC-012.1 e AC-012.2 (o estado acompanha a
captura e o processamento), AC-012.3 (o desfecho traz o status gravado e a
planilha), AC-012.5 (encerrar no processamento cancela e preserva os vídeos) e
AC-012.6 (sessão sem clipe processável termina sem planilha).

Esta função é o que `session run` executa e, por consequência, o que a interface
dispara. Ela **não** pega a trava de sessão única (quem pega é o comando, T-12)
e não conhece `streamlit` nem `auto_counter.cli`: tudo o que varia — relógio,
espera, cliente HTTP, detector e parada — entra por parâmetro, como em
`capturar`.

O desfecho de cada fase é gravado no estado da sessão (`sessao_atual.json`). As
exceções inesperadas marcam o estado como `FALHOU` e sobem, para o comando
traduzi-las em mensagem e código de saída.
"""

import os
import sys
from collections.abc import Callable
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path

import httpx

from auto_counter.cameras.model import Camera
from auto_counter.capture.duration import validar_duracao
from auto_counter.capture.session import Parada, capturar
from auto_counter.counting.clip import DetectorDoClipe
from auto_counter.counting.config import ConfiguracaoDoProcessamento
from auto_counter.counting.session import ProcessamentoCancelado, SessaoSemClipes
from auto_counter.export import exportar_sessao
from auto_counter.pipeline.processing import (
    conferir_modelo,
    persistir_e_descartar,
    processar,
)
from auto_counter.pipeline.state import AnotadorDoEstado, EstadoDaSessao, Fase
from auto_counter.pipeline.stop import consumir_pedido
from auto_counter.storage.connection import conectar
from auto_counter.storage.sessions import PersistenciaDaCaptura, ler_sessao

MENSAGEM_SEM_CLIPE = (
    "nenhum clipe da sessão pôde ser processado; não há planilha. O status da "
    "sessão continua registrado."
)
"""AC-012.6: o que a interface mostra quando não há o que exportar."""


def executar_sessao(
    camera: Camera,
    minutos: int,
    *,
    data_dir: str | Path,
    cliente: httpx.Client,
    agora: Callable[[], datetime],
    dormir: Callable[[float], None],
    criar_detector: Callable[[Path, ConfiguracaoDoProcessamento], DetectorDoClipe],
    criar_parada: Callable[[], Parada],
    manter_videos: bool = False,
    pid: int | None = None,
) -> EstadoDaSessao:
    """Roda a sessão da captura à planilha e devolve o estado final.

    `criar_parada` é uma fábrica, e é chamada **uma vez por fase**: o pedido de
    encerramento da captura (AC-003.6) não pode valer também para o
    processamento, que tem a regra própria de AC-012.5. Com o pedido por
    arquivo isso já é garantido pelo consumo entre as fases; a fábrica garante
    o mesmo para o Ctrl+C, cujo sinal é um objeto em memória.

    Termina com sucesso (`CONCLUIDA`), sem planilha (`SEM_PLANILHA`) ou com o
    processamento cancelado (`PROCESSAMENTO_CANCELADO`). Qualquer falha marca
    `FALHOU` e relevanta.
    """
    duracao = validar_duracao(minutos)
    data_dir = Path(data_dir)
    consumir_pedido(data_dir)

    anotador = AnotadorDoEstado(
        data_dir,
        pid=os.getpid() if pid is None else pid,
        id_camera=camera.id,
        nome_camera=camera.nome,
        duracao_pedida=duracao,
        iniciada_em=agora(),
    )
    anotador.iniciar()

    id_sessao: str | None = None
    try:
        # A captura não volta: descobrir só depois de 15 minutos que o modelo
        # falta seria desperdício puro.
        caminho_do_onnx, versao = conferir_modelo(data_dir)

        with ExitStack() as pilha:
            # Falha ao abrir o banco não interrompe a captura (`CLAUDE.md`): o
            # manifest é prova durável até o processamento regravar a sessão.
            persistencia = None
            try:
                conexao = pilha.enter_context(conectar(data_dir))
                persistencia = PersistenciaDaCaptura(conexao, camera=camera)
            except Exception as falha:  # noqa: BLE001
                print(
                    f"aviso: não foi possível abrir o banco em {data_dir}: "
                    f"{falha}; a sessão será capturada sem persistência no banco",
                    file=sys.stderr,
                )

            captura = capturar(
                camera,
                duracao,
                data_dir=data_dir,
                cliente=cliente,
                agora=agora,
                dormir=dormir,
                parada=criar_parada(),
                manter_videos=manter_videos,
                persistencia=persistencia,
                ao_resolver_minuto=anotador.minuto_da_captura,
            )
        id_sessao = captura.id_sessao

        # O pedido que encerrou a captura não vale para o processamento.
        consumir_pedido(data_dir)

        if not captura.minutos_capturados:
            anotador.terminar(
                Fase.SEM_PLANILHA,
                id_sessao=id_sessao,
                status=captura.status.value,
                mensagem=MENSAGEM_SEM_CLIPE,
            )
            return anotador.estado

        anotador.processamento_iniciado(id_sessao, len(captura.minutos_capturados))
        config = ConfiguracaoDoProcessamento()
        try:
            processar(
                captura.dir_sessao,
                camera=camera,
                detector=criar_detector(caminho_do_onnx, config),
                config=config,
                versao_do_modelo=versao,
                parada=criar_parada(),
                ao_resolver_minuto=lambda _minuto: anotador.minuto_processado(),
            )
        except ProcessamentoCancelado:
            anotador.terminar(
                Fase.PROCESSAMENTO_CANCELADO,
                id_sessao=id_sessao,
                status=captura.status.value,
                mensagem=(
                    "o processamento foi cancelado e os vídeos foram mantidos; "
                    f"reprocesse com `auto-counter session process {id_sessao}`"
                ),
            )
            return anotador.estado
        except SessaoSemClipes:
            anotador.terminar(
                Fase.SEM_PLANILHA,
                id_sessao=id_sessao,
                status=captura.status.value,
                mensagem=MENSAGEM_SEM_CLIPE,
            )
            return anotador.estado

        persistir_e_descartar(
            data_dir,
            captura.dir_sessao,
            camera=camera,
            manter_videos=manter_videos,
        )

        with conectar(data_dir) as conexao:
            planilha = exportar_sessao(conexao, id_sessao, data_dir=data_dir)
            gravada = ler_sessao(conexao, id_sessao)

        anotador.terminar(
            Fase.CONCLUIDA,
            id_sessao=id_sessao,
            status=gravada.status.value,
            planilha=str(planilha),
            mensagem="sessão concluída",
        )
        return anotador.estado
    except BaseException as falha:
        anotador.terminar(
            Fase.FALHOU,
            id_sessao=id_sessao,
            mensagem=str(falha) or type(falha).__name__,
        )
        raise
    finally:
        consumir_pedido(data_dir)


"""Orquestração da sessão de upload: dos vídeos à planilha — T-13.

Comportamento em `.spec/features/processamento-upload/spec.md`: AC-028.1 (uma
sessão da câmera, que começa direto no processamento), AC-028.3 e AC-028.10 (o
estado em disco acompanha cada vídeo e as quantidades), AC-028.9 (o vídeo que
falha fica "falhou" e a sessão segue), AC-029.1 e AC-029.2 (parar cancela sem
gravar, mantém os vídeos e deixa o vídeo em curso "interrompido") e AC-030.6 (a
sessão concluída apaga os vídeos), mais SUP-094, SUP-097 e, no `_tasks.md`, D-11,
D-12, D-13 e D-15.

Esta função é o que `session upload` executa e, por consequência, o que a
interface dispara. Ela **não** pega a trava de sessão única (quem pega é o
comando, T-14) e não conhece `streamlit` nem `auto_counter.cli`: relógio,
detector e parada entram por parâmetro, como em `executar_sessao`.

O estado inicial só é gravado depois da validação, porque `duracao_pedida` é M,
o total de minutos da sessão, que só se conhece com as durações lidas (D-3). Uma
recusa antes disso (modelo ausente, arquivo inválido) grava um estado `FALHOU`
com a mensagem, sem diretório de sessão e sem mexer nos arquivos enviados.

Desfechos: `CONCLUIDA` (persiste, apaga os vídeos, exporta), `SEM_PLANILHA`
quando nenhum vídeo rendeu frame (SUP-094), `PROCESSAMENTO_CANCELADO` e
`FALHOU`. Nos três últimos as cópias em `sessions/<id_sessao>/` ficam onde estão
(AC-029.1, D-15). Falha inesperada relevanta, para o comando sair com código
diferente de zero.
"""

import os
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path

from auto_counter.cameras.model import Camera
from auto_counter.capture.manifest import diretorio_da_sessao, id_da_sessao
from auto_counter.counting.clip import DetectorDoClipe
from auto_counter.counting.config import ConfiguracaoDoProcessamento
from auto_counter.counting.session import (
    ParadaDoProcessamento,
    ProcessamentoCancelado,
    SessaoSemClipes,
)
from auto_counter.counting.upload import processar_sessao_de_upload
from auto_counter.export import exportar_sessao
from auto_counter.pipeline.preparo_upload import (
    preparar_sessao,
    triar_arquivos,
    validar_arquivos,
)
from auto_counter.pipeline.processing import conferir_modelo
from auto_counter.pipeline.run import MENSAGEM_SEM_CLIPE
from auto_counter.pipeline.state import (
    AnotadorDoEstado,
    EstadoDaSessao,
    Fase,
    SituacaoDoVideo,
)
from auto_counter.pipeline.stop import consumir_pedido
from auto_counter.storage.connection import conectar
from auto_counter.storage.persist import persistir_sessao_de_upload
from auto_counter.storage.sessions import ler_sessao
from auto_counter.upload.manifest import apagar_videos, numerar_minutos


def _novo_anotador(
    camera: Camera,
    nomes: Sequence[str],
    *,
    data_dir: Path,
    agora: Callable[[], datetime],
    t0: datetime,
    pid: int | None,
    duracao: int,
) -> AnotadorDoEstado:
    return AnotadorDoEstado(
        data_dir,
        pid=os.getpid() if pid is None else pid,
        id_camera=camera.id,
        nome_camera=camera.nome,
        duracao_pedida=duracao,
        iniciada_em=t0,
        agora=agora,
        origem="UPLOAD",
        videos=nomes,
    )


def _interromper_o_video_em_curso(anotador: AnotadorDoEstado) -> None:
    """D-11: o vídeo em `PROCESSANDO` vira `INTERROMPIDO` (AC-029.2)."""
    for posicao, video in enumerate(anotador.estado.videos, start=1):
        if video.situacao is SituacaoDoVideo.PROCESSANDO:
            anotador.video_terminado(posicao, SituacaoDoVideo.INTERROMPIDO)


def executar_upload(
    camera: Camera,
    arquivos: Sequence[Path | str],
    nomes: Sequence[str],
    *,
    data_dir: str | Path,
    agora: Callable[[], datetime],
    criar_detector: Callable[[Path, ConfiguracaoDoProcessamento], DetectorDoClipe],
    criar_parada: Callable[[], ParadaDoProcessamento],
    pid: int | None = None,
    ao_avisar: Callable[[str], None] | None = None,
) -> EstadoDaSessao:
    """Roda a sessão de upload da validação à planilha e devolve o estado final.

    `arquivos` e `nomes` andam juntos, na ordem da lista: `nomes` são os nomes
    originais, que o arquivo em `envios/` não guarda. A ordem dos efeitos é a de
    D-13: modelo, validação, preparo do diretório, contagem, persistência,
    descarte dos vídeos e planilha.

    `ao_avisar` recebe cada aviso da validação (a duplicata, SUP-098), que não
    impede a sessão; o comando o imprime em `stderr`.
    """
    data_dir = Path(data_dir)
    consumir_pedido(data_dir)
    t0 = agora()
    id_sessao = id_da_sessao(camera.id, t0)

    # Antes de saber M, uma recusa só precisa de um lugar onde gravar `FALHOU`.
    provisorio = _novo_anotador(
        camera, nomes, data_dir=data_dir, agora=agora, t0=t0, pid=pid, duracao=1
    )
    try:
        # Descobrir só depois de ler os vídeos que o modelo falta seria perda.
        caminho_do_onnx, versao = conferir_modelo(data_dir)
        triar_arquivos(arquivos, nomes)
        validacao = validar_arquivos(arquivos, nomes, camera)
    except BaseException as falha:
        provisorio.terminar(Fase.FALHOU, mensagem=str(falha) or type(falha).__name__)
        consumir_pedido(data_dir)
        raise

    for aviso in validacao.avisos:
        if ao_avisar is not None:
            ao_avisar(aviso)

    minutos = numerar_minutos(
        [leitura.duracao_segundos or 0 for leitura in validacao.leituras]
    )[-1][1]
    anotador = _novo_anotador(
        camera, nomes, data_dir=data_dir, agora=agora, t0=t0, pid=pid, duracao=minutos
    )
    anotador.iniciar()

    try:
        preparar_sessao(
            data_dir,
            id_sessao=id_sessao,
            camera=camera,
            arquivos=arquivos,
            nomes=nomes,
            leituras=validacao.leituras,
        )
        dir_sessao = diretorio_da_sessao(data_dir, id_sessao)
        config = ConfiguracaoDoProcessamento()

        def ao_terminar_video(posicao: int, falhou: bool) -> None:
            anotador.video_terminado(
                posicao,
                SituacaoDoVideo.FALHOU if falhou else SituacaoDoVideo.CONCLUIDO,
            )

        def ao_resolver_minuto(_minuto: int, com_dado: bool) -> None:
            if com_dado:
                anotador.minuto_processado()
            else:
                anotador.minuto_sem_dado()

        try:
            processar_sessao_de_upload(
                dir_sessao,
                camera=camera,
                detector=criar_detector(caminho_do_onnx, config),
                config=config,
                versao_do_modelo=versao,
                inicio_do_processamento=t0,
                parada=criar_parada(),
                ao_iniciar_video=anotador.video_iniciado,
                ao_terminar_video=ao_terminar_video,
                ao_iniciar_minuto=lambda _minuto: anotador.minuto_iniciado(),
                ao_aceitar_evento=lambda evento: anotador.evento_aceito(
                    evento.minuto, evento.categoria
                ),
                ao_descartar_minuto=anotador.minuto_descartado,
                ao_resolver_minuto=ao_resolver_minuto,
            )
        except ProcessamentoCancelado:
            _interromper_o_video_em_curso(anotador)
            anotador.terminar(
                Fase.PROCESSAMENTO_CANCELADO,
                id_sessao=id_sessao,
                mensagem=(
                    "o processamento foi cancelado e os vídeos foram mantidos; "
                    f"reprocesse com `auto-counter session process {id_sessao}`"
                ),
            )
            return anotador.estado
        except SessaoSemClipes:
            anotador.terminar(
                Fase.SEM_PLANILHA, id_sessao=id_sessao, mensagem=MENSAGEM_SEM_CLIPE
            )
            return anotador.estado

        fim = agora()
        with conectar(data_dir) as conexao:
            persistir_sessao_de_upload(
                conexao, dir_sessao, camera=camera, inicio=t0, fim=fim
            )
        # AC-030.6: só depois de gravado no banco os vídeos vão embora.
        apagar_videos(dir_sessao)

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
        _interromper_o_video_em_curso(anotador)
        anotador.terminar(
            Fase.FALHOU,
            id_sessao=id_sessao,
            mensagem=str(falha) or type(falha).__name__,
        )
        raise
    finally:
        consumir_pedido(data_dir)

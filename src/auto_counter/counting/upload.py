"""Laço da sessão de upload: os vídeos, um a um — T-09 de `processamento-upload`.

Comportamento em `.spec/features/processamento-upload/spec.md`: AC-028.1 (uma
sessão, vídeos na ordem da lista), AC-028.7 a AC-028.9, AC-029.1 (a parada),
SUP-092 e SUP-094, e no `_tasks.md` a D-12.

Aqui **não** há `FiltroDaEmenda`: dois vídeos da lista nunca são adjacentes
(AC-007.4, SUP-092), então nada é deduplicado entre o fim de um e o início do
seguinte, e o rastreador é novo a cada vídeo (AC-028.7). O vídeo que falha não
interrompe a sessão: o laço segue para o próximo (AC-028.9).

O `eventos.json` é regravado ao fim de cada vídeo em que houve ao menos um frame
legível. Nenhum vídeo legível levanta `SessaoSemClipes` (SUP-094), e a parada
pedida levanta `ProcessamentoCancelado` e apaga o `eventos.json` parcial
(AC-029.1). A posição do vídeo em curso fica com quem chama, pelos ganchos.
"""

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from auto_counter.cameras.model import Camera
from auto_counter.counting.clip import DetectorDoClipe
from auto_counter.counting.config import ConfiguracaoDoProcessamento
from auto_counter.counting.events import (
    NOME_DO_ARQUIVO_DE_EVENTOS,
    Evento,
    MinutoNaoProcessado,
    RegistroDeEventos,
)
from auto_counter.counting.events import ler as ler_eventos
from auto_counter.counting.session import (
    ParadaDoProcessamento,
    ProcessamentoCancelado,
    ResultadoDaContagem,
    SessaoSemClipes,
)
from auto_counter.counting.tracking import RastreadorDoSupervision, criar_bytetrack
from auto_counter.counting.video import ProcessamentoDeVideoCancelado, processar_video
from auto_counter.upload.manifest import ler as ler_registro_do_upload


def processar_sessao_de_upload(
    dir_sessao: str | Path,
    *,
    camera: Camera,
    detector: DetectorDoClipe,
    config: ConfiguracaoDoProcessamento,
    versao_do_modelo: str,
    inicio_do_processamento: datetime,
    fabrica_de_bytetrack: Callable[[], RastreadorDoSupervision] = criar_bytetrack,
    parada: ParadaDoProcessamento | None = None,
    ao_iniciar_video: Callable[[int], None] | None = None,
    ao_terminar_video: Callable[[int, bool], None] | None = None,
    ao_iniciar_minuto: Callable[[int], None] | None = None,
    ao_aceitar_evento: Callable[[Evento], None] | None = None,
    ao_descartar_minuto: Callable[[int], None] | None = None,
    ao_resolver_minuto: Callable[[int, bool], None] | None = None,
) -> ResultadoDaContagem:
    """Processa todos os vídeos da sessão e grava o `eventos.json`.

    `inicio_do_processamento` é o T0 da sessão (D-5), a origem da linha do tempo
    dos eventos. `parada` é consultada antes de cada vídeo e antes de cada minuto
    dentro dele (D-12). `ao_terminar_video(posicao, falhou)` informa o desfecho
    do vídeo.
    """
    dir_sessao = Path(dir_sessao)
    registro = ler_registro_do_upload(dir_sessao)

    eventos: list[Evento] = []
    processados: list[int] = []
    nao_processados: list[MinutoNaoProcessado] = []
    algum_frame_lido = False
    caminho: Path | None = None

    def grava() -> Path:
        return RegistroDeEventos(
            id_sessao=registro.id_sessao,
            id_camera=registro.id_camera,
            configuracao=config,
            versao_do_modelo=versao_do_modelo,
            minutos_processados=tuple(processados),
            minutos_nao_processados=tuple(
                sorted(nao_processados, key=lambda item: item.minuto)
            ),
            eventos=tuple(eventos),
        ).gravar(dir_sessao)

    try:
        for video in sorted(registro.videos, key=lambda item: item.posicao):
            if parada is not None and parada.foi_pedida():
                raise ProcessamentoDeVideoCancelado(video.posicao)
            if ao_iniciar_video is not None:
                ao_iniciar_video(video.posicao)

            resultado = processar_video(
                dir_sessao / video.arquivo,
                camera=camera,
                posicao=video.posicao,
                nome=video.nome_original,
                minuto_inicial=video.minuto_inicial,
                minutos=video.minuto_final - video.minuto_inicial + 1,
                inicio_da_linha_do_tempo=inicio_do_processamento,
                detector=detector,
                config=config,
                fabrica_de_bytetrack=fabrica_de_bytetrack,
                parada=parada,
                ao_iniciar_minuto=ao_iniciar_minuto,
                ao_aceitar_evento=ao_aceitar_evento,
                ao_descartar_minuto=ao_descartar_minuto,
                ao_resolver_minuto=ao_resolver_minuto,
            )

            eventos.extend(resultado.eventos)
            processados.extend(resultado.minutos_com_dado)
            nao_processados.extend(resultado.minutos_sem_dado)
            algum_frame_lido = algum_frame_lido or resultado.leu_algum_frame
            if algum_frame_lido:
                caminho = grava()
            if ao_terminar_video is not None:
                ao_terminar_video(video.posicao, resultado.falhou)
    except ProcessamentoCancelado:
        # AC-029.1: nenhum resultado parcial fica gravado.
        (dir_sessao / NOME_DO_ARQUIVO_DE_EVENTOS).unlink(missing_ok=True)
        raise

    if caminho is None:
        raise SessaoSemClipes(
            f"nenhum vídeo da sessão {registro.id_sessao} rendeu um frame legível "
            f"em {dir_sessao}; a contagem não foi gravada, porque um resultado "
            f"zerado seria indistinguível de uma sessão sem nenhum veículo "
            f"(SUP-094)"
        )

    return ResultadoDaContagem(registro=ler_eventos(caminho), caminho=caminho)

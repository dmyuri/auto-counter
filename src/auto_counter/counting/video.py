"""Contagem de **um** vídeo enviado — T-06 de `processamento-upload`.

Comportamento em `.spec/features/processamento-upload/spec.md`: AC-028.4 a
AC-028.9, mais SUP-091 e, no `_tasks.md`, D-3, D-4, D-5 e D-12.

Ao contrário de `clip.py`, aqui o rastreador e o avaliador de cruzamento valem
para o **vídeo inteiro**: o minuto é só a divisão dos agregados, e não há emenda
a deduplicar dentro do mesmo arquivo (AC-028.6, SUP-091). A amostragem é por fps
efetivo (AC-028.5, SUP-090).

Cada evento é completado com o minuto da sessão, o vídeo e o deslocamento desde o
início do vídeo (D-5). O timestamp é uma posição na linha do tempo da sessão,
nunca uma hora do dia (SUP-100).

A falha de leitura (D-4) vale por minuto: o minuto em que a leitura parou e os
seguintes ficam sem dado, e os anteriores mantêm seus eventos (AC-028.9). Os
ganchos por minuto (D-12) deixam o laço da sessão atualizar o estado e consultar
a parada.
"""

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path

from auto_counter.cameras.model import Camera
from auto_counter.counting.clip import MOTIVO_SEM_FPS, DetectorDoClipe
from auto_counter.counting.config import ConfiguracaoDoProcessamento
from auto_counter.counting.crossing import AvaliadorDeCruzamento
from auto_counter.counting.events import Evento, MinutoNaoProcessado
from auto_counter.counting.sampling import frames_amostrados_por_taxa
from auto_counter.counting.session import ParadaDoProcessamento, ProcessamentoCancelado
from auto_counter.counting.tracking import (
    RastreadorDoSupervision,
    criar_bytetrack,
    rastreador_para_o_clipe,
)

MOTIVO_TERMINOU_CEDO = "a leitura terminou antes do fim do vídeo"
"""D-4: a decodificação acabou antes do início do último minuto do vídeo."""


class ProcessamentoDeVideoCancelado(ProcessamentoCancelado):
    """A parada foi pedida durante um vídeo; `video` é a posição dele (D-12)."""

    def __init__(self, video: int) -> None:
        super().__init__(f"processamento cancelado durante o vídeo {video}")
        self.video = video


@dataclass(frozen=True)
class ResultadoDoVideo:
    """O que um vídeo rendeu."""

    eventos: tuple[Evento, ...]
    """Só os dos minutos com dado."""
    minutos_com_dado: tuple[int, ...]
    minutos_sem_dado: tuple[MinutoNaoProcessado, ...]
    falhou: bool
    frames_analisados: int
    leu_algum_frame: bool


def processar_video(
    caminho: Path | str,
    *,
    camera: Camera,
    posicao: int,
    nome: str,
    minuto_inicial: int,
    minutos: int,
    inicio_da_linha_do_tempo: datetime,
    detector: DetectorDoClipe,
    config: ConfiguracaoDoProcessamento,
    fabrica_de_bytetrack: Callable[[], RastreadorDoSupervision] = criar_bytetrack,
    parada: ParadaDoProcessamento | None = None,
    ao_iniciar_minuto: Callable[[int], None] | None = None,
    ao_aceitar_evento: Callable[[Evento], None] | None = None,
    ao_descartar_minuto: Callable[[int], None] | None = None,
    ao_resolver_minuto: Callable[[int, bool], None] | None = None,
) -> ResultadoDoVideo:
    """Detecta, rastreia e conta os cruzamentos de um vídeo enviado.

    `posicao` e `nome` identificam o vídeo na lista (a partir de 1) e entram no
    motivo dos minutos sem dado. `minuto_inicial` e `minutos` são a faixa do
    vídeo na sessão (D-3), e `inicio_da_linha_do_tempo` é o T0 da sessão
    (D-5). Os minutos dos ganchos são os da sessão.
    """
    ultimo_minuto = minuto_inicial + minutos - 1
    inicio_do_video = inicio_da_linha_do_tempo + timedelta(
        seconds=60 * (minuto_inicial - 1)
    )
    rastreador = rastreador_para_o_clipe(minuto_inicial, fabrica_de_bytetrack)
    amostragem = frames_amostrados_por_taxa(caminho, config.frames_por_segundo)

    avaliador: AvaliadorDeCruzamento | None = None
    eventos: list[Evento] = []
    com_dado: list[int] = []
    sem_dado: list[MinutoNaoProcessado] = []
    analisados = 0
    aberto: int | None = None  # minuto da sessão em análise
    sem_fps = False

    def resolver(minuto: int, tem_dado: bool) -> None:
        if tem_dado:
            com_dado.append(minuto)
        if ao_resolver_minuto is not None:
            ao_resolver_minuto(minuto, tem_dado)

    iterador = iter(amostragem)
    try:
        for amostra in iterador:
            if avaliador is None:
                fps = amostragem.fps
                if fps is None or fps <= 0:
                    sem_fps = True
                    break
                avaliador = AvaliadorDeCruzamento(
                    camera=camera,
                    rastreador=rastreador,
                    inicio_do_clipe=inicio_do_video,
                    fps=fps,
                )

            deslocamento = int(amostra.indice / fps)
            minuto = minuto_inicial + min(deslocamento // 60, minutos - 1)
            if aberto is None or minuto > aberto:
                if aberto is not None:
                    for concluido in range(aberto, minuto):
                        resolver(concluido, True)
                if parada is not None and parada.foi_pedida():
                    raise ProcessamentoDeVideoCancelado(posicao)
                if ao_iniciar_minuto is not None:
                    ao_iniciar_minuto(minuto)
                aberto = minuto

            analisados += 1
            deteccoes = detector.detectar(amostra.imagem)
            rastreadas = rastreador.atualizar(deteccoes)
            for evento in avaliador.avaliar(rastreadas, indice_do_frame=amostra.indice):
                completo = replace(
                    evento,
                    minuto=minuto,
                    video=posicao,
                    deslocamento_segundos=deslocamento,
                )
                eventos.append(completo)
                if ao_aceitar_evento is not None:
                    ao_aceitar_evento(completo)
    finally:
        iterador.close()

    total = amostragem.total_de_frames
    fps = amostragem.fps
    motivo: str | None = None
    if sem_fps:
        motivo = MOTIVO_SEM_FPS
    elif amostragem.motivo is not None:
        motivo = amostragem.motivo
    elif fps and fps > 0 and (total - 1) / fps < 60 * (minutos - 1):
        motivo = MOTIVO_TERMINOU_CEDO

    if motivo is None:
        # Fim normal: o último minuto pode ser parcial (SUP-093).
        if aberto is not None:
            for concluido in range(aberto, ultimo_minuto + 1):
                resolver(concluido, True)
        return ResultadoDoVideo(
            eventos=tuple(eventos),
            minutos_com_dado=tuple(com_dado),
            minutos_sem_dado=(),
            falhou=False,
            frames_analisados=analisados,
            leu_algum_frame=total > 0,
        )

    # D-4: m é o minuto do primeiro frame que não foi lido.
    if aberto is None or sem_fps:
        primeiro_sem_dado = minuto_inicial
    else:
        do_primeiro_nao_lido = minuto_inicial + min(
            int(total / fps) // 60, minutos - 1
        )
        if aberto < do_primeiro_nao_lido:
            resolver(aberto, True)
            primeiro_sem_dado = aberto + 1
        else:
            primeiro_sem_dado = aberto

    if ao_descartar_minuto is not None:
        ao_descartar_minuto(primeiro_sem_dado)
    motivo_completo = f"{motivo} (vídeo {posicao}: {nome})"
    for minuto in range(primeiro_sem_dado, ultimo_minuto + 1):
        sem_dado.append(MinutoNaoProcessado(minuto=minuto, motivo=motivo_completo))
        resolver(minuto, False)

    return ResultadoDoVideo(
        eventos=tuple(e for e in eventos if e.minuto < primeiro_sem_dado),
        minutos_com_dado=tuple(com_dado),
        minutos_sem_dado=tuple(sem_dado),
        falhou=True,
        frames_analisados=analisados,
        leu_algum_frame=total > 0 and not sem_fps,
    )

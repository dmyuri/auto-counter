"""Processamento de um clipe, do arquivo aos eventos — T-11.

Costura T-04 (detector), T-05 (amostragem), T-06 (timestamp), T-08
(rastreamento) e T-09 (cruzamento) na ordem que a spec impõe:

- AC-005.3 — só os frames amostrados vão ao detector; os demais não passam por
  inferência;
- AC-005.1 e AC-005.2 — o filtro de classe e o de confiança acontecem dentro do
  detector, antes do rastreamento;
- SUP-023 — o histórico de classes é acumulado a cada frame analisado, e a
  categoria do evento é decidida no cruzamento;
- AC-006.1 e AC-006.5 — cada cruzamento vira um evento datado pelo início do
  clipe somado ao deslocamento do frame;
- AC-007.3 — o rastreador é **criado aqui**, um por clipe, e morre com ele.
  Nada de estado atravessa a chamada.

Um clipe é um clipe: esta função não conhece sessão, manifest nem emenda. Quem
decide adjacência e deduplica é T-10 e T-12, e é por isso que
`ResultadoDoClipe` devolve `fps` e duração — a janela de emenda de AC-007.1
precisa dos dois.

**D-4:** arquivo ausente, ilegível ou sem taxa de quadros utilizável não estoura
exceção. O resultado vem sem eventos e com o motivo preenchido, e quem o
transforma em "minuto sem dado" é T-12.

O detector e a fábrica do rastreador entram por parâmetro (D-8): a suíte rápida
roda sem o `.onnx` e sem ByteTrack real.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

import supervision as sv

from auto_counter.cameras.model import Camera
from auto_counter.counting.cancelamento import (
    ParadaDoProcessamento,
    ProcessamentoCancelado,
)
from auto_counter.counting.config import ConfiguracaoDoProcessamento
from auto_counter.counting.crossing import AvaliadorDeCruzamento
from auto_counter.counting.events import Evento
from auto_counter.counting.sampling import frames_amostrados
from auto_counter.counting.tracking import (
    RastreadorDoSupervision,
    criar_bytetrack,
    rastreador_para_o_clipe,
)

MOTIVO_SEM_FPS = "o vídeo não declara uma taxa de quadros utilizável"
"""Ramo de D-4: sem fps não há como datar o frame (AC-006.5), então o clipe é
tão inaproveitável quanto o que não abre — mesmo caminho, motivo próprio."""


class DetectorDoClipe(Protocol):
    """O contrato que este módulo usa do `Detector` de T-04 (D-8)."""

    def detectar(self, frame: Any) -> sv.Detections: ...


@dataclass(frozen=True)
class ResultadoDoClipe:
    """O que um clipe rendeu: os eventos e o que a emenda precisa saber dele.

    `fps` e `duracao_em_segundos` são lidos do próprio arquivo, nunca fixados
    em 59,93 s: T-10 usa os dois para posicionar a janela de 2 s de cada lado
    do corte, e o clipe entregue pode ser mais curto (AC-003.6).

    `motivo` é `None` quando o clipe foi processado. Preenchido, é o caminho de
    D-4, e aí os eventos são vazios por definição.
    """

    eventos: tuple[Evento, ...]
    fps: float | None
    duracao_em_segundos: float
    frames_analisados: int
    motivo: str | None = None


def processar_clipe(
    caminho: Path | str,
    *,
    camera: Camera,
    minuto: int,
    inicio_do_clipe: datetime,
    detector: DetectorDoClipe,
    config: ConfiguracaoDoProcessamento,
    fabrica_de_bytetrack: Callable[[], RastreadorDoSupervision] = criar_bytetrack,
    ao_gerar_evento: Callable[[Evento, float], None] | None = None,
    parada: ParadaDoProcessamento | None = None,
) -> ResultadoDoClipe:
    """Detecta, rastreia e conta os cruzamentos de **um** clipe.

    `inicio_do_clipe` é o Last-Modified daquele clipe (AC-006.5) e precisa ser
    ciente de fuso. `minuto` é o minuto da sessão, que vira o prefixo dos ids
    de rastreio (D-9).

    O avaliador de cruzamento só pode ser construído depois que o vídeo abre —
    ele precisa do `fps` do arquivo —, por isso nasce no primeiro frame
    analisado. Clipe que não rende frame nenhum nunca chega a ter avaliador, e
    sai por D-4.

    `ao_gerar_evento`, se dado, é chamado uma vez por evento, na ordem em que o
    avaliador os devolve e logo depois do frame que o gerou, com o `fps` do clipe
    (AC-016.2 de `acompanhamento-ao-vivo`). Não muda o resultado: se a leitura
    falhar no meio (D-4), o gancho já foi chamado e o resultado continua sem
    eventos — quem desconta o minuto é o chamador.

    `parada`, se dada, é consultada antes de cada frame analisado (AC-012.5 de
    `interface-sessao`, SUP-108). Pedida, levanta `ProcessamentoCancelado` sem
    mandar mais nenhum frame ao detector, e o clipe não devolve resultado.
    """
    rastreador = rastreador_para_o_clipe(minuto, fabrica_de_bytetrack)
    amostragem = frames_amostrados(caminho, config.amostragem)

    avaliador: AvaliadorDeCruzamento | None = None
    eventos: list[Evento] = []
    analisados = 0

    for amostra in amostragem:
        if parada is not None and parada.foi_pedida():
            raise ProcessamentoCancelado(
                f"o processamento foi cancelado a pedido do usuário durante o "
                f"minuto {minuto}"
            )
        if avaliador is None:
            fps = amostragem.fps
            if fps is None or fps <= 0:
                return ResultadoDoClipe(
                    eventos=(),
                    fps=None,
                    duracao_em_segundos=0.0,
                    frames_analisados=0,
                    motivo=MOTIVO_SEM_FPS,
                )
            avaliador = AvaliadorDeCruzamento(
                camera=camera,
                rastreador=rastreador,
                inicio_do_clipe=inicio_do_clipe,
                fps=fps,
            )

        analisados += 1
        deteccoes = detector.detectar(amostra.imagem)
        rastreadas = rastreador.atualizar(deteccoes)
        for evento in avaliador.avaliar(rastreadas, indice_do_frame=amostra.indice):
            eventos.append(evento)
            if ao_gerar_evento is not None:
                ao_gerar_evento(evento, fps)

    if amostragem.motivo is not None:
        # D-4: o clipe não abriu ou não tinha frame legível. O que porventura
        # tenha sido contado antes disso não é resultado válido do minuto.
        return ResultadoDoClipe(
            eventos=(),
            fps=amostragem.fps,
            duracao_em_segundos=0.0,
            frames_analisados=0,
            motivo=amostragem.motivo,
        )

    fps = amostragem.fps
    duracao = amostragem.total_de_frames / fps if fps else 0.0
    return ResultadoDoClipe(
        eventos=tuple(eventos),
        fps=fps,
        duracao_em_segundos=duracao,
        frames_analisados=analisados,
        motivo=None,
    )

"""Amostragem de frames do clipe — T-05.

Comportamento definido em `.spec/features/contagem-veiculos/spec.md`: AC-005.3
— o número de frames analisados corresponde à taxa de amostragem declarada, e
os demais frames **não passam por inferência**. Implementa SUP-017, cujo padrão
é 1 frame a cada 3.

A regra de amostragem é a fixada em T-05, porque a spec dá a taxa e não a
fórmula: são analisados os frames de índice `i` com `i % amostragem == 0`, o
que dá `ceil(total / amostragem)` frames.

Os frames não amostrados ainda são **lidos** — o OpenCV decodifica em sequência
—, mas não são entregues a ninguém: o que AC-005.3 proíbe é chamar o detector
para eles, e é o que este módulo garante ao não os produzir.

Cada amostra carrega o **índice do frame no clipe**, que é o que T-06 usa para
datar o evento (AC-006.5): sem ele o timestamp não existe.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import cv2
import numpy as np

MOTIVO_NAO_ABRE = "o arquivo não abre como vídeo"
MOTIVO_SEM_FRAMES = "o vídeo não tem nenhum frame legível"


@dataclass(frozen=True)
class FrameAmostrado:
    """Um frame que vai à inferência, com sua posição no clipe.

    Congelada porque o índice é a âncora temporal do evento (AC-006.5): quem
    recebe a amostra não pode reescrever de que instante do clipe ela veio.
    """

    indice: int
    """Posição do frame no clipe, contada de zero, na ordem de decodificação."""

    imagem: np.ndarray
    """O frame em BGR, como o OpenCV entrega, sem redimensionamento — quem
    normaliza para os 640×640 de SUP-015 é o detector (T-04)."""


class AmostragemDoClipe:
    """Iterador dos frames amostrados de um clipe, que também diz o que houve.

    É um objeto, e não uma função geradora simples, porque T-05 pede duas
    coisas ao mesmo tempo: iterar as amostras e **sinalizar o motivo** quando o
    clipe não rende nada, para que o chamador aplique D-4 (minuto sem dado, a
    sessão segue) em vez de receber uma exceção. Um `return` de gerador não
    chega a quem faz `for`, então o motivo fica aqui.

    `fps` e `total_de_frames` são lidos do próprio arquivo, nunca fixados em
    código: outra câmera da NitTrans pode gravar em outra taxa.
    """

    def __init__(self, caminho: Path | str, amostragem: int) -> None:
        if amostragem < 1:
            raise ValueError(
                f"amostragem precisa ser um inteiro de pelo menos 1 frame, e "
                f"não {amostragem} (SUP-017)"
            )
        self.caminho = Path(caminho)
        self.amostragem = amostragem
        self.motivo: str | None = None
        """`None` enquanto nada deu errado; o motivo de D-4 quando deu."""
        self.fps: float | None = None
        self.total_de_frames: int = 0
        """Frames efetivamente decodificados, que é o total que este clipe tem
        a oferecer — o declarado no cabeçalho pode mentir sobre o arquivo."""

    def __iter__(self) -> Iterator[FrameAmostrado]:
        captura = None
        try:
            captura = cv2.VideoCapture(str(self.caminho))
            if not captura.isOpened():
                self.motivo = MOTIVO_NAO_ABRE
                return
            self.fps = float(captura.get(cv2.CAP_PROP_FPS))
            yield from self._percorrer(captura)
            if self.total_de_frames == 0:
                self.motivo = MOTIVO_SEM_FRAMES
        except (cv2.error, OSError, ValueError):
            # Clipe corrompido não derruba a execução (`CLAUDE.md`): vale o
            # mesmo caminho do arquivo que não abre, e o chamador aplica D-4.
            self.motivo = MOTIVO_NAO_ABRE
        finally:
            if captura is not None:
                try:
                    captura.release()
                except cv2.error:
                    pass

    def _percorrer(self, captura) -> Iterator[FrameAmostrado]:
        """Decodifica em sequência e produz só os frames da taxa declarada."""
        indice = 0
        while True:
            leu, imagem = captura.read()
            if not leu:
                return
            self.total_de_frames = indice + 1
            if indice % self.amostragem == 0:
                yield FrameAmostrado(indice=indice, imagem=imagem)
            indice += 1


def frames_amostrados(caminho: Path | str, amostragem: int) -> AmostragemDoClipe:
    """Percorre o clipe e devolve apenas os frames que vão à inferência.

    `amostragem` é o passo de SUP-017: 1 analisa todos os frames, 3 analisa um
    a cada três. Clipe ilegível ou sem frames não levanta erro — a iteração
    termina vazia e `motivo` diz por quê.
    """
    return AmostragemDoClipe(caminho, amostragem)

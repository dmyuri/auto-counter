"""Leitura do vídeo enviado: legível, duração, resolução e sha256.

Comportamento em `.spec/features/upload-videos/spec.md`: SUP-083 (legível e
duração), SUP-086 (resolução lida do próprio arquivo) e SUP-085 (sha256 para a
duplicata), com as decisões de forma D-5 e D-6.

"Legível" é SUP-011, reaproveitado de `capture/readable.py` sem condição a
mais. A duração é `frames ÷ fps`, truncada ao segundo. Legível com FPS zero ou
contagem de frames zero não tem duração confiável e vale como ilegível.

`ler_video` nunca levanta. `iniciar_leitura` roda a leitura num único worker em
segundo plano (D-6), para a interface poder mostrar "Lendo vídeos…" sem ficar
parada, sem disputar CPU e na ordem de recebimento. Nada aqui importa
`streamlit`.
"""

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import cv2

from auto_counter.capture.content import sha256_do_arquivo
from auto_counter.capture.readable import e_legivel


@dataclass(frozen=True)
class LeituraDoVideo:
    """Resultado da leitura. Ilegível tem os outros quatro campos `None`."""

    legivel: bool
    duracao_segundos: int | None
    largura: int | None
    altura: int | None
    sha256: str | None


_ILEGIVEL = LeituraDoVideo(
    legivel=False, duracao_segundos=None, largura=None, altura=None, sha256=None
)


def ler_video(caminho: Path | str) -> LeituraDoVideo:
    """Lê o arquivo enviado (D-5). Nunca levanta."""
    try:
        if not e_legivel(caminho):
            return _ILEGIVEL
        captura = cv2.VideoCapture(str(caminho))
        try:
            quadros = captura.get(cv2.CAP_PROP_FRAME_COUNT)
            fps = captura.get(cv2.CAP_PROP_FPS)
            largura = int(captura.get(cv2.CAP_PROP_FRAME_WIDTH))
            altura = int(captura.get(cv2.CAP_PROP_FRAME_HEIGHT))
        finally:
            captura.release()
        if not fps or fps <= 0 or not quadros or quadros <= 0:
            return _ILEGIVEL
        return LeituraDoVideo(
            legivel=True,
            duracao_segundos=int(quadros / fps),
            largura=largura,
            altura=altura,
            sha256=sha256_do_arquivo(caminho),
        )
    except (cv2.error, OSError, ValueError):
        return _ILEGIVEL


_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="leitura-video")
"""Um worker só, criado uma vez por processo (D-6)."""


def iniciar_leitura(caminho: Path | str) -> "Future[LeituraDoVideo]":
    """Submete `ler_video` ao worker em segundo plano (D-6)."""
    return _EXECUTOR.submit(ler_video, caminho)

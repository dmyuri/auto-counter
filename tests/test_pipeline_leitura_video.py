"""Leitura do vídeo enviado.

Critérios de `.spec/features/upload-videos/spec.md`, do lado da leitura:
AC-027.3 (duração), AC-027.4 (legível, SUP-011), AC-027.5 (resolução lida do
arquivo) e AC-027.7 (sha256, SUP-051). Duração e formato em SUP-083.

Vídeos de teste são gerados em `tmp_path` com `cv2.VideoWriter`; nada é
versionado.
"""

import hashlib
from concurrent.futures import Future
from pathlib import Path

import cv2
import numpy as np

from auto_counter.pipeline.leitura_video import (
    LeituraDoVideo,
    iniciar_leitura,
    ler_video,
)


def escreve_video(
    caminho: Path, *, quadros: int, fps: float, largura: int = 64, altura: int = 48
) -> Path:
    escritor = cv2.VideoWriter(
        str(caminho), cv2.VideoWriter_fourcc(*"mp4v"), fps, (largura, altura)
    )
    assert escritor.isOpened(), "o codec mp4v não está disponível nesta máquina"
    try:
        for _ in range(quadros):
            escritor.write(np.zeros((altura, largura, 3), dtype=np.uint8))
    finally:
        escritor.release()
    assert caminho.exists() and caminho.stat().st_size > 0
    return caminho


def test_AC_027_3_duracao_e_frames_sobre_fps_truncada(tmp_path):
    video = escreve_video(tmp_path / "a.mp4", quadros=25, fps=10)

    leitura = ler_video(video)

    assert leitura.legivel is True
    assert leitura.duracao_segundos == 2  # 2,5 s truncado ao segundo


def test_AC_027_5_resolucao_lida_do_arquivo(tmp_path):
    video = escreve_video(tmp_path / "a.mp4", quadros=10, fps=10, largura=320, altura=240)

    leitura = ler_video(video)

    assert leitura.largura == 320
    assert leitura.altura == 240


def test_AC_027_7_sha256_e_o_do_conteudo(tmp_path):
    video = escreve_video(tmp_path / "a.mp4", quadros=10, fps=10)

    leitura = ler_video(video)

    assert leitura.sha256 == hashlib.sha256(video.read_bytes()).hexdigest()


def test_AC_027_4_bytes_quaisquer_com_extensao_de_video_sao_ilegiveis(tmp_path):
    falso = tmp_path / "falso.mp4"
    falso.write_bytes(b"isto nao e um video" * 100)

    leitura = ler_video(falso)

    assert leitura == LeituraDoVideo(
        legivel=False,
        duracao_segundos=None,
        largura=None,
        altura=None,
        sha256=None,
    )


def test_AC_027_4_arquivo_inexistente_e_ilegivel_sem_levantar(tmp_path):
    leitura = ler_video(tmp_path / "nao_existe.mp4")

    assert leitura.legivel is False
    assert leitura.duracao_segundos is None
    assert leitura.largura is None
    assert leitura.altura is None
    assert leitura.sha256 is None


def test_iniciar_leitura_devolve_future_com_o_mesmo_resultado_de_ler_video(tmp_path):
    video = escreve_video(tmp_path / "a.mp4", quadros=20, fps=10)

    futuro = iniciar_leitura(video)

    assert isinstance(futuro, Future)
    assert futuro.result(timeout=30) == ler_video(video)

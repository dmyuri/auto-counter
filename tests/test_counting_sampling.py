"""Amostragem de frames do clipe — T-05.

Critério coberto, de `.spec/features/contagem-veiculos/spec.md`:

- AC-005.3 — dado um clipe e a taxa de amostragem configurada, o número de
  frames analisados corresponde à taxa declarada e os demais frames não passam
  por inferência.

A taxa é a de SUP-017 (padrão 1 a cada 3, configurável). A fórmula é a fixada
em T-05: são analisados os frames de índice `i` com `i % amostragem == 0`, ou
seja `ceil(total / amostragem)` frames.

As fixtures são geradas no próprio teste, em diretório temporário: nenhum vídeo
entra no repositório. Se o codec `mp4v` não existir na máquina, o teste
**falha** — `audit.py` trata teste pulado igual a teste que falhou, então não há
`skip` condicional aqui.
"""

import math
from pathlib import Path

import cv2
import numpy as np

from auto_counter.counting.sampling import frames_amostrados

LARGURA = 64
ALTURA = 48
QUADROS = 31
"""Deliberadamente não múltiplo de 3: com amostragem 3 o último bloco é
incompleto, e é aí que `ceil` se distingue de divisão inteira."""


def _escreve_video(caminho: Path, quadros: int = QUADROS) -> Path:
    """MP4 válido e curto, escrito com `cv2.VideoWriter` no codec `mp4v`.

    Cada frame recebe um tom de cinza próprio do seu índice, para que o teste
    possa afirmar **qual** frame chegou, e não apenas quantos.
    """
    escritor = cv2.VideoWriter(
        str(caminho), cv2.VideoWriter_fourcc(*"mp4v"), 30.0, (LARGURA, ALTURA)
    )
    assert escritor.isOpened(), (
        "o codec mp4v não está disponível nesta máquina e a fixture de vídeo "
        "válido não pôde ser gerada"
    )
    try:
        for indice in range(quadros):
            escritor.write(np.full((ALTURA, LARGURA, 3), indice * 8, dtype=np.uint8))
    finally:
        escritor.release()
    assert caminho.exists() and caminho.stat().st_size > 0
    return caminho


class _DetectorEspiao:
    """Dublê no lugar do detector, que anota todo frame que lhe é entregue.

    É o instrumento de AC-005.3: o critério é sobre o que **chega à
    inferência**, então provar o descarte exige um detector que conte chamadas.
    """

    def __init__(self) -> None:
        self.indices_recebidos: list[int] = []

    def detectar(self, amostra) -> None:
        self.indices_recebidos.append(amostra.indice)


def test_AC_005_3_numero_de_frames_analisados_corresponde_a_taxa_declarada(tmp_path):
    caminho = _escreve_video(tmp_path / "clipe.mp4")

    amostras = list(frames_amostrados(caminho, amostragem=3))

    assert len(amostras) == math.ceil(QUADROS / 3)


def test_AC_005_3_frames_nao_amostrados_nao_passam_por_inferencia(tmp_path):
    caminho = _escreve_video(tmp_path / "clipe.mp4")
    detector = _DetectorEspiao()

    for amostra in frames_amostrados(caminho, amostragem=3):
        detector.detectar(amostra)

    assert detector.indices_recebidos == list(range(0, QUADROS, 3))


def test_AC_005_3_amostragem_de_um_analisa_todos_os_frames(tmp_path):
    caminho = _escreve_video(tmp_path / "clipe.mp4")

    amostras = list(frames_amostrados(caminho, amostragem=1))

    assert [amostra.indice for amostra in amostras] == list(range(QUADROS))


def test_AC_005_3_indice_do_frame_no_clipe_acompanha_cada_amostra(tmp_path):
    caminho = _escreve_video(tmp_path / "clipe.mp4")

    amostras = list(frames_amostrados(caminho, amostragem=3))

    assert [amostra.indice for amostra in amostras] == list(range(0, QUADROS, 3))
    for amostra in amostras:
        assert amostra.imagem.shape == (ALTURA, LARGURA, 3)


def test_AC_005_3_arquivo_que_nao_abre_como_video_termina_vazio_com_motivo(tmp_path):
    """T-05: clipe ilegível não estoura exceção — o gerador termina vazio e
    sinaliza o motivo, que é o que o chamador leva para D-4."""
    caminho = tmp_path / "quebrado.mp4"
    caminho.write_bytes(b"isto nao e um video")

    amostragem = frames_amostrados(caminho, amostragem=3)
    amostras = list(amostragem)

    assert amostras == []
    assert amostragem.motivo is not None


def test_AC_005_3_fps_e_total_sao_lidos_do_proprio_arquivo(tmp_path):
    """T-05: `fps` e contagem de frames vêm do arquivo, nunca fixados em código
    — outra câmera da NitTrans pode ter outra taxa."""
    caminho = _escreve_video(tmp_path / "clipe.mp4")

    amostragem = frames_amostrados(caminho, amostragem=3)
    list(amostragem)

    assert amostragem.fps == 30.0
    assert amostragem.total_de_frames == QUADROS

"""Renderização do PNG de preview da linha de contagem — T-08.

Critérios cobertos, de `.spec/features/configuracao-camera/spec.md`:
AC-002.1 (o PNG tem o frame, a linha desenhada entre os dois pontos e os
rótulos dos sentidos em lados opostos da linha) e AC-002.2 na parte que cai
sobre esta tarefa: linha fora do frame não gera PNG.

O frame é sintético e injetado por parâmetro — o download real é de T-07 e
nenhum teste daqui toca a rede. Que o PNG mostra mesmo a via da câmera 000013,
com cada rótulo do lado certo, é conferido por olho humano em T-10, que é o
momento de calibração previsto por AC-002.1 e SUP-003.

O lado de cada rótulo é medido pelo sinal do produto escalar entre a normal de
SUP-003 e o vetor que vai do meio da linha até o rótulo: sinais opostos são
semiplanos opostos.
"""

import cv2
import numpy as np
import pytest

from auto_counter.cameras.geometry import LinhaForaDoFrameError, normal_da_linha
from auto_counter.cameras.model import Camera
from auto_counter.cameras.preview import gravar_preview

LARGURA_DO_FRAME = 320
ALTURA_DO_FRAME = 240
CINZA_DE_FUNDO = 90


@pytest.fixture
def frame() -> np.ndarray:
    """Frame sintético uniforme: qualquer pixel diferente foi desenhado."""
    return np.full(
        (ALTURA_DO_FRAME, LARGURA_DO_FRAME, 3), CINZA_DE_FUNDO, dtype=np.uint8
    )


def camera_com_linha(p1: tuple[int, int], p2: tuple[int, int]) -> Camera:
    return Camera(
        resolucao={"largura": 1280, "altura": 720},
        id="000013",
        nome="Local de teste",
        sentido_a="Centro",
        sentido_b="Bairro",
        linha={
            "p1": {"x": p1[0], "y": p1[1]},
            "p2": {"x": p2[0], "y": p2[1]},
        },
    )


def pontos_do_segmento(p1, p2, quantidade=9):
    """Pontos amostrados ao longo do segmento, sem incluir as extremidades."""
    for passo in range(1, quantidade + 1):
        fracao = passo / (quantidade + 1)
        yield (
            round(p1[0] + (p2[0] - p1[0]) * fracao),
            round(p1[1] + (p2[1] - p1[1]) * fracao),
        )


def lado_em_relacao_a_linha(camera: Camera, ponto) -> float:
    """Sinal do semiplano em que `ponto` cai, pela normal de SUP-003."""
    nx, ny = normal_da_linha(camera.linha)
    meio_x = (camera.linha.p1.x + camera.linha.p2.x) / 2
    meio_y = (camera.linha.p1.y + camera.linha.p2.y) / 2
    return (ponto[0] - meio_x) * nx + (ponto[1] - meio_y) * ny


def test_AC_002_1_preview_grava_png_com_a_linha_desenhada_entre_os_dois_pontos(
    frame, tmp_path
):
    p1, p2 = (40, 200), (280, 60)
    camera = camera_com_linha(p1, p2)
    destino = tmp_path / "preview.png"

    gravar_preview(frame, camera, destino)

    assert destino.exists()
    imagem = cv2.imread(str(destino))
    assert imagem is not None, "o arquivo gravado não é um PNG legível"
    assert imagem.shape == (ALTURA_DO_FRAME, LARGURA_DO_FRAME, 3)

    # A linha foi desenhada ao longo de todo o segmento entre p1 e p2: cada
    # ponto amostrado tem pixel diferente do fundo na sua vizinhança imediata.
    for x, y in pontos_do_segmento(p1, p2):
        vizinhanca = imagem[y - 2 : y + 3, x - 2 : x + 3]
        assert (vizinhanca != CINZA_DE_FUNDO).any(), (
            f"nada desenhado sobre o ponto ({x}, {y}) do segmento"
        )

    # O frame original continua embaixo: o preview não é uma tela em branco.
    assert (imagem == CINZA_DE_FUNDO).any()

    # A imagem de entrada não é modificada no lugar.
    assert (frame == CINZA_DE_FUNDO).all()


def test_AC_002_1_rotulos_dos_sentidos_ficam_em_lados_opostos_da_linha(
    frame, tmp_path
):
    p1, p2 = (40, 200), (280, 60)
    camera = camera_com_linha(p1, p2)
    destino = tmp_path / "preview.png"

    resultado = gravar_preview(frame, camera, destino)

    # `sentido_a` do lado apontado pela normal de SUP-003, `sentido_b` do
    # oposto: os sinais têm de ser contrários e nenhum dos dois pode ser zero
    # (rótulo em cima da linha não é "lado oposto").
    lado_a = lado_em_relacao_a_linha(camera, resultado.posicao_sentido_a)
    lado_b = lado_em_relacao_a_linha(camera, resultado.posicao_sentido_b)
    assert lado_a > 0, "sentido_a não caiu no lado apontado pela normal"
    assert lado_b < 0, "sentido_b não caiu no lado oposto ao da normal"

    # E os rótulos foram mesmo desenhados nesses lados: há pixels alterados
    # em ambos os semiplanos, longe o bastante da linha para não serem a
    # própria linha.
    imagem = cv2.imread(str(destino))
    alterados = np.argwhere((imagem != CINZA_DE_FUNDO).any(axis=2))
    nx, ny = normal_da_linha(camera.linha)
    meio_x = (camera.linha.p1.x + camera.linha.p2.x) / 2
    meio_y = (camera.linha.p1.y + camera.linha.p2.y) / 2
    distancias = (alterados[:, 1] - meio_x) * nx + (alterados[:, 0] - meio_y) * ny
    fora_da_linha = distancias[np.abs(distancias) > 6]
    assert (fora_da_linha > 0).any(), "nenhum rótulo desenhado do lado da normal"
    assert (fora_da_linha < 0).any(), "nenhum rótulo desenhado do lado oposto"

    # Os dois rótulos cabem dentro do frame.
    for posicao in (resultado.posicao_sentido_a, resultado.posicao_sentido_b):
        assert 0 <= posicao[0] < LARGURA_DO_FRAME
        assert 0 <= posicao[1] < ALTURA_DO_FRAME


def test_AC_002_2_linha_fora_do_frame_nao_gera_png(frame, tmp_path):
    # A linha é válida como modelo (dois pontos distintos), mas não cabe no
    # frame recebido: o preview tem de recusar antes de desenhar qualquer
    # coisa, com o erro de AC-002.2.
    camera = camera_com_linha((10, 10), (LARGURA_DO_FRAME, 100))
    destino = tmp_path / "preview.png"

    with pytest.raises(LinhaForaDoFrameError) as erro:
        gravar_preview(frame, camera, destino)

    mensagem = str(erro.value)
    assert str(LARGURA_DO_FRAME) in mensagem
    assert str(ALTURA_DO_FRAME) in mensagem
    assert not destino.exists(), "linha fora do frame não pode gerar PNG"

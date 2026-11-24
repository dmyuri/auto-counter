"""Renderização do PNG de preview da linha de contagem.

Comportamento em `.spec/features/configuracao-camera/spec.md`: AC-002.1 — o
PNG tem um frame da câmera, a linha desenhada entre os dois pontos e os
rótulos dos sentidos A e B posicionados em lados opostos da linha.

Qual rótulo cai de cada lado sai da normal de SUP-003: `sentido_a` do lado
apontado pela normal e `sentido_b` do oposto. O PNG é justamente o instrumento
de conferir isso na calibração (T-10), então a única garantia daqui é que a
convenção é aplicada de forma estável — não que ela está certa para a via.

Antes de desenhar, a linha é validada contra as dimensões do frame recebido
(AC-002.2): linha fora do frame não gera PNG.
"""

import os
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from auto_counter.cameras.geometry import normal_da_linha, validar_linha_no_frame
from auto_counter.cameras.model import Camera

COR_DA_LINHA = (0, 0, 255)
"""Vermelho em BGR, a ordem de canais do OpenCV."""

COR_DO_TEXTO = (0, 255, 255)
"""Amarelo em BGR: contrasta com a linha e com asfalto."""

FONTE = cv2.FONT_HERSHEY_SIMPLEX

FRACAO_DO_AFASTAMENTO = 0.08
"""Afastamento do rótulo em relação ao meio da linha, como fração do frame.

É relativo porque a resolução vem do vídeo da própria câmera (SUP-007): um
afastamento fixo em pixels ficaria colado na linha num frame grande e jogaria
o rótulo para fora num frame pequeno.
"""

AFASTAMENTO_MINIMO = 14
"""Piso em pixels do afastamento, para o rótulo nunca encostar na linha."""


@dataclass(frozen=True)
class PreviewGravado:
    """Onde o PNG foi gravado e em que ponto cada rótulo ficou.

    As posições são o centro de cada rótulo, em pixels do frame. Elas voltam
    para que o lado de cada sentido seja verificável sem depender de ler texto
    de dentro da imagem.
    """

    caminho: Path
    posicao_sentido_a: tuple[int, int]
    posicao_sentido_b: tuple[int, int]


def _escala_do_texto(altura: int) -> tuple[float, int]:
    """Escala e espessura da fonte proporcionais à altura do frame."""
    escala = max(0.4, altura / 600)
    espessura = max(1, round(escala * 2))
    return escala, espessura


def _desenha_rotulo(
    imagem: np.ndarray, texto: str, centro: tuple[float, float], escala, espessura
) -> tuple[int, int]:
    """Escreve `texto` centrado em `centro`, contido nos limites do frame.

    Devolve o centro efetivo, que difere do pedido quando o rótulo precisou
    ser trazido para dentro do frame.
    """
    altura, largura = imagem.shape[:2]
    (largura_texto, altura_texto), _ = cv2.getTextSize(texto, FONTE, escala, espessura)

    x = centro[0] - largura_texto / 2
    y = centro[1] + altura_texto / 2
    x = min(max(x, 0), max(largura - largura_texto, 0))
    y = min(max(y, altura_texto), altura - 1)

    cv2.putText(
        imagem,
        texto,
        (round(x), round(y)),
        FONTE,
        escala,
        COR_DO_TEXTO,
        espessura,
        cv2.LINE_AA,
    )
    return (round(x + largura_texto / 2), round(y - altura_texto / 2))


def gravar_preview(frame: np.ndarray, camera: Camera, caminho) -> PreviewGravado:
    """Grava o PNG de conferência da linha de contagem da câmera (AC-002.1).

    `frame` é um frame da câmera — em produção o primeiro frame legível do
    clipe baixado na hora (SUP-005), obtido por `frame.primeiro_frame`. Aqui
    ele chega por parâmetro para que o desenho seja testável sem rede.

    Levanta `LinhaForaDoFrameError` quando a linha não cabe nas dimensões do
    frame recebido (AC-002.2), antes de desenhar ou gravar qualquer coisa.
    """
    altura, largura = frame.shape[:2]
    validar_linha_no_frame(camera.linha, largura, altura)

    imagem = frame.copy()
    p1 = (camera.linha.p1.x, camera.linha.p1.y)
    p2 = (camera.linha.p2.x, camera.linha.p2.y)
    escala, espessura = _escala_do_texto(altura)
    cv2.line(imagem, p1, p2, COR_DA_LINHA, max(2, espessura), cv2.LINE_AA)

    normal_x, normal_y = normal_da_linha(camera.linha)
    meio = ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)
    afastamento = max(AFASTAMENTO_MINIMO, FRACAO_DO_AFASTAMENTO * min(largura, altura))

    # `sentido_a` do lado apontado pela normal, `sentido_b` do oposto (SUP-003).
    posicao_a = _desenha_rotulo(
        imagem,
        camera.sentido_a,
        (meio[0] + normal_x * afastamento, meio[1] + normal_y * afastamento),
        escala,
        espessura,
    )
    posicao_b = _desenha_rotulo(
        imagem,
        camera.sentido_b,
        (meio[0] - normal_x * afastamento, meio[1] - normal_y * afastamento),
        escala,
        espessura,
    )

    destino = Path(caminho)
    if destino.parent != Path(""):
        os.makedirs(destino.parent, exist_ok=True)
    if not cv2.imwrite(str(destino), imagem):
        raise OSError(f"não foi possível gravar o PNG de preview em {destino}")

    return PreviewGravado(
        caminho=destino, posicao_sentido_a=posicao_a, posicao_sentido_b=posicao_b
    )

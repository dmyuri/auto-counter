"""Geometria da linha de contagem.

Por enquanto só a normal que separa os dois sentidos (SUP-003). A validação
da linha contra as dimensões do frame (AC-002.2) entra quando essas dimensões
existirem, lidas do vídeo da própria câmera (SUP-007).
"""

import math

from auto_counter.cameras.model import Linha


def normal_da_linha(linha: Linha) -> tuple[float, float]:
    """Normal unitária que separa o sentido A do sentido B (SUP-003).

    O vetor `v = p2 - p1` dá a orientação da linha; a normal é esse vetor
    girado 90 graus no sistema de coordenadas de pixel (x cresce para a
    direita, y cresce para baixo): `(dx, dy) -> (-dy, dx)`.

    `sentido_a` rotula os cruzamentos que acontecem no sentido dessa normal e
    `sentido_b` os do sentido oposto. Qual dos dois rótulos cai de cada lado
    é conferido no PNG de calibração (AC-002.1) — o código só garante que a
    convenção é estável.

    A linha nunca chega degenerada: `Linha` já rejeita `p1 == p2` (AC-002.3),
    então o comprimento nunca é zero.
    """
    dx = linha.p2.x - linha.p1.x
    dy = linha.p2.y - linha.p1.y
    comprimento = math.hypot(dx, dy)
    return (-dy / comprimento, dx / comprimento)

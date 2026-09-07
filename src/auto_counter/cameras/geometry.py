"""Geometria da linha de contagem.

Duas coisas: a normal que separa os dois sentidos (SUP-003) e a validação da
linha contra as dimensões do frame (AC-002.2).

A validação de limites é uma função separada da validação do modelo porque as
dimensões do frame são lidas do vídeo da própria câmera e nunca fixadas em
código (SUP-007) — outra câmera da NitTrans pode ter resolução diferente da
câmera do MVP. Por isso elas chegam por parâmetro: quem conhece o frame passa
largura e altura, e nada aqui presume uma resolução.
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


class LinhaForaDoFrameError(Exception):
    """Ponto da linha fora dos limites do frame (AC-002.2).

    A mensagem cita a coordenada inválida e as dimensões do frame usadas na
    conferência, porque sem as duas informações não dá para saber se o errado
    é a calibração ou a resolução com que ela foi conferida.
    """


def validar_linha_no_frame(linha: Linha, largura: int, altura: int) -> None:
    """Rejeita a linha se qualquer um dos dois pontos cair fora do frame.

    Convenção de borda: a coordenada é índice de pixel, logo `x` é válido em
    `0..largura-1` e `y` em `0..altura-1`. `x == largura` já é o primeiro
    pixel fora, e coordenada negativa também é inválida.

    `largura` e `altura` vêm do vídeo da câmera (SUP-007) e por isso são
    parâmetro, não constante. Devolve `None` quando a linha cabe no frame.
    """
    fora = []
    for nome, ponto in (("p1", linha.p1), ("p2", linha.p2)):
        if not 0 <= ponto.x < largura:
            fora.append(f"{nome}.x={ponto.x}")
        if not 0 <= ponto.y < altura:
            fora.append(f"{nome}.y={ponto.y}")

    if fora:
        raise LinhaForaDoFrameError(
            "linha fora dos limites do frame: "
            + ", ".join(fora)
            + f"; o frame tem {largura}x{altura} pixels, então x é válido em "
            f"0..{largura - 1} e y em 0..{altura - 1}"
        )

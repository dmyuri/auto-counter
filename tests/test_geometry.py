"""Validação da linha de contagem contra as dimensões do frame — T-06.

Critério coberto, de `.spec/features/configuracao-camera/spec.md`: AC-002.2
(ponto da linha fora dos limites do frame rejeita a câmera com erro que cita a
coordenada inválida e as dimensões do frame).

As dimensões chegam **por parâmetro** porque são lidas do vídeo da própria
câmera e nunca fixadas em código (SUP-007): outra câmera da NitTrans pode ter
resolução diferente da 000013. É isso que permite testar sem rede e sem vídeo.

Convenção de borda testada aqui: `x` válido em `0..largura-1` e `y` em
`0..altura-1`, como um índice de pixel. Logo `x == largura` é inválido.
"""

import inspect
import re

import pytest

from auto_counter.cameras import geometry as modulo_geometry
from auto_counter.cameras.geometry import (
    LinhaForaDoFrameError,
    validar_linha_no_frame,
)
from auto_counter.cameras.model import Linha


def linha(p1: tuple[int, int], p2: tuple[int, int]) -> Linha:
    return Linha(
        p1={"x": p1[0], "y": p1[1]},
        p2={"x": p2[0], "y": p2[1]},
    )


@pytest.mark.parametrize(
    ("pontos", "coordenada_citada"),
    [
        # x == largura e y == altura são o primeiro pixel fora de cada eixo.
        (((1280, 400), (100, 400)), "x=1280"),
        (((100, 400), (1280, 400)), "x=1280"),
        (((100, 720), (200, 400)), "y=720"),
        (((-1, 400), (200, 400)), "x=-1"),
        (((100, -5), (200, 400)), "y=-5"),
        (((5000, 9000), (200, 400)), "x=5000"),
    ],
)
def test_AC_002_2_ponto_fora_do_frame_e_rejeitado_citando_coordenada_e_dimensoes(
    pontos, coordenada_citada
):
    with pytest.raises(LinhaForaDoFrameError) as erro:
        validar_linha_no_frame(linha(*pontos), largura=1280, altura=720)

    mensagem = str(erro.value)
    assert coordenada_citada in mensagem
    assert "1280" in mensagem and "720" in mensagem


@pytest.mark.parametrize(
    "pontos",
    [
        # Os quatro cantos do frame e as bordas extremas de cada eixo.
        ((0, 0), (1279, 719)),
        ((1279, 0), (0, 719)),
        ((0, 400), (1279, 400)),
        ((640, 0), (640, 719)),
    ],
)
def test_AC_002_2_ponto_na_borda_do_frame_e_aceito(pontos):
    validar_linha_no_frame(linha(*pontos), largura=1280, altura=720)


def test_AC_002_2_dimensoes_vem_por_parametro_e_nao_sao_fixas_no_codigo():
    # A mesma linha é válida num frame grande e inválida num frame menor: se as
    # dimensões estivessem fixas no código, o resultado seria o mesmo nos dois
    # casos (SUP-007).
    l = linha((0, 0), (1279, 719))

    validar_linha_no_frame(l, largura=1280, altura=720)

    with pytest.raises(LinhaForaDoFrameError) as erro:
        validar_linha_no_frame(l, largura=640, altura=480)
    assert "640" in str(erro.value) and "480" in str(erro.value)

    # E o módulo não traz a resolução da 000013 escrita em lugar nenhum.
    fonte = inspect.getsource(modulo_geometry)
    assert not re.search(r"\b(1280|720)\b", fonte)

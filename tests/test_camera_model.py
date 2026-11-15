"""Modelo de câmera e de linha — T-02.

Critérios cobertos, de `.spec/features/configuracao-camera/spec.md`:
AC-001.2 (campo obrigatório ausente ou de tipo inválido), AC-002.3 (linha
degenerada) e AC-002.4 (câmera sem linha não vira modelo válido).

Os erros aqui nomeiam o **campo**; nomear o **arquivo** é responsabilidade do
registro (T-03), que é quem conhece o caminho.
"""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from auto_counter.cameras.geometry import normal_da_linha
from auto_counter.cameras.model import Camera, Linha

CAMERA_VALIDA = {
    "id": "000013",
    "nome": "Camera de exemplo",
    "sentido_a": "sentido A",
    "sentido_b": "sentido B",
    "linha": {"p1": {"x": 120, "y": 400}, "p2": {"x": 1160, "y": 420}},
    "resolucao": {"largura": 1280, "altura": 720},
}

CAMPOS_OBRIGATORIOS = ("id", "nome", "sentido_a", "sentido_b", "linha")


def locs(erro: ValidationError) -> list[tuple]:
    """Os caminhos de campo que o Pydantic aponta como problemáticos."""
    return [e["loc"] for e in erro.errors()]


def test_AC_001_2_campo_obrigatorio_ausente_e_rejeitado_citando_o_campo():
    for campo in CAMPOS_OBRIGATORIOS:
        dados = deepcopy(CAMERA_VALIDA)
        del dados[campo]

        with pytest.raises(ValidationError) as erro:
            Camera(**dados)

        assert locs(erro.value) == [(campo,)], (
            f"o erro de '{campo}' ausente deveria apontar exatamente esse campo"
        )
        assert erro.value.errors()[0]["type"] == "missing"
        assert campo in str(erro.value)


def test_AC_001_2_campo_com_tipo_invalido_e_rejeitado_citando_o_campo():
    # id numérico é o caso do YAML sem aspas (SUP-001): `000013` sem aspas vira
    # número e perderia os zeros à esquerda. Rejeitado, nunca convertido calado.
    dados = deepcopy(CAMERA_VALIDA)
    dados["id"] = 13
    with pytest.raises(ValidationError) as erro:
        Camera(**dados)
    assert locs(erro.value) == [("id",)]
    assert "id" in str(erro.value)

    dados = deepcopy(CAMERA_VALIDA)
    dados["nome"] = 42
    with pytest.raises(ValidationError) as erro:
        Camera(**dados)
    assert locs(erro.value) == [("nome",)]
    assert "nome" in str(erro.value)

    # coordenada de pixel é inteira (SUP-002)
    dados = deepcopy(CAMERA_VALIDA)
    dados["linha"]["p1"]["x"] = "esquerda"
    with pytest.raises(ValidationError) as erro:
        Camera(**dados)
    assert locs(erro.value) == [("linha", "p1", "x")]
    assert "x" in str(erro.value)


def test_AC_002_3_linha_com_pontos_iguais_e_rejeitada_como_degenerada():
    with pytest.raises(ValidationError) as erro:
        Linha(p1={"x": 500, "y": 300}, p2={"x": 500, "y": 300})
    assert "degenerada" in str(erro.value).lower()

    # a mensagem é específica: não se confunde com a de campo ausente
    with pytest.raises(ValidationError) as ausente:
        Linha(p1={"x": 500, "y": 300})
    assert "degenerada" not in str(ausente.value).lower()

    # e a câmera inteira cai junto com a linha degenerada
    dados = deepcopy(CAMERA_VALIDA)
    dados["linha"] = {"p1": {"x": 10, "y": 20}, "p2": {"x": 10, "y": 20}}
    with pytest.raises(ValidationError) as pela_camera:
        Camera(**dados)
    assert "degenerada" in str(pela_camera.value).lower()


def test_AC_002_4_camera_sem_linha_nao_produz_modelo_valido():
    dados = deepcopy(CAMERA_VALIDA)
    del dados["linha"]

    with pytest.raises(ValidationError) as erro:
        Camera(**dados)
    assert locs(erro.value) == [("linha",)]
    assert erro.value.errors()[0]["type"] == "missing"

    # não há linha padrão para herdar: o campo é obrigatório e sem default
    campo_linha = Camera.model_fields["linha"]
    assert campo_linha.is_required()
    assert campo_linha.default_factory is None


def test_AC_001_2_camera_sem_resolucao_e_rejeitada_citando_o_campo():
    # SUP-086: `resolucao` é obrigatória, sem valor padrão.
    dados = deepcopy(CAMERA_VALIDA)
    dados.pop("resolucao", None)

    with pytest.raises(ValidationError) as erro:
        Camera(**dados)

    assert locs(erro.value) == [("resolucao",)]
    assert erro.value.errors()[0]["type"] == "missing"
    assert "resolucao" in str(erro.value)


@pytest.mark.parametrize(
    "valor",
    [
        {"largura": "1280", "altura": 720},
        {"largura": 0, "altura": 720},
        {"largura": 1280},
        "1280x720",
    ],
)
def test_AC_001_2_resolucao_de_tipo_invalido_e_rejeitada(valor):
    dados = deepcopy(CAMERA_VALIDA)
    dados["resolucao"] = valor

    with pytest.raises(ValidationError) as erro:
        Camera(**dados)

    assert all(loc[0] == "resolucao" for loc in locs(erro.value))
    assert "resolucao" in str(erro.value)


def test_AC_002_2_linha_fora_da_resolucao_declarada_e_rejeitada():
    dados = deepcopy(CAMERA_VALIDA)
    dados["resolucao"] = {"largura": 1280, "altura": 720}

    # x == largura é o primeiro pixel fora do frame
    fora = deepcopy(dados)
    fora["linha"]["p2"]["x"] = 1280
    with pytest.raises(ValidationError) as erro:
        Camera(**fora)
    mensagem = str(erro.value)
    assert "p2.x=1280" in mensagem
    assert "1280x720" in mensagem

    # x == largura - 1 ainda cabe
    dentro = deepcopy(dados)
    dentro["linha"]["p2"]["x"] = 1279
    assert Camera(**dentro).linha.p2.x == 1279


def test_id_com_zeros_a_esquerda_sobrevive_a_serializacao():
    camera = Camera(**CAMERA_VALIDA)

    assert camera.id == "000013"
    assert camera.model_dump()["id"] == "000013"
    assert '"000013"' in camera.model_dump_json()


def test_normal_da_linha_e_unitaria_e_perpendicular_ao_vetor_p1_p2():
    # SUP-003: o vetor de p1 para p2 define a normal que separa os sentidos.
    # Convenção do código: giro de 90 graus, (dx, dy) -> (-dy, dx), no sistema
    # de pixel (x cresce para a direita, y cresce para baixo).
    linha = Linha(p1={"x": 0, "y": 0}, p2={"x": 10, "y": 0})
    nx, ny = normal_da_linha(linha)

    assert (nx, ny) == pytest.approx((0.0, 1.0))
    assert nx * nx + ny * ny == pytest.approx(1.0)

    # perpendicular a qualquer orientação, não só à horizontal
    diagonal = Linha(p1={"x": 100, "y": 100}, p2={"x": 200, "y": 300})
    nx, ny = normal_da_linha(diagonal)
    dx, dy = 200 - 100, 300 - 100
    assert nx * dx + ny * dy == pytest.approx(0.0)
    assert nx * nx + ny * ny == pytest.approx(1.0)


def test_AC_020_2_camera_sem_preview_e_valida_com_preview_none():
    camera = Camera(**deepcopy(CAMERA_VALIDA))

    assert camera.preview is None


def test_AC_020_2_camera_com_preview_guarda_o_caminho_como_texto():
    camera = Camera(**deepcopy(CAMERA_VALIDA), preview="previas/000013.png")

    assert camera.preview == "previas/000013.png"


@pytest.mark.parametrize("valor", [123, ["a.png"], {"x": 1}, None])
def test_AC_020_2_preview_de_tipo_invalido_vale_como_ausente(valor):
    camera = Camera(**deepcopy(CAMERA_VALIDA), preview=valor)

    assert camera.preview is None

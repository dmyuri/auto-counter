"""Interface: atalhos de duração — T-10 de `layout-interface`.

Critérios cobertos, de `.spec/features/layout-interface/spec.md`: AC-021.1 a
AC-021.3. A regra de 1 a 15 minutos continua a de AC-011.2, verificada em
`tests/test_ui_formulario.py`, sem edição.

O destaque de um atalho é o tipo do botão (`primary` destacado, `secondary`
não), lido de `proto.type`. Nada aqui toca a rede nem grava fora de `tmp_path`.
"""

import pytest

from auto_counter.pipeline.state import Fase
from tests.test_ui_acompanhamento import (  # noqa: F401  (fixtures usadas por nome)
    captura_em_curso,
    clica,
    termina,
    trava_do_run,
)
from tests.test_ui_formulario import (  # noqa: F401  (fixtures usadas por nome)
    abre_a_interface,
    ambiente,
    botao_iniciar,
    disparo,
    registro_com,
)

ATALHOS = ("5 min", "10 min", "15 min")


@pytest.fixture
def uma_camera(tmp_path, monkeypatch):
    registro_com(tmp_path, monkeypatch, "valida_000013.yaml")
    return tmp_path / "data"


def atalhos(at) -> dict[str, object]:
    achados = {b.label: b for b in at.button if b.label in ATALHOS}
    assert list(achados) == list(ATALHOS)
    return achados


def destacados(at) -> list[str]:
    return [rotulo for rotulo, b in atalhos(at).items() if b.proto.type == "primary"]


@pytest.mark.parametrize("minutos", [5, 10, 15])
def test_AC_021_1_atalho_muda_a_duracao_e_so_ele_fica_destacado(uma_camera, minutos):
    at = abre_a_interface()

    at = clica(at, f"{minutos} min")

    assert not at.exception
    assert at.number_input[0].value == minutos
    assert destacados(at) == [f"{minutos} min"]


def test_AC_021_1_atalho_troca_o_destaque_ao_ser_acionado_em_sequencia(uma_camera):
    at = abre_a_interface()

    at = clica(at, "5 min")
    at = clica(at, "10 min")

    assert at.number_input[0].value == 10
    assert destacados(at) == ["10 min"]


def test_AC_021_1_padrao_15_destaca_o_atalho_de_15(uma_camera):
    at = abre_a_interface()

    assert at.number_input[0].value == 15
    assert destacados(at) == ["15 min"]


def test_AC_021_2_valor_digitado_fora_dos_atalhos_nao_destaca_nenhum_e_inicia_com_ele(
    uma_camera, disparo
):
    at = abre_a_interface()

    at.number_input[0].set_value(7)
    at = at.run()

    assert destacados(at) == []
    botao_iniciar(at).click()
    at = at.run()
    assert [chamada[1] for chamada in disparo.chamadas] == [7]


def test_AC_021_2_digitar_um_valor_dos_atalhos_destaca_o_atalho(uma_camera):
    at = abre_a_interface()

    at.number_input[0].set_value(10)
    at = at.run()

    assert destacados(at) == ["10 min"]


@pytest.mark.parametrize("situacao", ["sessao_em_andamento", "resultado"])
def test_AC_021_3_sessao_em_andamento_ou_resultado_trava_campo_e_atalhos(
    uma_camera, situacao
):
    data_dir = uma_camera
    if situacao == "resultado":
        termina(data_dir, Fase.CONCLUIDA, status="COMPLETA")
        at = abre_a_interface()
    else:
        captura_em_curso(data_dir)
        with trava_do_run(data_dir):
            at = abre_a_interface()

    assert at.number_input[0].disabled is True
    # Os atalhos continuam desenhados, só que indisponíveis (D-11).
    assert all(b.disabled for b in atalhos(at).values())

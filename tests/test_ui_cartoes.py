"""Interface: cartões de câmera com prévia — T-09 de `layout-interface`.

Critérios cobertos, de `.spec/features/layout-interface/spec.md`: AC-020.1 a
AC-020.6 (SUP-065, SUP-066, SUP-067).

Imagens de prévia são geradas em `tmp_path` com `cv2.imencode`; nenhuma imagem
nova é versionada. Nada aqui toca a rede nem grava fora de `tmp_path`.

O cartão é um contêiner com a imagem (ou "sem prévia"), o id e o nome do local
em texto, e um botão `camera_<id>` que diz "SELECIONADA" ou "Selecionar". A
imagem é verificada por `at.get("image")`: nesta versão do Streamlit, é assim
que o `AppTest` expõe `st.image` (o nome `"imgs"`, que a tarefa previa como
alternativa, não existe aqui).
"""

import cv2
import httpx
import numpy as np
import pytest

from auto_counter.pipeline.state import Fase
from tests.test_ui_acompanhamento import (  # noqa: F401  (fixtures usadas por nome)
    captura_em_curso,
    termina,
    textos,
    trava_do_run,
)
from tests.test_ui_formulario import (  # noqa: F401  (fixtures usadas por nome)
    abre_a_interface,
    ambiente,
    botao_iniciar,
    botoes_de_cartao,
    cartoes,
    disparo,
    registro_com,
)

DUAS = ("valida_000013.yaml", "valida_000042.yaml")


def rotulos_dos_cartoes(at) -> dict[str, str]:
    return {b.key: b.label for b in botoes_de_cartao(at)}


def tipos_dos_cartoes(at) -> dict[str, str]:
    return {b.key: b.proto.type for b in botoes_de_cartao(at)}


def png_em(caminho) -> None:
    ok, codificada = cv2.imencode(".png", np.full((12, 16, 3), 127, dtype=np.uint8))
    assert ok
    caminho.write_bytes(codificada.tobytes())


def declara_previa(registro, arquivo: str, previa: str) -> None:
    yaml = registro / arquivo
    yaml.write_text(
        yaml.read_text(encoding="utf-8") + f'\npreview: "{previa}"\n', encoding="utf-8"
    )


def test_AC_020_1_n_cameras_validas_dao_n_cartoes_com_id_e_nome(tmp_path, monkeypatch):
    registro_com(tmp_path, monkeypatch, *DUAS)

    at = abre_a_interface()

    assert not at.exception
    assert cartoes(at) == [
        ("000013", "Via de teste - camera 13"),
        ("000042", "Via de teste - camera 42"),
    ]
    assert [b.key for b in botoes_de_cartao(at)] == ["camera_000013", "camera_000042"]


def test_AC_020_1_cartoes_nao_tem_campo_de_texto(tmp_path, monkeypatch):
    registro_com(tmp_path, monkeypatch, *DUAS)

    at = abre_a_interface()

    assert len(at.text_input) == 0
    assert len(at.text_area) == 0
    assert len(at.selectbox) == 0


def test_AC_020_2_cartao_mostra_a_imagem_indicada(tmp_path, monkeypatch):
    registro = registro_com(tmp_path, monkeypatch, *DUAS)
    declara_previa(registro, "valida_000013.yaml", "13.png")
    png_em(registro / "13.png")

    at = abre_a_interface()

    assert not at.exception
    # `st.image` aparece como o elemento "image"; só a 000013 tem prévia.
    assert len(at.get("image")) == 1
    assert textos(at).count("sem prévia") == 1


@pytest.mark.parametrize("caso", ["ausente", "inexistente", "nao_e_imagem"])
def test_AC_020_2_sem_preview_ou_arquivo_que_nao_abre_mostra_sem_previa_e_seleciona(
    tmp_path, monkeypatch, caso
):
    registro = registro_com(tmp_path, monkeypatch, *DUAS)
    if caso == "inexistente":
        declara_previa(registro, "valida_000042.yaml", "nao_existe.png")
    elif caso == "nao_e_imagem":
        declara_previa(registro, "valida_000042.yaml", "texto.png")
        (registro / "texto.png").write_bytes(b"isto nao e uma imagem")

    at = abre_a_interface()

    assert not at.exception
    assert at.get("image") == []
    assert textos(at).count("sem prévia") == 2
    assert at.session_state["camera"] == "000013"

    at.button(key="camera_000042").click()
    at = at.run()

    assert at.session_state["camera"] == "000042"
    assert rotulos_dos_cartoes(at)["camera_000042"] == "SELECIONADA"


def test_AC_020_2_interface_nao_acessa_a_camera_para_a_previa(tmp_path, monkeypatch):
    def proibido(self, *args, **kwargs):
        raise AssertionError("a interface não pode acessar a rede para a prévia")

    monkeypatch.setattr(httpx.Client, "send", proibido)
    registro = registro_com(tmp_path, monkeypatch, *DUAS)
    declara_previa(registro, "valida_000013.yaml", "13.png")
    png_em(registro / "13.png")

    at = abre_a_interface()

    assert not at.exception
    assert len(at.get("image")) == 1


def test_AC_020_3_acionar_cartao_marca_so_ele_como_selecionada_e_e_ele_que_inicia(
    tmp_path, monkeypatch, disparo
):
    registro_com(tmp_path, monkeypatch, *DUAS)
    at = abre_a_interface()
    assert rotulos_dos_cartoes(at) == {
        "camera_000013": "SELECIONADA",
        "camera_000042": "Selecionar",
    }

    at.button(key="camera_000042").click()
    at = at.run()

    assert rotulos_dos_cartoes(at) == {
        "camera_000013": "Selecionar",
        "camera_000042": "SELECIONADA",
    }
    assert tipos_dos_cartoes(at) == {
        "camera_000013": "secondary",
        "camera_000042": "primary",
    }
    botao_iniciar(at).click()
    at = at.run()
    assert [chamada[0] for chamada in disparo.chamadas] == ["000042"]


def test_AC_020_4_aba_nova_seleciona_a_primeira_camera_do_registro(
    tmp_path, monkeypatch
):
    # Copiados em ordem inversa: a ordem dos cartões é a do registro (SUP-065).
    registro_com(tmp_path, monkeypatch, "valida_000042.yaml", "valida_000013.yaml")

    at = abre_a_interface()

    assert [id_ for id_, _ in cartoes(at)] == ["000013", "000042"]
    assert at.session_state["camera"] == "000013"
    assert rotulos_dos_cartoes(at)["camera_000013"] == "SELECIONADA"


@pytest.mark.parametrize("situacao", ["sessao_em_andamento", "resultado"])
def test_AC_020_5_sessao_em_andamento_ou_resultado_trava_os_cartoes(
    tmp_path, monkeypatch, situacao
):
    registro_com(tmp_path, monkeypatch, *DUAS)
    data_dir = tmp_path / "data"
    if situacao == "resultado":
        termina(data_dir, Fase.CONCLUIDA, status="COMPLETA")
        at = abre_a_interface()
    else:
        captura_em_curso(data_dir)
        with trava_do_run(data_dir):
            at = abre_a_interface()

    assert len(botoes_de_cartao(at)) == 2
    assert all(b.disabled for b in botoes_de_cartao(at))
    assert at.session_state["camera"] == "000013"


def test_AC_020_6_registro_sem_camera_valida_nao_mostra_cartao_e_trava_iniciar(
    tmp_path, monkeypatch
):
    registro_com(tmp_path, monkeypatch, "sem_linha.yaml")

    at = abre_a_interface()

    assert not at.exception
    assert cartoes(at) == []
    assert botoes_de_cartao(at) == []
    assert any("Nenhuma câmera disponível" in w.value for w in at.warning)
    assert botao_iniciar(at).disabled is True

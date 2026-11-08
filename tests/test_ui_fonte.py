"""Interface: seletor de fonte e o que cada fonte mostra — upload-videos.

Critérios cobertos, de `.spec/features/upload-videos/spec.md`: AC-026.1,
AC-026.2, AC-026.4 (a fonte ao vivo dispara a captura de AC-011.4) e AC-026.5
(a fonte e a área de envio travadas), mais R-4 (a duração sobrevive à ida e
volta da fonte).

Mesmos dublês dos demais testes de interface: `.env` nunca é lido, o disparo
da sessão é um dublê e nada aqui toca a rede ou grava fora de `tmp_path`.
"""

from tests.test_ui_acompanhamento import (  # noqa: F401  (fixtures usadas por nome)
    captura_em_curso,
    data_dir,
    trava_do_run,
)
from tests.test_ui_formulario import (  # noqa: F401  (fixtures usadas por nome)
    abre_a_interface,
    ambiente,
    botoes_de_cartao,
    disparo,
    registro_com,
)
from tests.test_ui_resultado import concluida  # noqa: F401  (fixture usada por nome)

AVISO = "Envie apenas vídeos gravados pela 000013 · Via de teste - camera 13."


def radio_da_fonte(at):
    achados = [r for r in at.radio if r.key == "fonte"]
    assert len(achados) == 1
    return achados[0]


def muda_a_fonte(at, valor: str):
    radio_da_fonte(at).set_value(valor)
    return at.run()


def rotulos_de_markdown(at) -> str:
    return "\n".join(m.value for m in at.markdown)


def atalhos(at) -> list:
    return [b for b in at.button if (b.key or "").startswith("atalho_")]


def test_AC_026_1_aba_nova_oferece_as_duas_fontes_com_camera_ao_vivo_marcada(
    tmp_path, monkeypatch
):
    registro_com(tmp_path, monkeypatch, "valida_000013.yaml")

    at = abre_a_interface()

    radio = radio_da_fonte(at)
    assert radio.options == [
        "**Câmera ao vivo**\n\nAcessa o feed e processa em tempo real",
        "**Fazer upload de vídeos**\n\nProcessa arquivos enviados manualmente",
    ]
    assert "01 · Fonte" in rotulos_de_markdown(at)
    assert radio.value == "camera"
    assert radio.index == 0
    assert radio.disabled is False


def test_AC_026_2_upload_esconde_duracao_atalhos_e_manter_clipes(
    tmp_path, monkeypatch
):
    registro_com(tmp_path, monkeypatch, "valida_000013.yaml")

    at = muda_a_fonte(abre_a_interface(), "upload")

    assert not at.exception
    assert len(at.number_input) == 0
    assert atalhos(at) == []
    assert not [c for c in at.checkbox if c.label == "Manter clipes de vídeo"]
    texto = rotulos_de_markdown(at)
    assert "Duração" not in texto
    assert "Saída" not in texto
    assert "Manter clipes de vídeo" not in texto
    assert not [b for b in at.button if b.label == "Iniciar sessão"]


def test_AC_026_2_upload_mostra_area_de_envio_e_cartoes(tmp_path, monkeypatch):
    registro_com(tmp_path, monkeypatch, "valida_000013.yaml", "valida_000042.yaml")

    ao_vivo = abre_a_interface()
    assert len(ao_vivo.file_uploader) == 0

    at = muda_a_fonte(ao_vivo, "upload")

    (envio,) = at.file_uploader
    assert envio.accept_multiple_files is True
    # sem `type=`: a recusa por extensão é a mensagem do app (AC-027.2, D-3)
    assert envio.allowed_type == []
    assert len(botoes_de_cartao(at)) == 2


def test_AC_026_2_upload_mostra_o_aviso_com_id_e_nome_da_camera_selecionada(
    tmp_path, monkeypatch
):
    registro_com(tmp_path, monkeypatch, "valida_000013.yaml")

    ao_vivo = abre_a_interface()
    assert AVISO not in [i.value for i in ao_vivo.info]

    at = muda_a_fonte(ao_vivo, "upload")

    assert AVISO in [i.value for i in at.info]


def test_AC_026_4_camera_ao_vivo_inicia_a_sessao_de_captura(
    tmp_path, monkeypatch, disparo
):
    registro_com(tmp_path, monkeypatch, "valida_000013.yaml")

    at = abre_a_interface()
    at.number_input[0].set_value(7)
    at = at.run()
    next(b for b in at.button if b.label == "Iniciar sessão").click()
    at.run()

    assert len(disparo.chamadas) == 1
    (id_camera, minutos, _data_dir, _config_dir, manter_videos) = disparo.chamadas[0]
    assert (id_camera, minutos, manter_videos) == ("000013", 7, False)


def test_AC_026_5_sessao_em_andamento_trava_a_fonte_e_a_area_de_envio(data_dir):
    at = muda_a_fonte(abre_a_interface(), "upload")
    assert radio_da_fonte(at).disabled is False
    assert at.file_uploader[0].disabled is False

    captura_em_curso(data_dir)
    with trava_do_run(data_dir):
        at = at.run()

    assert radio_da_fonte(at).disabled is True
    assert radio_da_fonte(at).value == "upload"
    assert at.file_uploader[0].disabled is True


def test_AC_026_5_resultado_na_tela_trava_a_fonte_e_a_area_de_envio(data_dir):
    at = muda_a_fonte(abre_a_interface(), "upload")

    concluida(data_dir)
    at = at.run()

    assert radio_da_fonte(at).disabled is True
    assert radio_da_fonte(at).value == "upload"
    assert at.file_uploader[0].disabled is True


def test_R_4_duracao_volta_com_o_valor_de_antes(tmp_path, monkeypatch):
    registro_com(tmp_path, monkeypatch, "valida_000013.yaml")

    at = abre_a_interface()
    at.number_input[0].set_value(5)
    at = at.run()
    assert at.number_input[0].value == 5

    at = muda_a_fonte(at, "upload")
    assert len(at.number_input) == 0

    at = muda_a_fonte(at, "camera")

    assert at.number_input[0].value == 5

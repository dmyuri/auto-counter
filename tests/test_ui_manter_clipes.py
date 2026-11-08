"""Interface: opção "Manter clipes de vídeo" no painel de Configuração —
download-clipes.

Critérios cobertos, de `.spec/features/download-clipes/spec.md`: AC-024.1 a
AC-024.4 (a opção na tela, SUP-080, D-8).

A trava e o `sessao_atual.json` são montados à mão em `tmp_path`, como nos
demais testes da interface. Nada aqui inicia sessão de verdade, abre
navegador ou toca a rede.
"""

from tests.test_ui_acompanhamento import (  # noqa: F401  (fixtures usadas por nome)
    captura_em_curso,
    data_dir,
    trava_do_run,
)
from tests.test_ui_formulario import (  # noqa: F401  (fixtures usadas por nome)
    abre_a_interface,
    ambiente,
    disparo,
    registro_com,
)
from tests.test_ui_resultado import concluida  # noqa: F401  (fixture usada por nome)


def checkbox_manter_clipes(at):
    achados = [c for c in at.checkbox if c.label == "Manter clipes de vídeo"]
    assert len(achados) == 1
    return achados[0]


def textos(at) -> str:
    partes = [m.value for m in at.markdown]
    partes += [e.value for e in at.caption]
    return "\n".join(partes)


def test_AC_024_1_aba_nova_mostra_a_opcao_desligada_com_o_texto(tmp_path, monkeypatch):
    registro_com(tmp_path, monkeypatch, "valida_000013.yaml")

    at = abre_a_interface()

    checkbox = checkbox_manter_clipes(at)
    assert checkbox.value is False
    assert (
        "Salva os trechos processados para download ao final. A planilha "
        ".xlsx é sempre gerada." in textos(at)
    )


def test_AC_024_2_ligada_ao_iniciar_dispara_com_manter_videos_true(
    tmp_path, monkeypatch, disparo
):
    registro_com(tmp_path, monkeypatch, "valida_000013.yaml")

    at = abre_a_interface()
    checkbox_manter_clipes(at).set_value(True)
    at = at.run()
    botao = next(b for b in at.button if b.label == "Iniciar sessão")
    botao.click()
    at.run()

    (id_camera, minutos, data_dir_, config_dir_, manter_videos) = disparo.chamadas[0]
    assert manter_videos is True


def test_AC_024_3_desligada_ao_iniciar_dispara_com_manter_videos_false(
    tmp_path, monkeypatch, disparo
):
    registro_com(tmp_path, monkeypatch, "valida_000013.yaml")

    at = abre_a_interface()
    botao = next(b for b in at.button if b.label == "Iniciar sessão")
    botao.click()
    at.run()

    (id_camera, minutos, data_dir_, config_dir_, manter_videos) = disparo.chamadas[0]
    assert manter_videos is False


def test_AC_024_4_sessao_em_andamento_trava_a_opcao(data_dir):
    captura_em_curso(data_dir)

    with trava_do_run(data_dir):
        at = abre_a_interface()

    assert checkbox_manter_clipes(at).disabled is True


def test_AC_024_4_sessao_do_terminal_trava_a_opcao(tmp_path, monkeypatch):
    from datetime import datetime, timezone

    from auto_counter.pipeline.lock import adquirir_trava

    registro_com(tmp_path, monkeypatch, "valida_000013.yaml")
    with adquirir_trava(
        tmp_path / "data",
        comando="capture",
        id_camera="000042",
        nome_camera="Outro local",
        agora=lambda: datetime(2026, 9, 7, 11, 0, tzinfo=timezone.utc),
    ):
        at = abre_a_interface()

    assert checkbox_manter_clipes(at).disabled is True


def test_AC_024_4_resultado_na_tela_trava_a_opcao(data_dir):
    concluida(data_dir)

    at = abre_a_interface()

    assert checkbox_manter_clipes(at).disabled is True


def test_AC_023_6_nova_sessao_devolve_a_opcao_com_o_valor_anterior(data_dir):
    at = abre_a_interface()
    checkbox_manter_clipes(at).set_value(True)
    at = at.run()

    concluida(data_dir)
    at = at.run()
    assert checkbox_manter_clipes(at).value is True
    assert checkbox_manter_clipes(at).disabled is True

    botao = next(b for b in at.button if b.label == "Nova sessão")
    botao.click()
    at = at.run()

    checkbox = checkbox_manter_clipes(at)
    assert checkbox.disabled is False
    assert checkbox.value is True

"""Interface: cabeçalho, tema, painéis e estado da tela — T-08 de `layout-interface`.

Critérios cobertos, de `.spec/features/layout-interface/spec.md`:

- AC-019.1 a AC-019.4 — o indicador do cabeçalho;
- AC-019.5 e AC-019.6 — o tema escuro por padrão e a troca de tema (SUP-062,
  SUP-064);
- AC-023.5 a AC-023.7 — depois do resultado, só "Nova sessão" libera a
  configuração, e só na aba em que foi acionado (SUP-074).

O tema é verificado pelo conjunto de variáveis CSS injetado, e não pela cor
renderizada (SUP-062). Os valores esperados são os da tabela de D-12, copiados
do protótipo, e não vêm do código da interface.

A trava e o `sessao_atual.json` são montados à mão em `tmp_path`, como nos testes
de acompanhamento. Nada aqui inicia sessão, abre navegador ou toca a rede.
"""

import re
from datetime import timedelta

import pytest

from auto_counter.pipeline.lock import adquirir_trava
from auto_counter.pipeline.progress import ler_progresso
from auto_counter.pipeline.state import AnotadorDoEstado, Fase
from auto_counter.pipeline.stop import NOME_DO_PEDIDO
from tests.test_ui_acompanhamento import (  # noqa: F401  (fixtures usadas por nome)
    INICIO,
    botoes,
    captura_em_curso,
    clica,
    downloads,
    em_processamento,
    termina,
    textos,
    trava_do_run,
)
from tests.test_ui_formulario import (  # noqa: F401  (fixtures usadas por nome)
    abre_a_interface,
    ambiente,
    registro_com,
)

VARIAVEIS_ESCURO = {
    "--bg": "#0c0e0d",
    "--panel": "#141715",
    "--panel2": "#1a1e1b",
    "--line": "#262b28",
    "--ink": "#eef1ee",
    "--muted": "#8d958f",
    "--accent": "oklch(0.83 0.19 150)",
    "--accentInk": "#05130a",
    "--accentSoft": "oklch(0.83 0.19 150 / 0.12)",
    "--danger": "oklch(0.7 0.18 25)",
    "--stripe": "#1d211e",
}
VARIAVEIS_CLARO = {
    "--bg": "#f3f4f2",
    "--panel": "#ffffff",
    "--panel2": "#f7f8f6",
    "--line": "#dde1dc",
    "--ink": "#111412",
    "--muted": "#596159",
    "--accent": "oklch(0.52 0.15 150)",
    "--accentInk": "#ffffff",
    "--accentSoft": "oklch(0.52 0.15 150 / 0.1)",
    "--danger": "oklch(0.55 0.19 25)",
    "--stripe": "#eceee9",
}

FASES_TERMINAIS = [
    Fase.CONCLUIDA,
    Fase.SEM_PLANILHA,
    Fase.PROCESSAMENTO_CANCELADO,
    Fase.FALHOU,
]


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    registro_com(tmp_path, monkeypatch, "valida_000013.yaml", "valida_000042.yaml")
    return tmp_path / "data"


def indicador(at) -> str:
    """O texto do indicador do cabeçalho."""
    achados = [
        re.search(r'<span class="indicador">(.*?)</span>', m.value)
        for m in at.markdown
    ]
    textos_do_indicador = [a.group(1) for a in achados if a]
    assert len(textos_do_indicador) == 1
    return textos_do_indicador[0]


def variaveis_do_tema(at) -> dict[str, str]:
    """As variáveis de `:root` do único bloco de estilo injetado."""
    blocos = [m.value for m in at.markdown if m.value.lstrip().startswith("<style>")]
    assert len(blocos) == 1
    raiz = re.search(r":root\s*\{([^}]*)\}", blocos[0])
    assert raiz is not None
    return {
        nome: valor.strip()
        for nome, valor in re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", raiz.group(1))
    }


def botao_de_tema(at) -> str:
    rotulos = [b.label for b in at.button if b.label in ("Tema claro", "Tema escuro")]
    assert len(rotulos) == 1
    return rotulos[0]


def camera_exibida(at):
    return at.selectbox[0].value


def duracao_exibida(at):
    return at.number_input[0].value


def instantaneo(pasta) -> dict:
    return {
        str(caminho.relative_to(pasta)): (
            caminho.stat().st_size,
            caminho.stat().st_mtime_ns,
            caminho.read_bytes(),
        )
        for caminho in sorted(pasta.rglob("*"))
        if caminho.is_file()
    }


def test_AC_019_1_sem_sessao_e_sem_resultado_mostra_aguardando(data_dir):
    at = abre_a_interface()

    assert not at.exception
    assert indicador(at) == "Aguardando"


def test_AC_019_2_sessao_da_interface_mostra_capturando_e_processando(data_dir):
    captura_em_curso(data_dir)
    with trava_do_run(data_dir):
        na_captura = abre_a_interface()
    assert indicador(na_captura) == "Capturando"

    em_processamento(data_dir)
    with trava_do_run(data_dir):
        no_processamento = abre_a_interface()
    assert indicador(no_processamento) == "Processando"


def test_AC_019_2_troca_de_fase_atualiza_o_cabecalho_sem_acao_do_usuario(
    data_dir, monkeypatch
):
    """O fragmento percebe a troca de fase e pede a página inteira de novo (D-10).

    A primeira leitura (a do cabeçalho) ainda vê a captura, e as seguintes já
    veem o processamento: é o que acontece quando a fase troca entre o desenho
    da página e a atualização do fragmento.
    """
    captura_em_curso(data_dir)
    with trava_do_run(data_dir):
        na_captura = ler_progresso(data_dir)
    em_processamento(data_dir)
    with trava_do_run(data_dir):
        no_processamento = ler_progresso(data_dir)

    leituras = iter([na_captura])

    def leitura_da_troca(_data_dir, **_opcoes):
        return next(leituras, no_processamento)

    monkeypatch.setattr(
        "auto_counter.pipeline.progress.ler_progresso", leitura_da_troca
    )

    at = abre_a_interface()

    assert not at.exception
    assert indicador(at) == "Processando"


def test_AC_019_3_sessao_do_terminal_mostra_em_andamento(data_dir):
    with adquirir_trava(
        data_dir,
        comando="capture",
        id_camera="000042",
        nome_camera="Outro local",
        agora=lambda: INICIO,
    ):
        at = abre_a_interface()

    assert indicador(at) == "Em andamento"


@pytest.mark.parametrize("fase", FASES_TERMINAIS)
def test_AC_019_4_resultado_exibido_mostra_finalizado(data_dir, fase):
    termina(data_dir, fase, status="COMPLETA", mensagem="desfecho")

    at = abre_a_interface()

    assert not at.exception
    assert indicador(at) == "Finalizado"


def test_AC_019_5_aba_nova_aplica_tema_escuro_e_oferece_tema_claro(data_dir):
    at = abre_a_interface()

    variaveis = variaveis_do_tema(at)

    for nome, valor in VARIAVEIS_ESCURO.items():
        assert variaveis.get(nome) == valor, nome
    assert botao_de_tema(at) == "Tema claro"


def test_AC_019_6_botao_de_tema_alterna_e_nao_mexe_na_sessao(data_dir):
    captura_em_curso(data_dir)
    with trava_do_run(data_dir):
        at = abre_a_interface()
        camera, duracao = camera_exibida(at), duracao_exibida(at)

        at = clica(at, "Tema claro")
        assert not at.exception
        claras = variaveis_do_tema(at)
        assert all(claras.get(n) == v for n, v in VARIAVEIS_CLARO.items())
        assert botao_de_tema(at) == "Tema escuro"
        assert indicador(at) == "Capturando"

        at = clica(at, "Tema escuro")
        escuras = variaveis_do_tema(at)
        assert all(escuras.get(n) == v for n, v in VARIAVEIS_ESCURO.items())
        assert botao_de_tema(at) == "Tema claro"

    assert (camera_exibida(at), duracao_exibida(at)) == (camera, duracao)
    assert not (data_dir / NOME_DO_PEDIDO).exists()


def test_AC_023_5_resultado_exibido_esconde_iniciar_trava_configuracao_e_mostra_nova_sessao(
    data_dir,
):
    termina(data_dir, Fase.CONCLUIDA, status="COMPLETA")

    at = abre_a_interface()

    assert "Iniciar sessão" not in botoes(at)
    assert "Nova sessão" in botoes(at)
    assert at.selectbox[0].disabled is True
    assert at.number_input[0].disabled is True


def test_AC_023_6_nova_sessao_some_com_o_resultado_e_volta_a_configuracao(data_dir):
    at = abre_a_interface()
    at.selectbox[0].select("Via de teste - camera 42")
    at.number_input[0].set_value(7)
    at = at.run()
    escolhidas = (camera_exibida(at), duracao_exibida(at))

    data_dir.mkdir(parents=True, exist_ok=True)
    planilha = data_dir / "x.xlsx"
    planilha.write_bytes(b"xlsx")
    termina(
        data_dir, Fase.CONCLUIDA, status="COMPLETA", planilha=str(planilha)
    )
    at = at.run()
    assert indicador(at) == "Finalizado"
    assert len(downloads(at)) == 1
    antes = instantaneo(data_dir)

    at = clica(at, "Nova sessão")

    assert not at.exception
    assert indicador(at) == "Aguardando"
    assert downloads(at) == []
    assert "status COMPLETA" not in textos(at)
    assert "Nova sessão" not in botoes(at)
    assert "Iniciar sessão" in botoes(at)
    assert at.selectbox[0].disabled is False
    assert at.number_input[0].disabled is False
    assert (camera_exibida(at), duracao_exibida(at)) == escolhidas
    assert escolhidas[1] == 7
    # O registro da sessão e a planilha não mudam: bytes e mtime iguais.
    assert instantaneo(data_dir) == antes


def test_AC_023_7_aba_nova_volta_a_mostrar_o_ultimo_resultado(data_dir):
    termina(data_dir, Fase.CONCLUIDA, status="COMPLETA")
    aba = abre_a_interface()
    aba = clica(aba, "Nova sessão")
    assert indicador(aba) == "Aguardando"

    outra_aba = abre_a_interface()

    assert indicador(outra_aba) == "Finalizado"
    assert "Nova sessão" in botoes(outra_aba)
    assert "status COMPLETA" in textos(outra_aba)


def test_AC_023_6_resultado_dispensado_nao_esconde_o_da_sessao_seguinte(data_dir):
    termina(data_dir, Fase.CONCLUIDA, status="COMPLETA")
    at = abre_a_interface()
    at = clica(at, "Nova sessão")
    assert indicador(at) == "Aguardando"

    seguinte = AnotadorDoEstado(
        data_dir,
        pid=4242,
        id_camera="000013",
        nome_camera="Praça Exemplo",
        duracao_pedida=5,
        iniciada_em=INICIO + timedelta(hours=1),
    )
    seguinte.iniciar()
    seguinte.terminar(Fase.CONCLUIDA, id_sessao="outra", status="COMPLETA")
    at = at.run()

    assert indicador(at) == "Finalizado"
    assert "Nova sessão" in botoes(at)


def test_a_interface_nao_grava_nada_em_disco_ao_trocar_tema_ou_dispensar(data_dir):
    captura_em_curso(data_dir)
    with trava_do_run(data_dir):
        at = abre_a_interface()
        antes = {p.name for p in data_dir.rglob("*")}
        at = clica(at, "Tema claro")
        at = clica(at, "Tema escuro")
        assert {p.name for p in data_dir.rglob("*")} == antes

    termina(data_dir, Fase.CONCLUIDA, status="COMPLETA")
    at = abre_a_interface()
    antes = instantaneo(data_dir)

    clica(at, "Tema claro")
    clica(abre_a_interface(), "Nova sessão")

    assert instantaneo(data_dir) == antes

"""Interface: escolha de câmera e duração — T-15.

Critérios cobertos, de `.spec/features/interface-sessao/spec.md`:

- AC-011.1 — a interface lista exatamente as câmeras válidas, pelo nome do
  local, e não tem campo para digitar id, URL ou endereço;
- AC-011.2 — a duração é inteira, de 1 a 15 minutos, com padrão 15 (SUP-043);
- AC-011.3 — sem câmera válida, a interface avisa e o botão fica indisponível;
- AC-013.1 — com sessão em andamento, iniciar fica indisponível e a mensagem diz
  qual câmera e quando.

E SUP-038: a interface é só casca e importa apenas `streamlit`, a biblioteca
padrão, `dotenv` e o `pipeline`.

Usa `streamlit.testing.v1.AppTest` sobre o script real. O `.env` nunca é lido
(`load_dotenv` é trocado), o disparo da sessão é um dublê, e nada aqui abre
navegador, toca a rede ou grava fora de `tmp_path`.
"""

import ast
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from auto_counter.pipeline import launch
from auto_counter.pipeline.lock import adquirir_trava

APP = Path(__file__).parent.parent / "src" / "auto_counter" / "ui" / "app.py"
FIXTURES = Path(__file__).parent / "fixtures" / "cameras"
INICIO = datetime(2026, 9, 7, 11, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def ambiente(monkeypatch, tmp_path):
    """Sem `.env`, com os dados em `tmp_path` e o disparo trocado por um dublê."""
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: False)
    monkeypatch.setenv("AUTO_COUNTER_DATA_DIR", str(tmp_path / "data"))


def registro_com(tmp_path, monkeypatch, *arquivos: str) -> Path:
    destino = tmp_path / "cameras"
    destino.mkdir(exist_ok=True)
    for arquivo in arquivos:
        shutil.copy(FIXTURES / arquivo, destino / arquivo)
    monkeypatch.setattr(sys, "argv", ["app.py", "--config-dir", str(destino)])
    return destino


def abre_a_interface() -> AppTest:
    return AppTest.from_file(str(APP), default_timeout=30).run()


class DisparoDuble:
    def __init__(self, problema=None):
        self.chamadas = []
        self.problema = problema

    def iniciar(self, id_camera, minutos, *, data_dir, config_dir, manter_videos=False):
        self.chamadas.append(
            (id_camera, minutos, data_dir, config_dir, manter_videos)
        )
        return object()

    def aguardar(self, disparada, **opcoes):
        return self.problema


@pytest.fixture
def disparo(monkeypatch) -> DisparoDuble:
    duble = DisparoDuble()
    monkeypatch.setattr(launch, "iniciar_sessao", duble.iniciar)
    monkeypatch.setattr(launch, "aguardar_inicio", duble.aguardar)
    return duble


def botao_iniciar(at: AppTest):
    botoes = [b for b in at.button if b.label == "Iniciar sessão"]
    assert len(botoes) == 1
    return botoes[0]


def botoes_de_cartao(at: AppTest) -> list:
    """Os botões dos cartões de câmera (`layout-interface`, AC-020.1)."""
    return [b for b in at.button if (b.key or "").startswith("camera_")]


def cartoes(at: AppTest) -> list[tuple[str, str]]:
    """(id, nome do local) de cada cartão, na ordem em que aparecem."""
    achados = [re.fullmatch(r"`(\w+)` \*\*(.+)\*\*", m.value) for m in at.markdown]
    return [(a.group(1), a.group(2)) for a in achados if a]


def test_AC_011_1_a_interface_lista_exatamente_as_cameras_validas_pelo_nome(
    tmp_path, monkeypatch
):
    registro_com(tmp_path, monkeypatch, "valida_000013.yaml", "valida_000042.yaml")

    at = abre_a_interface()

    assert not at.exception
    assert [nome for _, nome in cartoes(at)] == [
        "Via de teste - camera 13",
        "Via de teste - camera 42",
    ]


def test_AC_011_1_camera_rejeitada_nao_aparece_na_lista(tmp_path, monkeypatch):
    registro_com(tmp_path, monkeypatch, "valida_000013.yaml", "sem_linha.yaml")

    at = abre_a_interface()

    assert [nome for _, nome in cartoes(at)] == ["Via de teste - camera 13"]


def test_AC_011_1_a_interface_nao_tem_campo_de_texto(tmp_path, monkeypatch):
    registro_com(tmp_path, monkeypatch, "valida_000013.yaml", "valida_000042.yaml")

    at = abre_a_interface()

    assert len(at.text_input) == 0
    assert len(at.text_area) == 0


def test_AC_011_2_duracao_e_inteira_de_1_a_15_com_padrao_15(tmp_path, monkeypatch):
    registro_com(tmp_path, monkeypatch, "valida_000013.yaml")

    at = abre_a_interface()

    duracao = at.number_input[0]
    assert (duracao.min, duracao.max, duracao.step) == (1, 15, 1)
    assert duracao.value == 15
    assert isinstance(duracao.value, int)


def test_AC_011_3_registro_sem_camera_valida_avisa_e_desabilita_iniciar(
    tmp_path, monkeypatch
):
    registro_com(tmp_path, monkeypatch, "sem_linha.yaml")

    at = abre_a_interface()

    assert any("Nenhuma câmera disponível" in w.value for w in at.warning)
    assert botoes_de_cartao(at) == []
    assert botao_iniciar(at).disabled is True


def test_AC_011_3_registro_com_id_duplicado_tambem_desabilita_iniciar(
    tmp_path, monkeypatch
):
    registro_com(tmp_path, monkeypatch, "valida_000013.yaml", "duplicada_000013.yaml")

    at = abre_a_interface()

    assert any("Nenhuma câmera disponível" in w.value for w in at.warning)
    assert any("id duplicado" in c.value for c in at.caption)
    assert botao_iniciar(at).disabled is True


def test_AC_011_3_diretorio_de_registro_inexistente_desabilita_iniciar(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        sys, "argv", ["app.py", "--config-dir", str(tmp_path / "nao_existe")]
    )

    at = abre_a_interface()

    assert not at.exception
    assert botao_iniciar(at).disabled is True


def test_AC_013_1_com_sessao_em_andamento_iniciar_fica_indisponivel_com_camera_e_inicio(
    tmp_path, monkeypatch
):
    registro_com(tmp_path, monkeypatch, "valida_000013.yaml")

    with adquirir_trava(
        tmp_path / "data",
        comando="capture",
        id_camera="000042",
        nome_camera="Outro local",
        agora=lambda: INICIO,
    ):
        at = abre_a_interface()

    assert botao_iniciar(at).disabled is True
    mensagens = " ".join(i.value for i in at.info)
    assert "Outro local" in mensagens
    assert "07/09/2026 08:00" in mensagens


def test_iniciar_dispara_com_a_camera_e_a_duracao_escolhidas(
    tmp_path, monkeypatch, disparo
):
    destino = registro_com(
        tmp_path, monkeypatch, "valida_000013.yaml", "valida_000042.yaml"
    )

    at = abre_a_interface()
    at.button(key="camera_000042").click()
    at.number_input[0].set_value(7)
    at = at.run()
    botao_iniciar(at).click()
    at = at.run()

    assert not at.exception
    assert disparo.chamadas == [
        ("000042", 7, tmp_path / "data", destino, False)
    ]


def test_sessao_que_nao_inicia_mostra_o_motivo_sem_traceback(
    tmp_path, monkeypatch, disparo
):
    registro_com(tmp_path, monkeypatch, "valida_000013.yaml")
    disparo.problema = "erro: o modelo não foi encontrado"

    at = abre_a_interface()
    botao_iniciar(at).click()
    at = at.run()

    assert not at.exception
    assert any("o modelo não foi encontrado" in e.value for e in at.error)


def test_a_interface_so_importa_streamlit_stdlib_dotenv_e_o_pipeline():
    arvore = ast.parse(APP.read_text(encoding="utf-8"))
    importados = set()
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            importados.update(alias.name for alias in no.names)
        elif isinstance(no, ast.ImportFrom):
            importados.add(no.module or "")

    permitidos_externos = {"streamlit", "dotenv"}
    for modulo in importados:
        raiz = modulo.split(".")[0]
        if raiz == "auto_counter":
            assert modulo.startswith("auto_counter.pipeline"), modulo
        elif raiz not in permitidos_externos:
            assert raiz in sys.stdlib_module_names, f"{modulo} não é permitido"

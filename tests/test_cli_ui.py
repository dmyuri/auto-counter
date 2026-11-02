"""Comando `auto-counter ui` — T-17.

Critério coberto, de `.spec/features/interface-sessao/spec.md`: SUP-041 — a
interface roda apenas em localhost e sem autenticação.

O servidor nunca sobe de verdade: `_executar_ui` é trocado por um dublê que
guarda o comando. Nada aqui abre navegador nem toca a rede.
"""

import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from auto_counter.cli import app


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def comandos(monkeypatch) -> list[list[str]]:
    guardados: list[list[str]] = []

    def executar(comando: list[str]) -> int:
        guardados.append(comando)
        return 0

    monkeypatch.setattr("auto_counter.cli._executar_ui", executar)
    return guardados


def valor_de(comando: list[str], opcao: str) -> str:
    return comando[comando.index(opcao) + 1]


def test_SUP_041_a_interface_escuta_apenas_em_localhost(runner, comandos):
    resultado = runner.invoke(app, ["ui"])

    assert resultado.exit_code == 0, resultado.output
    (comando,) = comandos
    assert valor_de(comando, "--server.address") == "127.0.0.1"
    assert "0.0.0.0" not in comando
    assert valor_de(comando, "--browser.gatherUsageStats") == "false"
    assert valor_de(comando, "--server.port") == "8501"


def test_ui_aponta_para_o_script_da_interface_que_existe(runner, comandos):
    runner.invoke(app, ["ui"])

    (comando,) = comandos
    assert comando[:5] == [sys.executable, "-m", "streamlit", "run", comando[4]]
    script = Path(comando[4])
    assert script.name == "app.py"
    assert script.parent.name == "ui"
    assert script.is_file()


def test_ui_repassa_o_diretorio_de_configuracao_ao_script(runner, comandos, tmp_path):
    runner.invoke(app, ["ui", "--config-dir", str(tmp_path)])

    (comando,) = comandos
    depois_do_separador = comando[comando.index("--") + 1 :]
    assert depois_do_separador == ["--config-dir", str(tmp_path.resolve())]


def test_ui_repassa_a_porta(runner, comandos):
    runner.invoke(app, ["ui", "--port", "8600"])

    (comando,) = comandos
    assert valor_de(comando, "--server.port") == "8600"


def test_ui_devolve_o_codigo_de_saida_do_servidor(runner, monkeypatch):
    monkeypatch.setattr("auto_counter.cli._executar_ui", lambda comando: 3)

    resultado = runner.invoke(app, ["ui"])

    assert resultado.exit_code == 3


def test_ui_nao_deixa_traceback_quando_nao_consegue_iniciar(runner, monkeypatch):
    def falha(comando):
        raise FileNotFoundError("python não encontrado")

    monkeypatch.setattr("auto_counter.cli._executar_ui", falha)

    resultado = runner.invoke(app, ["ui"])

    assert resultado.exit_code == 1
    assert "não foi possível iniciar a interface" in resultado.output
    assert "Traceback" not in resultado.output


def test_ui_nao_importa_streamlit_na_cli():
    resultado = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, auto_counter.cli; print('streamlit' in sys.modules)",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert resultado.returncode == 0, resultado.stderr
    assert resultado.stdout.strip() == "False"

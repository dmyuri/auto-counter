"""Comando `auto-counter session export` — T-11.

Comportamento em `.spec/features/exportacao-xlsx/spec.md`: AC-010.1, AC-010.5 e
AC-010.7, pela superfície de CLI (D-3 do `_tasks.md`).

Nenhum teste toca a rede nem a câmera: as sessões são gravadas direto no banco
(`tests.export_helpers`), porque o comando só lê o que já está lá.
"""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from auto_counter.capture.status import StatusDaSessao
from auto_counter.cli import app
from auto_counter.storage.connection import NOME_DO_ARQUIVO_DO_BANCO, conectar
from tests.export_helpers import ID_SESSAO, evento, gravar_sessao


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def data_dir(monkeypatch, tmp_path) -> Path:
    caminho = tmp_path / "data"
    monkeypatch.setenv("AUTO_COUNTER_DATA_DIR", str(caminho))
    return caminho


def _exportar(runner, id_sessao=ID_SESSAO):
    return runner.invoke(app, ["session", "export", id_sessao])


def test_AC_010_1_session_export_grava_o_xlsx_e_imprime_o_caminho(runner, data_dir):
    with conectar(data_dir) as conexao:
        gravar_sessao(
            conexao, duracao_pedida=15, eventos=(evento(minuto=1, id_de_rastreio="1:1"),)
        )

    resultado = _exportar(runner)

    esperado = data_dir / "000013_20260907_0800_15min.xlsx"
    assert resultado.exit_code == 0
    assert esperado.is_file()
    assert str(esperado) in resultado.output


def test_AC_010_5_session_export_de_sessao_invalida_gera_o_arquivo_com_status_no_nome(
    runner, data_dir
):
    with conectar(data_dir) as conexao:
        gravar_sessao(
            conexao,
            duracao_pedida=15,
            status=StatusDaSessao.INVALIDA,
            minutos_perdidos=(1, 2, 3, 4),
        )

    resultado = _exportar(runner)

    assert resultado.exit_code == 0
    assert (data_dir / "000013_20260907_0800_15min_INVALIDA.xlsx").is_file()
    assert "ATENÇÃO: sessão INVALIDA" in resultado.output


def test_AC_010_7_session_export_funciona_com_os_videos_ja_apagados(runner, data_dir):
    with conectar(data_dir) as conexao:
        gravar_sessao(conexao)

    resultado = _exportar(runner)

    assert resultado.exit_code == 0
    assert not (data_dir / "sessions").exists()


def test_session_export_sem_banco_sai_com_erro_e_nao_cria_banco(runner, data_dir):
    resultado = _exportar(runner)

    assert resultado.exit_code == 1
    assert "nenhuma sessão foi gravada" in resultado.output
    assert not (data_dir / NOME_DO_ARQUIVO_DO_BANCO).exists()


def test_session_export_de_sessao_inexistente_sai_com_codigo_1(runner, data_dir):
    with conectar(data_dir) as conexao:
        gravar_sessao(conexao)

    resultado = _exportar(runner, "nao-existe")

    assert resultado.exit_code == 1
    assert "nao-existe" in resultado.output
    assert "Traceback" not in resultado.output


def test_session_export_de_sessao_em_andamento_sai_com_codigo_1(runner, data_dir):
    with conectar(data_dir) as conexao:
        gravar_sessao(conexao, status=None)

    resultado = _exportar(runner)

    assert resultado.exit_code == 1
    assert "em andamento" in resultado.output
    assert list(data_dir.glob("*.xlsx")) == []


def test_session_export_de_sessao_nao_processada_sai_com_codigo_1(runner, data_dir):
    with conectar(data_dir) as conexao:
        gravar_sessao(conexao, processada=False)

    resultado = _exportar(runner)

    assert resultado.exit_code == 1
    assert "session process" in resultado.output
    assert list(data_dir.glob("*.xlsx")) == []

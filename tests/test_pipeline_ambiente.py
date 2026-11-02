"""Diretório de dados fora da CLI — T-03.

Critério coberto, de `.spec/features/interface-sessao/spec.md`: SUP-038 — a
interface resolve o diretório de dados pela mesma regra da linha de comando,
sem importar a CLI.
"""

import ast
from pathlib import Path

import pytest

from auto_counter import cli
from auto_counter.pipeline import ambiente
from auto_counter.pipeline.ambiente import (
    DATA_DIR_PADRAO,
    VARIAVEL_DATA_DIR,
    data_dir_do_ambiente,
)


def test_data_dir_vem_da_variavel_de_ambiente(monkeypatch, tmp_path):
    monkeypatch.setenv(VARIAVEL_DATA_DIR, f"  {tmp_path}  ")

    assert data_dir_do_ambiente() == tmp_path


@pytest.mark.parametrize("valor", [None, "", "   "])
def test_data_dir_vazio_ou_ausente_usa_o_padrao_local(monkeypatch, valor):
    if valor is None:
        monkeypatch.delenv(VARIAVEL_DATA_DIR, raising=False)
    else:
        monkeypatch.setenv(VARIAVEL_DATA_DIR, valor)

    assert data_dir_do_ambiente() == DATA_DIR_PADRAO == Path("data")


def test_a_cli_e_o_pipeline_resolvem_o_mesmo_data_dir(monkeypatch, tmp_path):
    assert cli.VARIAVEL_DATA_DIR == VARIAVEL_DATA_DIR
    assert cli.DATA_DIR_PADRAO == DATA_DIR_PADRAO

    monkeypatch.setenv(VARIAVEL_DATA_DIR, str(tmp_path))
    assert cli._data_dir() == data_dir_do_ambiente()

    monkeypatch.delenv(VARIAVEL_DATA_DIR)
    assert cli._data_dir() == data_dir_do_ambiente()


def test_o_pipeline_nao_importa_a_cli():
    pasta = Path(ambiente.__file__).parent
    for arquivo in pasta.glob("*.py"):
        arvore = ast.parse(arquivo.read_text(encoding="utf-8"))
        for no in ast.walk(arvore):
            nomes = []
            if isinstance(no, ast.Import):
                nomes = [alias.name for alias in no.names]
            elif isinstance(no, ast.ImportFrom):
                nomes = [no.module or ""]
            assert not any(
                nome == "auto_counter.cli" or nome.startswith("auto_counter.cli.")
                for nome in nomes
            ), f"{arquivo.name} importa a CLI"

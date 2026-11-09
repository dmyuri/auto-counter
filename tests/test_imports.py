"""Os pontos de entrada importam sozinhos, sem ciclo de import.

Cada módulo é importado num processo novo, porque dentro do pytest a ordem dos
imports de outros testes pode resolver um ciclo por acaso e escondê-lo: foi o
que aconteceu com `export` importando `pipeline.progress`, que quebrava a
interface (`ui/app.py` importa `pipeline.launch` primeiro).

`auto_counter.ui.app` fica de fora: importá-lo executa o script do Streamlit,
que lê o diretório de dados de verdade. `pipeline.launch` é o primeiro import
dele e cobre o mesmo caminho.
"""

import subprocess
import sys

import pytest

PONTOS_DE_ENTRADA = (
    "auto_counter.cli",
    "auto_counter.export",
    "auto_counter.export.format",
    "auto_counter.export.sheet_events",
    "auto_counter.export.sheet_session",
    "auto_counter.pipeline.lock",
    "auto_counter.pipeline.progress",
    "auto_counter.pipeline.launch",
    "auto_counter.pipeline.lista_envio",
)


@pytest.mark.parametrize("modulo", PONTOS_DE_ENTRADA)
def test_modulo_importa_em_processo_limpo(modulo):
    resultado = subprocess.run(
        [sys.executable, "-c", f"import {modulo}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    assert resultado.returncode == 0, resultado.stderr

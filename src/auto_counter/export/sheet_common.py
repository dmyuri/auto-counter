"""Cabeçalho comum das três abas — T-08.

Comportamento em `.spec/features/exportacao-xlsx/spec.md`: AC-010.5. Sessão
DEGRADADA ou INVALIDA leva o aviso na célula A1 de cada aba e o cabeçalho
desce para a linha 2 (D-10 de `_tasks.md`); sessão COMPLETA começa pelo
cabeçalho, na linha 1.
"""

from collections.abc import Sequence

from openpyxl.worksheet.worksheet import Worksheet

from auto_counter.export.format import linha_de_aviso
from auto_counter.storage.model import SessaoGravada


def escrever_cabecalho(
    planilha: Worksheet, sessao: SessaoGravada, cabecalho: Sequence[str]
) -> int:
    """Escreve o aviso (se houver) e o cabeçalho; devolve a linha do cabeçalho."""
    linha = 1
    aviso = linha_de_aviso(sessao)
    if aviso is not None:
        planilha.cell(row=linha, column=1, value=aviso)
        linha += 1

    for coluna, titulo in enumerate(cabecalho, start=1):
        planilha.cell(row=linha, column=coluna, value=titulo)
    return linha

"""Exportação do resultado de uma sessão em XLSX, lida apenas do banco.

Comportamento definido em `.spec/features/exportacao-xlsx/spec.md`.
"""

from auto_counter.export.load import (
    SessaoEmAndamentoError,
    SessaoNaoEncontradaError,
    SessaoNaoProcessadaError,
)
from auto_counter.export.workbook import exportar_sessao

__all__ = [
    "SessaoEmAndamentoError",
    "SessaoNaoEncontradaError",
    "SessaoNaoProcessadaError",
    "exportar_sessao",
]

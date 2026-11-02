"""Aba PorMinuto — T-08.

Comportamento em `.spec/features/exportacao-xlsx/spec.md`: AC-010.3 (uma linha
por minuto, uma coluna por combinação de sentido e categoria mais o total, e
minuto sem dado visivelmente diferente de zero), AC-010.5 (aviso na primeira
linha), SUP-034 (11 colunas) e SUP-035 (SEM_DADO é célula vazia, nunca zero).

A coluna `minuto` é o ordinal da sessão (D-1 de `_tasks.md`). Só o cabeçalho
usa os rótulos de sentido da sessão (D-11); os valores são lidos pelo papel
`sentido_a` / `sentido_b` do agregado.
"""

from openpyxl.worksheet.worksheet import Worksheet

from auto_counter.export.load import DadosDaExportacao
from auto_counter.export.sheet_common import escrever_cabecalho
from auto_counter.storage.model import EstadoDoMinuto

_CATEGORIAS = ("carro", "moto", "onibus", "caminhao")

_COLUNAS_DE_CONTAGEM = tuple(
    f"{papel}_{categoria}"
    for papel in ("sentido_a", "sentido_b")
    for categoria in _CATEGORIAS
)
"""Ordem das oito colunas: sentido A (CARRO, MOTO, ONIBUS, CAMINHAO) e depois
sentido B."""


def _cabecalho(sentido_a: str, sentido_b: str) -> tuple[str, ...]:
    rotulos = {"sentido_a": sentido_a, "sentido_b": sentido_b}
    return (
        "minuto",
        "estado",
        *(
            f"{rotulos[papel]} {categoria.upper()}"
            for papel in ("sentido_a", "sentido_b")
            for categoria in _CATEGORIAS
        ),
        "total",
    )


def escrever_por_minuto(planilha: Worksheet, dados: DadosDaExportacao) -> None:
    """Escreve o aviso (se houver), o cabeçalho e uma linha por minuto."""
    sessao = dados.sessao
    linha = escrever_cabecalho(
        planilha, sessao, _cabecalho(sessao.sentido_a, sessao.sentido_b)
    )

    for agregado in dados.agregados:
        linha += 1
        planilha.cell(row=linha, column=1, value=agregado.minuto)
        planilha.cell(row=linha, column=2, value=agregado.estado.value)
        if agregado.estado is EstadoDoMinuto.SEM_DADO:
            # SUP-035: células de contagem e total vazias, nunca zero.
            continue

        contagens = [getattr(agregado, coluna) for coluna in _COLUNAS_DE_CONTAGEM]
        for coluna, valor in enumerate(contagens, start=3):
            planilha.cell(row=linha, column=coluna, value=valor)
        planilha.cell(row=linha, column=3 + len(contagens), value=sum(contagens))

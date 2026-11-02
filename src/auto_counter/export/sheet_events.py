"""Aba Eventos — T-07.

Comportamento em `.spec/features/exportacao-xlsx/spec.md`: AC-010.2 (uma linha
por cruzamento, com os cinco campos), AC-010.5 (aviso na primeira linha) e
SUP-033 (timestamp como data e hora reais do Excel, em horário de Brasília).
"""

from openpyxl.worksheet.worksheet import Worksheet

from auto_counter.export.format import linha_de_aviso, para_brasilia
from auto_counter.export.load import DadosDaExportacao

FORMATO_DATA_HORA = "dd/mm/yyyy hh:mm:ss"

CABECALHO = (
    "timestamp (horário de Brasília)",
    "categoria",
    "sentido",
    "id de rastreio",
    "confiança",
)


def escrever_eventos(planilha: Worksheet, dados: DadosDaExportacao) -> None:
    """Escreve o aviso (se houver), o cabeçalho e uma linha por evento."""
    linha = 1
    aviso = linha_de_aviso(dados.sessao)
    if aviso is not None:
        planilha.cell(row=linha, column=1, value=aviso)
        linha += 1

    for coluna, titulo in enumerate(CABECALHO, start=1):
        planilha.cell(row=linha, column=coluna, value=titulo)

    for evento in dados.eventos:
        linha += 1
        instante = planilha.cell(
            row=linha, column=1, value=para_brasilia(evento.timestamp)
        )
        instante.number_format = FORMATO_DATA_HORA
        planilha.cell(row=linha, column=2, value=evento.categoria.value)
        planilha.cell(row=linha, column=3, value=evento.sentido)
        planilha.cell(row=linha, column=4, value=evento.id_de_rastreio)
        planilha.cell(row=linha, column=5, value=evento.confianca)

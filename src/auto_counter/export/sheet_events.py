"""Aba Eventos — T-07.

Comportamento em `.spec/features/exportacao-xlsx/spec.md`: AC-010.2 (uma linha
por cruzamento, com os cinco campos), AC-010.5 (aviso na primeira linha) e
SUP-033 (timestamp como data e hora reais do Excel, em horário de Brasília).

Por `processamento-upload` (AC-030.5, D-10), a sessão de upload troca a data e a
hora do cruzamento pelo nome do vídeo e pelo deslocamento em MM:SS desde o
início dele, sem nenhuma coluna de data ou hora.
"""

from openpyxl.worksheet.worksheet import Worksheet

from auto_counter.export.format import para_brasilia
from auto_counter.export.load import DadosDaExportacao
from auto_counter.export.sheet_common import escrever_cabecalho
from auto_counter.storage.model import OrigemDaSessao
from auto_counter.tempo import formatar_tempo

FORMATO_DATA_HORA = "dd/mm/yyyy hh:mm:ss"

CABECALHO = (
    "timestamp (horário de Brasília)",
    "categoria",
    "sentido",
    "id de rastreio",
    "confiança",
)


CABECALHO_DO_UPLOAD = (
    "vídeo",
    "deslocamento (MM:SS)",
    "categoria",
    "sentido",
    "id de rastreio",
    "confiança",
)


def _escrever_eventos_do_upload(planilha: Worksheet, dados: DadosDaExportacao) -> None:
    nomes = {video.posicao: video.nome_original for video in dados.sessao.videos}
    linha = escrever_cabecalho(planilha, dados.sessao, CABECALHO_DO_UPLOAD)

    for evento in dados.eventos:
        linha += 1
        planilha.cell(row=linha, column=1, value=nomes.get(evento.video))
        planilha.cell(
            row=linha, column=2, value=formatar_tempo(evento.deslocamento or 0)
        )
        planilha.cell(row=linha, column=3, value=evento.categoria.value)
        planilha.cell(row=linha, column=4, value=evento.sentido)
        planilha.cell(row=linha, column=5, value=evento.id_de_rastreio)
        planilha.cell(row=linha, column=6, value=evento.confianca)


def escrever_eventos(planilha: Worksheet, dados: DadosDaExportacao) -> None:
    """Escreve o aviso (se houver), o cabeçalho e uma linha por evento."""
    if dados.sessao.origem is OrigemDaSessao.UPLOAD:
        _escrever_eventos_do_upload(planilha, dados)
        return
    linha = escrever_cabecalho(planilha, dados.sessao, CABECALHO)

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

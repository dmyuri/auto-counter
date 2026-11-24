"""Aba Sessao — T-09.

Comportamento em `.spec/features/exportacao-xlsx/spec.md`: AC-010.4 (os
metadados da sessão), AC-010.5 (aviso na primeira linha) e SUP-033 (período em
data e hora reais do Excel, em horário de Brasília).

Nenhum campo carrega o instante da exportação (D-12 de `_tasks.md`): é o que
mantém as abas idênticas entre duas exportações (AC-010.6).

Por `processamento-upload` (AC-030.1, AC-030.3, D-10), a aba também traz a
origem, nas duas origens. No upload, quatro rótulos são trocados, o período é o
"horário do processamento" e, depois dos campos, há uma linha vazia e o bloco
com uma linha por vídeo.
"""

from openpyxl.worksheet.worksheet import Worksheet

from auto_counter.export.format import para_brasilia
from auto_counter.export.load import DadosDaExportacao
from auto_counter.export.sheet_common import escrever_cabecalho
from auto_counter.export.sheet_events import FORMATO_DATA_HORA
from auto_counter.storage.model import OrigemDaSessao
from auto_counter.tempo import formatar_tempo

CABECALHO = ("campo", "valor")

CAMPOS_DE_INSTANTE = (
    "início real",
    "fim real",
    "início (horário do processamento)",
    "fim (horário do processamento)",
)

CABECALHO_DOS_VIDEOS = ("vídeo", "nome", "duração (MM:SS)", "minutos")


def _minutos_do_video(inicial: int, final: int) -> str:
    return f"{inicial}" if inicial == final else f"{inicial} a {final}"


def escrever_sessao(planilha: Worksheet, dados: DadosDaExportacao) -> None:
    """Escreve o aviso (se houver), o cabeçalho e uma linha por campo."""
    sessao = dados.sessao
    upload = sessao.origem is OrigemDaSessao.UPLOAD
    campos = (
        ("id da sessão", sessao.id_sessao),
        ("origem", sessao.origem.value),
        ("id da câmera", sessao.id_camera),
        ("nome da câmera", sessao.nome_camera),
        ("sentido A", sessao.sentido_a),
        ("sentido B", sessao.sentido_b),
        (
            "início (horário do processamento)" if upload else "início real",
            sessao.inicio,
        ),
        (
            "fim (horário do processamento)" if upload else "fim real",
            sessao.fim,
        ),
        ("duração pedida (min)", sessao.duracao_pedida),
        ("duração real (min)", sessao.duracao_real),
        ("encerrada pelo usuário", "SIM" if sessao.encerrada_pelo_usuario else "NÃO"),
        (
            "encerrada por servidor indisponível",
            "SIM" if sessao.encerrada_por_servidor_indisponivel else "NÃO",
        ),
        ("status", sessao.status.value),
        (
            "minutos sem dado (falha de leitura)" if upload else "minutos perdidos",
            ", ".join(str(m) for m in sessao.minutos_perdidos) or "nenhum",
        ),
        ("versão do modelo", sessao.versao_do_modelo),
        (
            (
                "amostragem (frames por segundo de vídeo)"
                if upload
                else "amostragem (1 frame a cada N)"
            ),
            sessao.amostragem,
        ),
        ("limiar de confiança", sessao.limiar_de_confianca),
    )

    linha = escrever_cabecalho(planilha, sessao, CABECALHO)
    for campo, valor in campos:
        linha += 1
        planilha.cell(row=linha, column=1, value=campo)
        if campo in CAMPOS_DE_INSTANTE and valor is not None:
            celula = planilha.cell(row=linha, column=2, value=para_brasilia(valor))
            celula.number_format = FORMATO_DATA_HORA
        else:
            planilha.cell(row=linha, column=2, value=valor)

    if upload:
        linha += 2  # uma linha vazia entre os campos e o bloco de vídeos
        for coluna, titulo in enumerate(CABECALHO_DOS_VIDEOS, start=1):
            planilha.cell(row=linha, column=coluna, value=titulo)
        for video in sessao.videos:
            linha += 1
            planilha.cell(row=linha, column=1, value=video.posicao)
            planilha.cell(row=linha, column=2, value=video.nome_original)
            planilha.cell(
                row=linha, column=3, value=formatar_tempo(video.duracao_segundos)
            )
            planilha.cell(
                row=linha,
                column=4,
                value=_minutos_do_video(video.minuto_inicial, video.minuto_final),
            )

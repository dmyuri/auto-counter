"""Aba Sessao — T-09.

Comportamento em `.spec/features/exportacao-xlsx/spec.md`: AC-010.4 (os
metadados da sessão), AC-010.5 (aviso na primeira linha) e SUP-033 (período em
data e hora reais do Excel, em horário de Brasília).

Nenhum campo carrega o instante da exportação (D-12 de `_tasks.md`): é o que
mantém as abas idênticas entre duas exportações (AC-010.6).
"""

from openpyxl.worksheet.worksheet import Worksheet

from auto_counter.export.format import para_brasilia
from auto_counter.export.load import DadosDaExportacao
from auto_counter.export.sheet_common import escrever_cabecalho
from auto_counter.export.sheet_events import FORMATO_DATA_HORA

CABECALHO = ("campo", "valor")

CAMPOS_DE_INSTANTE = ("início real", "fim real")


def escrever_sessao(planilha: Worksheet, dados: DadosDaExportacao) -> None:
    """Escreve o aviso (se houver), o cabeçalho e uma linha por campo."""
    sessao = dados.sessao
    campos = (
        ("id da sessão", sessao.id_sessao),
        ("id da câmera", sessao.id_camera),
        ("nome da câmera", sessao.nome_camera),
        ("sentido A", sessao.sentido_a),
        ("sentido B", sessao.sentido_b),
        ("início real", sessao.inicio),
        ("fim real", sessao.fim),
        ("duração pedida (min)", sessao.duracao_pedida),
        ("duração real (min)", sessao.duracao_real),
        ("encerrada pelo usuário", "SIM" if sessao.encerrada_pelo_usuario else "NÃO"),
        ("status", sessao.status.value),
        (
            "minutos perdidos",
            ", ".join(str(m) for m in sessao.minutos_perdidos) or "nenhum",
        ),
        ("versão do modelo", sessao.versao_do_modelo),
        ("amostragem (1 frame a cada N)", sessao.amostragem),
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

"""Aba PorMinuto — T-08.

Comportamento em `.spec/features/exportacao-xlsx/spec.md`: AC-010.3, AC-010.5,
SUP-034 e SUP-035. A planilha é montada em memória, e o banco vive em
`tmp_path`.
"""

from openpyxl import Workbook

from auto_counter.capture.status import StatusDaSessao
from auto_counter.counting.config import Categoria
from auto_counter.export.load import carregar
from auto_counter.export.sheet_minutes import escrever_por_minuto
from auto_counter.storage.connection import conectar
from tests.export_helpers import (
    ID_SESSAO,
    SENTIDO_A,
    SENTIDO_B,
    evento,
    gravar_sessao,
)

EVENTOS = (
    evento(minuto=1, id_de_rastreio="1:1"),
    evento(minuto=1, id_de_rastreio="1:2", categoria=Categoria.MOTO),
    evento(
        minuto=1,
        id_de_rastreio="1:3",
        sentido=SENTIDO_B,
        categoria=Categoria.CAMINHAO,
    ),
)


def _aba(tmp_path, **campos):
    with conectar(tmp_path) as conexao:
        gravar_sessao(conexao, **campos)
        dados = carregar(conexao, ID_SESSAO)
    aba = Workbook().active
    escrever_por_minuto(aba, dados)
    return aba


def _linha(aba, numero):
    return [celula.value for celula in aba[numero]]


def test_AC_010_3_por_minuto_tem_uma_linha_por_minuto_do_periodo(tmp_path):
    aba = _aba(tmp_path, duracao_pedida=3, eventos=EVENTOS)

    assert [aba.cell(row=r, column=1).value for r in range(2, aba.max_row + 1)] == [
        1,
        2,
        3,
    ]


def test_AC_010_3_por_minuto_tem_as_onze_colunas_de_sentido_e_categoria_mais_total(
    tmp_path,
):
    aba = _aba(tmp_path, eventos=EVENTOS)

    assert _linha(aba, 1) == [
        "minuto",
        "estado",
        *(f"{SENTIDO_A} {c}" for c in ("CARRO", "MOTO", "ONIBUS", "CAMINHAO")),
        *(f"{SENTIDO_B} {c}" for c in ("CARRO", "MOTO", "ONIBUS", "CAMINHAO")),
        "total",
    ]
    assert aba.max_column == 11


def test_AC_010_3_o_total_do_minuto_e_a_soma_das_oito_combinacoes(tmp_path):
    aba = _aba(tmp_path, eventos=EVENTOS)

    # minuto 1: 1 carro e 1 moto no sentido A, 1 caminhão no sentido B
    assert _linha(aba, 2) == [1, "CAPTURADO", 1, 1, 0, 0, 0, 0, 0, 1, 3]


def test_AC_010_3_minuto_sem_dado_tem_celulas_de_contagem_vazias_e_nao_zero(tmp_path):
    aba = _aba(
        tmp_path,
        duracao_pedida=3,
        status=StatusDaSessao.DEGRADADA,
        minutos_perdidos=(2,),
        eventos=EVENTOS,
    )

    # linha 1 é o aviso, linha 2 o cabeçalho; o minuto 2 fica na linha 4
    assert _linha(aba, 4) == [2, "SEM_DADO"] + [None] * 9


def test_AC_010_3_minuto_capturado_sem_veiculo_mostra_zero(tmp_path):
    aba = _aba(tmp_path, duracao_pedida=2, eventos=EVENTOS)

    assert _linha(aba, 3) == [2, "CAPTURADO"] + [0] * 9


def test_AC_010_3_o_cabecalho_usa_os_rotulos_de_sentido_da_sessao(tmp_path):
    aba = _aba(tmp_path, sentido_a="Norte", sentido_b="Sul")

    assert aba["C1"].value == "Norte CARRO"
    assert aba["G1"].value == "Sul CARRO"


def test_AC_010_5_por_minuto_de_sessao_invalida_comeca_com_o_aviso(tmp_path):
    aba = _aba(
        tmp_path,
        duracao_pedida=2,
        status=StatusDaSessao.INVALIDA,
        minutos_perdidos=(1,),
    )

    assert aba["A1"].value.startswith("ATENÇÃO: sessão INVALIDA")
    assert aba["A2"].value == "minuto"

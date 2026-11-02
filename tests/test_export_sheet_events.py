"""Aba Eventos — T-07.

Comportamento em `.spec/features/exportacao-xlsx/spec.md`: AC-010.2, AC-010.5
e SUP-033. A planilha é montada em memória, e o banco vive em `tmp_path`.
"""

from datetime import datetime

from openpyxl import Workbook

from auto_counter.capture.status import StatusDaSessao
from auto_counter.counting.config import Categoria
from auto_counter.export.load import carregar
from auto_counter.export.sheet_events import CABECALHO, escrever_eventos
from auto_counter.storage.connection import conectar
from auto_counter.storage.events import contar_eventos
from tests.export_helpers import ID_SESSAO, SENTIDO_B, evento, gravar_sessao

EVENTOS = (
    evento(minuto=1, id_de_rastreio="1:1"),
    evento(
        minuto=1,
        id_de_rastreio="1:2",
        sentido=SENTIDO_B,
        categoria=Categoria.MOTO,
        confianca=0.75,
        segundos=20,
    ),
    evento(minuto=2, id_de_rastreio="2:1", categoria=Categoria.ONIBUS),
)


def _aba(tmp_path, **campos):
    with conectar(tmp_path) as conexao:
        gravar_sessao(conexao, **campos)
        dados = carregar(conexao, ID_SESSAO)
        total = contar_eventos(conexao, ID_SESSAO)
    aba = Workbook().active
    escrever_eventos(aba, dados)
    return aba, total


def test_AC_010_2_eventos_tem_uma_linha_por_cruzamento_gravado(tmp_path):
    aba, total = _aba(tmp_path, eventos=EVENTOS)

    assert aba.max_row - 1 == total == 3


def test_AC_010_2_eventos_traz_timestamp_categoria_sentido_rastreio_e_confianca(
    tmp_path,
):
    aba, _ = _aba(tmp_path, eventos=EVENTOS)

    assert tuple(c.value for c in aba[1]) == CABECALHO
    segunda = [c.value for c in aba[3]]
    assert segunda[1:] == ["MOTO", "Centro", "1:2", 0.75]


def test_AC_010_2_o_timestamp_e_data_e_hora_do_excel_em_horario_de_brasilia(tmp_path):
    aba, _ = _aba(tmp_path, eventos=EVENTOS)

    celula = aba["A2"]
    assert isinstance(celula.value, datetime)
    assert celula.value == datetime(2026, 9, 7, 8, 0, 15)
    assert celula.number_format == "dd/mm/yyyy hh:mm:ss"


def test_AC_010_5_eventos_de_sessao_invalida_comeca_com_o_aviso(tmp_path):
    aba, _ = _aba(
        tmp_path,
        duracao_pedida=2,
        status=StatusDaSessao.INVALIDA,
        minutos_perdidos=(1,),
        eventos=(evento(minuto=2, id_de_rastreio="2:1"),),
    )

    assert aba["A1"].value.startswith("ATENÇÃO: sessão INVALIDA")
    assert tuple(c.value for c in aba[2]) == CABECALHO


def test_AC_010_5_eventos_de_sessao_degradada_comeca_com_o_aviso(tmp_path):
    aba, _ = _aba(
        tmp_path,
        duracao_pedida=10,
        status=StatusDaSessao.DEGRADADA,
        minutos_perdidos=(3,),
    )

    assert aba["A1"].value.startswith("ATENÇÃO: sessão DEGRADADA")
    assert tuple(c.value for c in aba[2]) == CABECALHO


def test_sessao_completa_comeca_pelo_cabecalho(tmp_path):
    aba, _ = _aba(tmp_path, eventos=EVENTOS)

    assert tuple(c.value for c in aba[1]) == CABECALHO


def test_sessao_sem_nenhum_evento_produz_so_o_cabecalho(tmp_path):
    aba, _ = _aba(tmp_path)

    assert aba.max_row == 1

"""Nome do arquivo, conversão de fuso e linha de aviso — T-06.

Comportamento em `.spec/features/exportacao-xlsx/spec.md`: AC-010.1, AC-010.5,
SUP-032 e SUP-033. Funções puras: nenhum teste toca banco ou disco.
"""

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from auto_counter.capture.status import StatusDaSessao
from auto_counter.export.format import (
    linha_de_aviso,
    nome_do_arquivo,
    para_brasilia,
)
from auto_counter.storage.model import SessaoGravada

INICIO_UTC = datetime(2026, 9, 7, 11, 0, 5, tzinfo=timezone.utc)


def _sessao(**campos) -> SessaoGravada:
    base = dict(
        id_sessao="000013-20260907T110000Z",
        id_camera="000013",
        nome_camera="Praça Exemplo",
        criada_em=INICIO_UTC,
        inicio=INICIO_UTC,
        fim=INICIO_UTC,
        duracao_pedida=15,
        duracao_real=15,
        encerrada_pelo_usuario=False,
        status=StatusDaSessao.COMPLETA,
        minutos_perdidos_quantidade=0,
        minutos_perdidos=(),
        versao_do_modelo="yolo11n.onnx@abc123def456",
        amostragem=3,
        limiar_de_confianca=0.35,
        sentido_a="Icaraí",
        sentido_b="Centro",
    )
    base.update(campos)
    return SessaoGravada(**base)


def test_AC_010_1_nome_do_arquivo_identifica_camera_data_hora_e_duracao():
    assert nome_do_arquivo(_sessao()) == "000013_20260907_0800_15min.xlsx"


def test_AC_010_1_nome_usa_a_duracao_real_quando_o_usuario_encerrou_antes():
    sessao = _sessao(duracao_real=7, encerrada_pelo_usuario=True)

    assert nome_do_arquivo(sessao) == "000013_20260907_0800_7min.xlsx"


def test_AC_010_1_a_hora_do_nome_esta_no_horario_de_brasilia():
    sessao = _sessao(inicio=datetime(2026, 9, 7, 11, 0, 0, tzinfo=timezone.utc))

    assert "_0800_" in nome_do_arquivo(sessao)


def test_AC_010_5_status_invalida_aparece_no_nome_do_arquivo():
    sessao = _sessao(
        status=StatusDaSessao.INVALIDA,
        minutos_perdidos=(1, 2, 3, 4),
        minutos_perdidos_quantidade=4,
    )

    assert nome_do_arquivo(sessao) == "000013_20260907_0800_15min_INVALIDA.xlsx"


def test_AC_010_5_status_degradada_aparece_no_nome_do_arquivo():
    sessao = _sessao(
        status=StatusDaSessao.DEGRADADA,
        minutos_perdidos=(2,),
        minutos_perdidos_quantidade=1,
    )

    assert nome_do_arquivo(sessao) == "000013_20260907_0800_15min_DEGRADADA.xlsx"


def test_AC_010_5_sessao_completa_nao_tem_sufixo_de_status():
    assert "COMPLETA" not in nome_do_arquivo(_sessao())


def test_AC_010_5_aviso_traz_status_e_percentual_dos_minutos_perdidos():
    sessao = _sessao(
        status=StatusDaSessao.INVALIDA,
        minutos_perdidos=(1, 2, 3, 4),
        minutos_perdidos_quantidade=4,
    )

    assert linha_de_aviso(sessao) == (
        "ATENÇÃO: sessão INVALIDA — 4 de 15 minutos perdidos na captura (26,7%)"
    )


def test_AC_010_5_percentual_usa_a_duracao_real_como_base():
    sessao = _sessao(
        duracao_pedida=15,
        duracao_real=5,
        encerrada_pelo_usuario=True,
        status=StatusDaSessao.INVALIDA,
        minutos_perdidos=(1, 2),
        minutos_perdidos_quantidade=2,
    )

    assert "(40,0%)" in linha_de_aviso(sessao)


def test_sessao_completa_nao_tem_linha_de_aviso():
    assert linha_de_aviso(_sessao()) is None
    assert linha_de_aviso(replace(_sessao(), status=None)) is None


def test_para_brasilia_recusa_instante_sem_fuso():
    with pytest.raises(ValueError, match="sem fuso"):
        para_brasilia(datetime(2026, 9, 7, 11, 0, 0))


def test_para_brasilia_devolve_datetime_sem_tzinfo_para_o_excel():
    resultado = para_brasilia(INICIO_UTC)

    assert resultado.tzinfo is None
    assert resultado == datetime(2026, 9, 7, 8, 0, 5)

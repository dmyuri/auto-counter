"""Montagem e gravação do arquivo XLSX — T-10.

Comportamento em `.spec/features/exportacao-xlsx/spec.md`: AC-010.1, AC-010.5,
AC-010.6 e AC-010.7. O arquivo gravado é relido com `openpyxl`. Tudo acontece
em `tmp_path`.
"""

import shutil
import socket

import pytest
from openpyxl import load_workbook

from auto_counter.capture.status import StatusDaSessao
from auto_counter.counting.config import Categoria
from auto_counter.export import (
    SessaoEmAndamentoError,
    exportar_sessao,
)
from auto_counter.storage.connection import conectar
from tests.export_helpers import ID_SESSAO, SENTIDO_B, evento, gravar_sessao

EVENTOS = (
    evento(minuto=1, id_de_rastreio="1:1"),
    evento(
        minuto=2,
        id_de_rastreio="2:1",
        sentido=SENTIDO_B,
        categoria=Categoria.MOTO,
    ),
)


def _conteudo(caminho) -> dict:
    """Valor e formato de todas as células de cada aba."""
    pasta = load_workbook(caminho)
    return {
        aba.title: [
            [(c.value, c.number_format) for c in linha] for linha in aba.iter_rows()
        ]
        for aba in pasta.worksheets
    }


def test_AC_010_1_o_arquivo_tem_exatamente_as_abas_eventos_por_minuto_e_sessao(
    tmp_path,
):
    with conectar(tmp_path) as conexao:
        gravar_sessao(conexao, eventos=EVENTOS)
        caminho = exportar_sessao(conexao, ID_SESSAO, data_dir=tmp_path)

    assert load_workbook(caminho).sheetnames == ["Eventos", "PorMinuto", "Sessao"]


def test_AC_010_1_o_arquivo_e_gravado_no_diretorio_de_dados_com_o_nome_da_spec(
    tmp_path,
):
    with conectar(tmp_path) as conexao:
        gravar_sessao(conexao, duracao_pedida=15, eventos=EVENTOS)
        caminho = exportar_sessao(conexao, ID_SESSAO, data_dir=tmp_path)

    assert caminho == tmp_path / "000013_20260907_0800_15min.xlsx"
    assert caminho.is_file()


def test_AC_010_5_sessao_invalida_gera_planilha_com_aviso_nas_tres_abas_e_no_nome(
    tmp_path,
):
    with conectar(tmp_path) as conexao:
        gravar_sessao(
            conexao,
            duracao_pedida=15,
            status=StatusDaSessao.INVALIDA,
            minutos_perdidos=(1, 2, 3, 4),
        )
        caminho = exportar_sessao(conexao, ID_SESSAO, data_dir=tmp_path)

    assert caminho.name == "000013_20260907_0800_15min_INVALIDA.xlsx"
    for aba in load_workbook(caminho).worksheets:
        assert aba["A1"].value.startswith("ATENÇÃO: sessão INVALIDA"), aba.title


def test_AC_010_6_exportar_duas_vezes_produz_abas_com_conteudo_identico(tmp_path):
    with conectar(tmp_path) as conexao:
        gravar_sessao(conexao, eventos=EVENTOS)
        primeiro = exportar_sessao(conexao, ID_SESSAO, data_dir=tmp_path)
        copia = tmp_path / "primeira.xlsx"
        shutil.copy(primeiro, copia)
        segundo = exportar_sessao(conexao, ID_SESSAO, data_dir=tmp_path)

    assert _conteudo(copia) == _conteudo(segundo)


def test_AC_010_7_exporta_sem_arquivo_de_video_e_sem_rede(tmp_path, monkeypatch):
    with conectar(tmp_path) as conexao:
        gravar_sessao(conexao, eventos=EVENTOS)

        def sem_rede(*args, **kwargs):
            raise AssertionError("a exportação tentou abrir uma conexão de rede")

        monkeypatch.setattr(socket, "socket", sem_rede)
        caminho = exportar_sessao(conexao, ID_SESSAO, data_dir=tmp_path)

    assert not (tmp_path / "sessions").exists()
    assert caminho.is_file()


def test_sessao_em_andamento_nao_gera_arquivo(tmp_path):
    with conectar(tmp_path) as conexao:
        gravar_sessao(conexao, status=None)
        with pytest.raises(SessaoEmAndamentoError):
            exportar_sessao(conexao, ID_SESSAO, data_dir=tmp_path)

    assert list(tmp_path.glob("*.xlsx")) == []

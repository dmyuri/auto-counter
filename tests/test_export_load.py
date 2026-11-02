"""Carga dos dados de uma sessão a partir do banco — T-05.

Comportamento em `.spec/features/exportacao-xlsx/spec.md`: AC-010.2 (todos os
eventos gravados), AC-010.7 (só o banco) e SUP-037 (sessão em andamento).

Nenhum teste grava banco dentro do repositório: tudo acontece em `tmp_path`.
"""

import ast
from pathlib import Path

import pytest

import auto_counter.export
from auto_counter.export.load import (
    SessaoEmAndamentoError,
    SessaoNaoEncontradaError,
    SessaoNaoProcessadaError,
    carregar,
)
from auto_counter.storage.connection import conectar
from auto_counter.storage.events import contar_eventos
from tests.export_helpers import ID_SESSAO, evento, gravar_sessao


def test_AC_010_7_carregar_le_a_sessao_sem_diretorio_de_sessao_em_disco(tmp_path):
    with conectar(tmp_path) as conexao:
        gravar_sessao(conexao)
        dados = carregar(conexao, ID_SESSAO)

    assert not (tmp_path / "sessions").exists()
    assert dados.sessao.id_sessao == ID_SESSAO
    assert len(dados.agregados) == 2


def test_AC_010_2_carregar_traz_todos_os_eventos_gravados_da_sessao(tmp_path):
    eventos = (
        evento(minuto=1, id_de_rastreio="1:1"),
        evento(minuto=1, id_de_rastreio="1:2"),
        evento(minuto=2, id_de_rastreio="2:1"),
    )
    with conectar(tmp_path) as conexao:
        gravar_sessao(conexao, eventos=eventos)
        dados = carregar(conexao, ID_SESSAO)
        total = contar_eventos(conexao, ID_SESSAO)

    assert len(dados.eventos) == total == 3


def test_sessao_inexistente_e_recusada_citando_o_id(tmp_path):
    with conectar(tmp_path) as conexao:
        with pytest.raises(SessaoNaoEncontradaError, match="nao-existe"):
            carregar(conexao, "nao-existe")


def test_sessao_em_andamento_e_recusada_com_erro(tmp_path):
    with conectar(tmp_path) as conexao:
        gravar_sessao(conexao, status=None)
        with pytest.raises(SessaoEmAndamentoError, match=ID_SESSAO):
            carregar(conexao, ID_SESSAO)


def test_sessao_capturada_mas_nao_processada_e_recusada_com_erro(tmp_path):
    with conectar(tmp_path) as conexao:
        gravar_sessao(conexao, processada=False)
        with pytest.raises(SessaoNaoProcessadaError, match="session process"):
            carregar(conexao, ID_SESSAO)


def test_o_modulo_export_nao_importa_captura_contagem_nem_rede():
    proibidos = (
        "cv2",
        "httpx",
        "auto_counter.capture",
        "auto_counter.counting.clip",
        "auto_counter.cameras.registry",
    )
    encontrados = []
    for arquivo in Path(auto_counter.export.__file__).parent.glob("*.py"):
        for no in ast.walk(ast.parse(arquivo.read_text(encoding="utf-8"))):
            if isinstance(no, ast.Import):
                nomes = [alias.name for alias in no.names]
            elif isinstance(no, ast.ImportFrom):
                nomes = [no.module or ""]
            else:
                continue
            encontrados += [
                (arquivo.name, nome)
                for nome in nomes
                if any(nome == p or nome.startswith(p + ".") for p in proibidos)
            ]

    assert encontrados == []

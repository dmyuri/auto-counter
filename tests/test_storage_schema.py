"""Migration 001: as três tabelas e a versão do schema — T-02.

Comportamento em `.spec/features/persistencia-resultados/spec.md`: estrutura
exigida por AC-008.1, AC-008.2, AC-008.3 e AC-008.4, implementando SUP-024
(arquivo único), SUP-028 (minuto sem dado é coluna de estado, não ausência de
linha nem contagem nula) e SUP-030 (timestamps em UTC).

Nenhum AC é provado diretamente aqui — isso é entrega de T-03 a T-07, que
gravam e leem através deste schema. Este arquivo prova a estrutura: a
migration aplica, não duplica ao reaplicar, as três tabelas existem, e as
restrições de domínio (status, categoria, consistência de SEM_DADO/CAPTURADO)
são do próprio SQLite, não de uma validação que alguém pode esquecer de
chamar.

Nenhum teste grava banco dentro do repositório: tudo acontece em `tmp_path`.
"""

import sqlite3

import pytest

from auto_counter.storage import schema
from auto_counter.storage.connection import conectar
from auto_counter.storage.schema import MIGRATIONS, VERSAO_ATUAL

ID_CAMERA = "000013"
CRIADA_EM = "2026-01-01T00:00:00+00:00"

COLUNAS_DE_CONTAGEM = (
    "sentido_a_carro",
    "sentido_a_moto",
    "sentido_a_onibus",
    "sentido_a_caminhao",
    "sentido_b_carro",
    "sentido_b_moto",
    "sentido_b_onibus",
    "sentido_b_caminhao",
)
"""As oito colunas de contagem da tabela `minuto` (SUP-034: 2 sentidos × 4
categorias), nomeadas pelos papéis `sentido_a` / `sentido_b` (D-6), nunca
pelos rótulos de uma câmera específica."""


def _inserir_sessao(conexao: sqlite3.Connection, id_sessao: str = "s1") -> None:
    """Uma linha mínima e válida de `sessao`, pré-condição das FKs de `evento`
    e `minuto`."""
    conexao.execute(
        """
        INSERT INTO sessao (id_sessao, id_camera, criada_em, duracao_pedida)
        VALUES (?, ?, ?, ?)
        """,
        (id_sessao, ID_CAMERA, CRIADA_EM, 5),
    )


def test_a_primeira_conexao_aplica_a_migration_001_e_grava_a_versao(tmp_path):
    """A migration 001 roda sozinha na primeira conexão, sem comando manual."""
    with conectar(tmp_path) as conexao:
        linhas = conexao.execute(
            "SELECT versao, aplicada_em FROM schema_version"
        ).fetchall()

    assert [linha["versao"] for linha in linhas] == sorted(MIGRATIONS)
    assert linhas[0]["aplicada_em"]  # não vazio: é o instante real da aplicação


def test_aplicar_migrations_duas_vezes_nao_reaplica_nem_duplica_versao(tmp_path):
    """Reconectar não reaplica a migration nem duplica a linha de versão."""
    with conectar(tmp_path):
        pass

    with conectar(tmp_path) as conexao:
        linhas = conexao.execute(
            "SELECT versao FROM schema_version"
        ).fetchall()

    assert [linha["versao"] for linha in linhas] == sorted(MIGRATIONS)


def test_um_banco_novo_chega_a_versao_2(tmp_path):
    with conectar(tmp_path) as conexao:
        versao = conexao.execute("SELECT MAX(versao) AS v FROM schema_version").fetchone()

    assert versao["v"] == 2
    assert VERSAO_ATUAL == 2


def test_banco_na_versao_1_sobe_para_a_2_sem_perder_as_sessoes_gravadas(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(schema, "MIGRATIONS", {1: MIGRATIONS[1]})
    with conectar(tmp_path) as conexao:
        _inserir_sessao(conexao, "antiga")
        conexao.commit()

    monkeypatch.undo()
    with conectar(tmp_path) as conexao:
        versoes = [
            linha["versao"]
            for linha in conexao.execute("SELECT versao FROM schema_version")
        ]
        sessao = conexao.execute(
            "SELECT id_camera, nome_camera FROM sessao WHERE id_sessao = 'antiga'"
        ).fetchone()

    assert versoes == [1, 2]
    assert sessao["id_camera"] == ID_CAMERA
    assert sessao["nome_camera"] is None


def test_as_tres_tabelas_existem_depois_da_migration(tmp_path):
    """`sessao`, `evento` e `minuto` existem depois da primeira conexão."""
    with conectar(tmp_path) as conexao:
        nomes = {
            linha["name"]
            for linha in conexao.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    assert {"sessao", "evento", "minuto", "schema_version"} <= nomes


def test_status_fora_do_vocabulario_de_tres_e_recusado_pelo_banco(tmp_path):
    """Só `COMPLETA`, `DEGRADADA` e `INVALIDA` (ou nulo) são aceitos."""
    with conectar(tmp_path) as conexao:
        with pytest.raises(sqlite3.IntegrityError):
            conexao.execute(
                """
                INSERT INTO sessao
                    (id_sessao, id_camera, criada_em, duracao_pedida, status)
                VALUES (?, ?, ?, ?, ?)
                """,
                ("s1", ID_CAMERA, CRIADA_EM, 5, "EM_ANDAMENTO"),
            )


def test_categoria_fora_das_quatro_e_recusada_pelo_banco(tmp_path):
    """Só `CARRO`, `MOTO`, `ONIBUS` e `CAMINHAO` são aceitos em `evento`."""
    with conectar(tmp_path) as conexao:
        _inserir_sessao(conexao)
        with pytest.raises(sqlite3.IntegrityError):
            conexao.execute(
                """
                INSERT INTO evento
                    (id_sessao, id_de_rastreio, sentido, timestamp, categoria,
                     confianca, minuto)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                ("s1", "1:1", "Icaraí", "2026-01-01T00:01:00+00:00",
                 "BICICLETA", 0.9, 1),
            )


def test_minuto_sem_dado_com_contagem_preenchida_e_recusado_pelo_banco(tmp_path):
    """SUP-028/AC-008.4: minuto `SEM_DADO` não pode ter contagem nenhuma."""
    with conectar(tmp_path) as conexao:
        _inserir_sessao(conexao)
        colunas = ", ".join(COLUNAS_DE_CONTAGEM)
        marcadores = ", ".join("?" for _ in COLUNAS_DE_CONTAGEM)
        with pytest.raises(sqlite3.IntegrityError):
            conexao.execute(
                f"""
                INSERT INTO minuto (id_sessao, minuto, estado, {colunas})
                VALUES (?, ?, ?, {marcadores})
                """,
                ("s1", 1, "SEM_DADO", *([0] * len(COLUNAS_DE_CONTAGEM))),
            )


def test_minuto_capturado_sem_contagem_e_recusado_pelo_banco(tmp_path):
    """AC-008.3: minuto `CAPTURADO` precisa das oito contagens, zero inclusive."""
    with conectar(tmp_path) as conexao:
        _inserir_sessao(conexao)
        with pytest.raises(sqlite3.IntegrityError):
            conexao.execute(
                "INSERT INTO minuto (id_sessao, minuto, estado) VALUES (?, ?, ?)",
                ("s1", 1, "CAPTURADO"),
            )


def test_minuto_capturado_com_as_oito_contagens_e_aceito(tmp_path):
    """Sanidade: o caminho válido de AC-008.3 não é recusado pelo CHECK."""
    with conectar(tmp_path) as conexao:
        _inserir_sessao(conexao)
        colunas = ", ".join(COLUNAS_DE_CONTAGEM)
        marcadores = ", ".join("?" for _ in COLUNAS_DE_CONTAGEM)
        conexao.execute(
            f"""
            INSERT INTO minuto (id_sessao, minuto, estado, {colunas})
            VALUES (?, ?, ?, {marcadores})
            """,
            ("s1", 1, "CAPTURADO", *([0] * len(COLUNAS_DE_CONTAGEM))),
        )
        conexao.commit()


def test_evento_de_sessao_inexistente_e_recusado_pela_chave_estrangeira(tmp_path):
    """A FK de `evento` para `sessao` depende de `PRAGMA foreign_keys = ON`."""
    with conectar(tmp_path) as conexao:
        with pytest.raises(sqlite3.IntegrityError):
            conexao.execute(
                """
                INSERT INTO evento
                    (id_sessao, id_de_rastreio, sentido, timestamp, categoria,
                     confianca, minuto)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                ("sessao-inexistente", "1:1", "Icaraí",
                 "2026-01-01T00:01:00+00:00", "CARRO", 0.9, 1),
            )

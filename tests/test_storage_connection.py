"""Conexão com o banco SQLite — T-01.

Comportamento em `.spec/features/persistencia-resultados/spec.md`: implementa
a parte de "arquivo único criado na primeira execução" de SUP-024 (o banco é
um arquivo SQLite único em `<data_dir>/auto_counter.db`).

Nenhum teste aqui aplica migration: isso é entrega de T-02. Aqui só se prova
que o arquivo nasce no caminho certo, que reconectar não o recria, e que a
conexão sai com a chave estrangeira ligada — pré-condição para as tabelas
ligadas por FK que T-02 vai criar.

Nenhum teste grava banco dentro do repositório: tudo acontece em `tmp_path`.
"""

from pathlib import Path

from auto_counter.storage.connection import caminho_do_banco, conectar


def test_o_banco_e_criado_na_primeira_conexao_no_caminho_da_spec(tmp_path):
    """SUP-024: o banco é `<data_dir>/auto_counter.db`."""
    caminho_esperado = tmp_path / "auto_counter.db"
    assert not caminho_esperado.exists()

    with conectar(tmp_path):
        pass

    assert caminho_esperado.is_file()
    assert caminho_do_banco(tmp_path) == caminho_esperado


def test_conectar_cria_o_diretorio_de_dados_quando_ele_nao_existe(tmp_path):
    """`data_dir` pode não existir ainda na primeira execução da máquina."""
    data_dir = tmp_path / "ainda-nao-existe"
    assert not data_dir.exists()

    with conectar(data_dir):
        pass

    assert (data_dir / "auto_counter.db").is_file()


def test_conectar_duas_vezes_reusa_o_mesmo_arquivo_sem_recriar(tmp_path):
    """Reconectar não apaga nem recria o arquivo existente."""
    with conectar(tmp_path):
        pass

    caminho = caminho_do_banco(tmp_path)
    tamanho_antes = caminho.stat().st_size
    mtime_antes = caminho.stat().st_mtime_ns

    with conectar(tmp_path):
        pass

    assert caminho.stat().st_size == tamanho_antes
    assert caminho.stat().st_mtime_ns == mtime_antes


def test_a_conexao_vem_com_chave_estrangeira_ligada(tmp_path):
    """`PRAGMA foreign_keys` precisa estar `ON` para as FKs de T-02 valerem."""
    with conectar(tmp_path) as conexao:
        (valor,) = conexao.execute("PRAGMA foreign_keys").fetchone()
        assert valor == 1


def test_a_conexao_devolve_linhas_acessiveis_por_nome_de_coluna(tmp_path):
    """`row_factory = sqlite3.Row`: o código que lê acessa coluna por nome."""
    with conectar(tmp_path) as conexao:
        linha = conexao.execute("SELECT 1 AS um").fetchone()
        assert linha["um"] == 1


def test_caminho_do_banco_nao_toca_o_disco(tmp_path):
    """`caminho_do_banco` só monta o `Path`; não cria arquivo nem diretório."""
    data_dir = tmp_path / "outro"
    caminho = caminho_do_banco(data_dir)
    assert caminho == data_dir / "auto_counter.db"
    assert not data_dir.exists()

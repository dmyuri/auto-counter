"""Conexão com o banco SQLite da sessão — T-01 e T-02.

Comportamento em `.spec/features/persistencia-resultados/spec.md`: implementa
a parte de "arquivo único criado na primeira execução" de SUP-024 — o banco é
um arquivo SQLite único em `<data_dir>/auto_counter.db`, com o schema aplicado
por migration (T-02, `storage.schema`) antes de a conexão ser entregue a quem
chamou.

`detect_types` com `PARSE_DECLTYPES` não é usado: os instantes são texto
ISO 8601 UTC (SUP-030), e a conversão é explícita nas funções que gravam e
leem, para que o fuso nunca dependa de configuração do driver.
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from auto_counter.storage.schema import aplicar_migrations

NOME_DO_ARQUIVO_DO_BANCO = "auto_counter.db"
"""Nome do arquivo dentro do diretório de dados (SUP-024)."""


def caminho_do_banco(data_dir: str | Path) -> Path:
    """`<data_dir>/auto_counter.db` (SUP-024).

    Só monta o caminho — não cria diretório nem arquivo. O `data_dir` chega
    por parâmetro; quem resolve `AUTO_COUNTER_DATA_DIR` é o CLI, com
    `VARIAVEL_DATA_DIR` e `DATA_DIR_PADRAO` de `auto_counter.cli`.
    """
    return Path(data_dir) / NOME_DO_ARQUIVO_DO_BANCO


@contextmanager
def conectar(data_dir: str | Path):
    """Abre (ou cria) o banco da sessão e devolve a conexão.

    Cria o diretório de dados se ele ainda não existir — a primeira execução
    da máquina não tem nem `data_dir` nem banco. A conexão sai com
    `PRAGMA foreign_keys = ON`, pré-condição para as chaves estrangeiras que
    `evento` e `minuto` declaram, com `row_factory = sqlite3.Row`, para que o
    código que lê acesse coluna por nome, nunca por posição, e já com o
    schema na versão mais recente aplicado (T-02) — quem chama nunca precisa
    lembrar de aplicar migration.

    Gerenciador de contexto: fecha a conexão ao saír do bloco `with`, mesmo em
    caso de exceção. Fora da aplicação das migrations, não dá commit
    automático — quem grava decide a própria transação, como as funções de
    T-05 e T-07 exigem (tudo-ou-nada).
    """
    caminho = caminho_do_banco(data_dir)
    caminho.parent.mkdir(parents=True, exist_ok=True)

    conexao = sqlite3.connect(caminho)
    conexao.row_factory = sqlite3.Row
    try:
        conexao.execute("PRAGMA foreign_keys = ON")
        aplicar_migrations(conexao)
        yield conexao
    finally:
        conexao.close()

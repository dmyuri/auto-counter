"""Aplicação das migrations do schema — T-02.

Comportamento em `.spec/features/persistencia-resultados/spec.md` (SUP-024):
o schema é gravado em migrations numeradas, com a versão aplicada registrada
em tabela própria. Uma migration, depois de commitada, é imutável
(`CLAUDE.md`) — campo novo é a migration seguinte, nunca edição de um arquivo
já existente neste diretório.

Cada migration é aplicada **numa única transação**: o DDL e o registro da
nova versão em `schema_version` sobem juntos, ou nenhum dos dois sobe. Por
isso o SQL de cada arquivo é executado instrução por instrução, com `BEGIN`
explícito — `sqlite3.Connection.executescript` dá COMMIT implícito antes de
rodar o script, o que quebraria essa atomicidade.
"""

import importlib.resources
import sqlite3
from datetime import datetime, timezone

MIGRATIONS: dict[int, str] = {
    1: "001_inicial.sql",
    2: "002_nome_camera.sql",
    3: "003_upload.sql",
    4: "004_sessao_cancelada.sql",
}
"""Versão → nome do arquivo em `storage/migrations/`. Só cresce no fim."""

VERSAO_ATUAL = max(MIGRATIONS)


def _versao_aplicada(conexao: sqlite3.Connection) -> int:
    """A versão mais alta já aplicada neste banco, ou 0 se nenhuma.

    Zero também é a resposta de um banco recém-criado, em que
    `schema_version` ainda não existe — e não existir é informação, não
    corrupção: é exatamente o estado anterior à migration 1.
    """
    try:
        linha = conexao.execute(
            "SELECT MAX(versao) AS versao FROM schema_version"
        ).fetchone()
    except sqlite3.OperationalError:
        return 0
    return linha["versao"] or 0


def _sql_da_migration(nome_do_arquivo: str) -> str:
    """O texto SQL de uma migration, lido como dado do pacote instalado.

    `importlib.resources`, e não um caminho relativo a `__file__` montado à
    mão: o `.sql` precisa ser encontrado tanto em instalação editável quanto
    empacotada.
    """
    recurso = importlib.resources.files("auto_counter.storage") / "migrations" / nome_do_arquivo
    return recurso.read_text(encoding="utf-8")


def _instrucoes(sql: str) -> list[str]:
    """Quebra o arquivo em instruções individuais, sem os comentários `--`.

    Instruções são executadas uma a uma (e não com `executescript`) para que
    todas caibam na mesma transação explícita de `aplicar_migrations`.
    """
    sem_comentarios = "\n".join(linha.split("--", 1)[0] for linha in sql.splitlines())
    return [
        instrucao.strip() for instrucao in sem_comentarios.split(";") if instrucao.strip()
    ]


def aplicar_migrations(conexao: sqlite3.Connection) -> None:
    """Aplica, em ordem, toda migration com versão maior que a já aplicada.

    Banco novo: aplica a migration 1 (e as seguintes, se existirem). Banco já
    na versão atual: não faz nada — reaplicar é inócuo, como a spec exige.
    """
    atual = _versao_aplicada(conexao)
    pendentes = sorted(versao for versao in MIGRATIONS if versao > atual)

    for versao in pendentes:
        sql = _sql_da_migration(MIGRATIONS[versao])
        conexao.execute("BEGIN")
        try:
            for instrucao in _instrucoes(sql):
                conexao.execute(instrucao)
            conexao.execute(
                "INSERT INTO schema_version (versao, aplicada_em) VALUES (?, ?)",
                (versao, datetime.now(timezone.utc).isoformat()),
            )
        except Exception:
            conexao.rollback()
            raise
        else:
            conexao.commit()

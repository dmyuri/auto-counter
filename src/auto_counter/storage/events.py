"""Gravação dos eventos de cruzamento — T-05.

Comportamento em `.spec/features/persistencia-resultados/spec.md`: AC-008.2.

Os objetos gravados são os `Evento` de `counting.events` — os mesmos que
`counting.events.ler` devolve de um `eventos.json` real. Este módulo não
redefine o evento: `indice_do_frame` e `posicao_na_linha` não têm coluna no
schema (T-02), porque AC-008.2 não os exige — são diagnóstico de
`contagem-veiculos`, não dado persistido.

`gravar_eventos` **não comita**: quem controla a transação é
`persistir_sessao` (T-07), que precisa gravar sessão, eventos e agregados
como tudo-ou-nada.
"""

import sqlite3
from collections.abc import Iterable

from auto_counter.counting.config import Categoria
from auto_counter.counting.events import Evento
from auto_counter.storage.model import EventoGravado
from auto_counter.storage.sessions import (
    SessaoInexistenteError,
    _desserializa_instante,
)


def gravar_eventos(
    conexao: sqlite3.Connection, id_sessao: str, eventos: Iterable[Evento]
) -> None:
    """Grava os eventos de uma sessão (AC-008.2).

    A chave `(id_sessao, id_de_rastreio, sentido)` é a mesma de AC-006.6 de
    `contagem-veiculos` (no máximo um evento por par rastreio+sentido):
    `ON CONFLICT ... DO UPDATE` faz regravar a mesma sessão produzir o mesmo
    conteúdo (AC-008.5), em vez de erro de integridade.

    `timestamp` já chega normalizado em UTC com fuso explícito — é
    `Evento.__post_init__` quem garante isso (SUP-030); esta função só grava
    o que recebeu.

    Sessão inexistente é recusada pela chave estrangeira; o erro cru do
    SQLite é traduzido para `SessaoInexistenteError`, com o id citado.
    """
    linhas = [
        (
            id_sessao,
            evento.id_de_rastreio,
            evento.sentido,
            evento.timestamp.isoformat(),
            evento.categoria.value,
            evento.confianca,
            evento.minuto,
            evento.video,
            evento.deslocamento_segundos,
        )
        for evento in eventos
    ]
    if not linhas:
        return

    try:
        conexao.executemany(
            """
            INSERT INTO evento
                (id_sessao, id_de_rastreio, sentido, timestamp, categoria,
                 confianca, minuto, video, deslocamento)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id_sessao, id_de_rastreio, sentido) DO UPDATE SET
                timestamp = excluded.timestamp,
                categoria = excluded.categoria,
                confianca = excluded.confianca,
                minuto = excluded.minuto,
                video = excluded.video,
                deslocamento = excluded.deslocamento
            """,
            linhas,
        )
    except sqlite3.IntegrityError as falha:
        raise SessaoInexistenteError(id_sessao) from falha


def contar_eventos(conexao: sqlite3.Connection, id_sessao: str) -> int:
    """O total de eventos de uma sessão.

    Usado por T-09 (total de AC-009.2) e pelos testes de AC-008.5 para
    conferir que regravar a mesma sessão não duplica nada.
    """
    linha = conexao.execute(
        "SELECT COUNT(*) AS contagem FROM evento WHERE id_sessao = ?",
        (id_sessao,),
    ).fetchone()
    return linha["contagem"]


def ler_eventos(
    conexao: sqlite3.Connection, id_sessao: str
) -> tuple[EventoGravado, ...]:
    """Lê os eventos gravados de uma sessão, em ordem determinística.

    `SELECT` puro, ordenado por `timestamp, id_de_rastreio, sentido` para que
    duas leituras do mesmo banco devolvam a mesma sequência. O timestamp volta
    para UTC ciente de fuso pelo mesmo caminho de `ler_sessao`.

    Sessão inexistente é `SessaoInexistenteError`; sessão existente sem evento
    é tupla vazia. As duas situações são diferentes e não se confundem.
    """
    existe = conexao.execute(
        "SELECT 1 FROM sessao WHERE id_sessao = ?", (id_sessao,)
    ).fetchone()
    if existe is None:
        raise SessaoInexistenteError(id_sessao)

    linhas = conexao.execute(
        """
        SELECT id_de_rastreio, sentido, timestamp, categoria, confianca, minuto,
               video, deslocamento
        FROM evento
        WHERE id_sessao = ?
        ORDER BY timestamp, id_de_rastreio, sentido
        """,
        (id_sessao,),
    ).fetchall()
    return tuple(
        EventoGravado(
            id_de_rastreio=linha["id_de_rastreio"],
            sentido=linha["sentido"],
            timestamp=_desserializa_instante(linha["timestamp"]),
            categoria=Categoria(linha["categoria"]),
            confianca=linha["confianca"],
            minuto=linha["minuto"],
            video=linha["video"],
            deslocamento=linha["deslocamento"],
        )
        for linha in linhas
    )

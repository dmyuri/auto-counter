"""A linha de sessão: abrir, fechar a captura, completar o processamento —
T-03.

Comportamento em `.spec/features/persistencia-resultados/spec.md`: AC-008.1.

O ciclo de vida de uma linha de sessão tem três momentos (D-1 de `_tasks.md`):

1. `abrir_sessao` — chamada no início da captura, com id, câmera, duração
   pedida e os rótulos de sentido vigentes (D-6). Tudo o que só existe depois
   fica nulo. É o que torna o registro existente desde o início da captura,
   pré-condição de AC-012.4 de `interface-sessao`;
2. `fechar_captura` — chamada no fim da captura, com o período real
   (AC-003.4), a duração real e o encerramento (AC-003.6), o status
   (AC-004.4 a AC-004.6) e a lista de minutos perdidos;
3. `completar_processamento` — chamada no fim do processamento, com a versão
   do modelo, a amostragem e o limiar usados (AC-008.1).

Cada função grava e comita imediatamente, no mesmo espírito de
`capture.manifest.ManifestDaSessao`: uma queda entre a captura e o
processamento não pode levar junto o que já foi registrado.

Timestamps são gravados em UTC, texto ISO 8601 com fuso explícito (SUP-030) —
um `datetime` sem fuso é recusado, porque não há como saber se ele já era UTC.

`PersistenciaDaCaptura` (T-04) é a implementação concreta do `Persistencia`
de `capture.session`: liga os dois primeiros momentos de D-1 à captura de
verdade. Falha ao abrir ou gravar não interrompe a captura (`CLAUDE.md`): ela
só é avisada, porque a captura é a operação que não volta e o manifest
continua sendo prova durável suficiente até o processamento regravar a sessão
(D-7 de `_tasks.md`).
"""

import json
import sqlite3
import sys
from collections.abc import Callable
from datetime import datetime, timezone

from auto_counter.cameras.model import Camera
from auto_counter.capture.status import StatusDaSessao
from auto_counter.storage.model import SessaoGravada, SessaoNoHistorico


class SessaoInexistenteError(LookupError):
    """A sessão citada não tem linha em `sessao`.

    `fechar_captura` e `completar_processamento` são `UPDATE`s: sem esta
    checagem, uma sessão inexistente passaria em silêncio como um `UPDATE`
    de zero linhas, e ninguém notaria que nada foi gravado.
    """

    def __init__(self, id_sessao: str) -> None:
        self.id_sessao = id_sessao
        super().__init__(
            f"a sessão '{id_sessao}' não tem registro em `sessao`; "
            f"ela precisa ter sido aberta com abrir_sessao antes"
        )


def _em_utc(instante: datetime) -> datetime:
    """Normaliza para UTC ciente de fuso (SUP-030).

    Sem `tzinfo` não há como saber se o valor já era UTC, e assumir seria
    inventar hora — mesma recusa de `capture/manifest.py` e
    `counting/events.py`.
    """
    if instante.tzinfo is None:
        raise ValueError(
            f"instante sem fuso horário ({instante!r}); a sessão é gravada em "
            f"UTC com fuso explícito, e um datetime ingênuo não diz qual é o "
            f"dele"
        )
    return instante.astimezone(timezone.utc)


def _serializa_instante(instante: datetime | None) -> str | None:
    """ISO 8601 em UTC com fuso explícito, ou nulo."""
    return None if instante is None else _em_utc(instante).isoformat()


def _desserializa_instante(bruto: str | None) -> datetime | None:
    """Volta do ISO 8601 para `datetime` UTC, preservando o nulo."""
    return None if bruto is None else _em_utc(datetime.fromisoformat(bruto))


def abrir_sessao(
    conexao: sqlite3.Connection,
    *,
    id_sessao: str,
    id_camera: str,
    criada_em: datetime,
    duracao_pedida: int,
    sentido_a: str,
    sentido_b: str,
    nome_camera: str | None = None,
    comitar: bool = True,
) -> None:
    """Momento 1 de D-1: abre a linha no início da captura.

    `nome_camera` é opcional (migration 002, AC-010.4): o nome vigente na
    sessão, gravado como os rótulos de sentido.

    `status`, `inicio`, `fim`, `duracao_real`, `versao_do_modelo`,
    `amostragem` e `limiar_de_confianca` ficam nulos — eles só existem a
    partir de `fechar_captura` e `completar_processamento`.

    Idempotente: reabrir a mesma sessão (`ON CONFLICT DO NOTHING`) não apaga
    o que um `fechar_captura` ou `completar_processamento` já tiver gravado.

    `comitar=False` é para quem já controla a própria transação — o upsert
    de `persistir_sessao` (T-07), que precisa de sessão, eventos e agregados
    como tudo-ou-nada. O padrão (`True`) é o uso direto de T-04, onde cada
    chamada é a própria unidade de gravação.
    """
    conexao.execute(
        """
        INSERT INTO sessao
            (id_sessao, id_camera, criada_em, duracao_pedida,
             sentido_a, sentido_b, nome_camera)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (id_sessao) DO NOTHING
        """,
        (
            id_sessao,
            id_camera,
            _serializa_instante(criada_em),
            duracao_pedida,
            sentido_a,
            sentido_b,
            nome_camera,
        ),
    )
    if comitar:
        conexao.commit()


def fechar_captura(
    conexao: sqlite3.Connection,
    id_sessao: str,
    *,
    inicio: datetime | None,
    fim: datetime | None,
    duracao_real: int,
    encerrada_pelo_usuario: bool,
    status: StatusDaSessao,
    minutos_perdidos: list[int] | tuple[int, ...],
    comitar: bool = True,
) -> None:
    """Momento 2 de D-1: grava o desfecho da captura.

    `status` é um `StatusDaSessao` de `capture.status`, gravado como
    `.value` — nenhuma tabela de tradução própria. `minutos_perdidos` é a
    lista de AC-004.5/AC-004.6 (os minutos perdidos **na captura**, não os
    não processados), gravada como JSON ao lado da quantidade.

    `comitar=False`: mesma regra de `abrir_sessao`, para quem controla a
    própria transação (T-07). A falha de "sessão inexistente" sempre desfaz
    a transação até aqui, comitada ou não — ela não pode deixar um `UPDATE`
    pendente de nada no meio de uma transação maior.
    """
    perdidos = tuple(minutos_perdidos)
    cursor = conexao.execute(
        """
        UPDATE sessao
        SET inicio = ?,
            fim = ?,
            duracao_real = ?,
            encerrada_pelo_usuario = ?,
            status = ?,
            minutos_perdidos_quantidade = ?,
            minutos_perdidos = ?
        WHERE id_sessao = ?
        """,
        (
            _serializa_instante(inicio),
            _serializa_instante(fim),
            duracao_real,
            int(encerrada_pelo_usuario),
            status.value,
            len(perdidos),
            json.dumps(list(perdidos)),
            id_sessao,
        ),
    )
    if cursor.rowcount == 0:
        conexao.rollback()
        raise SessaoInexistenteError(id_sessao)
    if comitar:
        conexao.commit()


def completar_processamento(
    conexao: sqlite3.Connection,
    id_sessao: str,
    *,
    versao_do_modelo: str,
    amostragem: int,
    limiar_de_confianca: float,
    comitar: bool = True,
) -> None:
    """Momento 3 de D-1: grava a configuração usada no processamento
    (AC-008.1: versão do modelo, taxa de amostragem e limiar de confiança).

    `comitar=False`: mesma regra de `abrir_sessao` e `fechar_captura`.
    """
    cursor = conexao.execute(
        """
        UPDATE sessao
        SET versao_do_modelo = ?,
            amostragem = ?,
            limiar_de_confianca = ?
        WHERE id_sessao = ?
        """,
        (versao_do_modelo, amostragem, limiar_de_confianca, id_sessao),
    )
    if cursor.rowcount == 0:
        conexao.rollback()
        raise SessaoInexistenteError(id_sessao)
    if comitar:
        conexao.commit()


def ler_sessao(conexao: sqlite3.Connection, id_sessao: str) -> SessaoGravada | None:
    """Lê a linha de `sessao`, ou `None` se ela não existir.

    É como os testes conferem o que foi gravado, e como T-09 (histórico) e a
    exportação (`exportacao-xlsx`) vão ler uma sessão única.
    """
    linha = conexao.execute(
        "SELECT * FROM sessao WHERE id_sessao = ?", (id_sessao,)
    ).fetchone()
    if linha is None:
        return None

    return SessaoGravada(
        id_sessao=linha["id_sessao"],
        id_camera=linha["id_camera"],
        nome_camera=linha["nome_camera"],
        criada_em=_desserializa_instante(linha["criada_em"]),
        inicio=_desserializa_instante(linha["inicio"]),
        fim=_desserializa_instante(linha["fim"]),
        duracao_pedida=linha["duracao_pedida"],
        duracao_real=linha["duracao_real"],
        encerrada_pelo_usuario=bool(linha["encerrada_pelo_usuario"]),
        status=(
            None if linha["status"] is None else StatusDaSessao(linha["status"])
        ),
        minutos_perdidos_quantidade=linha["minutos_perdidos_quantidade"],
        minutos_perdidos=tuple(json.loads(linha["minutos_perdidos"])),
        versao_do_modelo=linha["versao_do_modelo"],
        amostragem=linha["amostragem"],
        limiar_de_confianca=linha["limiar_de_confianca"],
        sentido_a=linha["sentido_a"],
        sentido_b=linha["sentido_b"],
    )


def listar_sessoes(
    conexao: sqlite3.Connection, limite: int | None = None
) -> tuple[SessaoNoHistorico, ...]:
    """O histórico de sessões, da mais recente para a mais antiga — US-009.

    `LEFT JOIN` com `COUNT`, e não uma subconsulta por sessão: é o que faz
    uma sessão sem evento nenhum aparecer com total **zero**, em vez de ficar
    de fora (AC-009.2). A consulta não lê `manifest.json` nem toca em vídeo
    nenhum (AC-009.1) — o total vem só do que já está no banco.

    Ordenado por `criada_em DESC`, não por `inicio`: `inicio` é nulo numa
    sessão que não capturou clipe nenhum, e nulo não tem lugar definido numa
    ordenação.

    `limite` fica de fora do SQL quando `None` — SUP-029 diz que sessão nunca
    expira, então sem limite a consulta devolve todas.
    """
    sql = """
        SELECT
            s.id_sessao AS id_sessao,
            s.id_camera AS id_camera,
            s.criada_em AS criada_em,
            s.inicio AS inicio,
            s.fim AS fim,
            s.status AS status,
            COUNT(e.id_sessao) AS total_de_eventos
        FROM sessao s
        LEFT JOIN evento e ON e.id_sessao = s.id_sessao
        GROUP BY s.id_sessao
        ORDER BY s.criada_em DESC
    """
    parametros: tuple = ()
    if limite is not None:
        sql += " LIMIT ?"
        parametros = (limite,)

    linhas = conexao.execute(sql, parametros).fetchall()

    return tuple(
        SessaoNoHistorico(
            id_sessao=linha["id_sessao"],
            id_camera=linha["id_camera"],
            criada_em=_desserializa_instante(linha["criada_em"]),
            inicio=_desserializa_instante(linha["inicio"]),
            fim=_desserializa_instante(linha["fim"]),
            status=(
                None if linha["status"] is None else StatusDaSessao(linha["status"])
            ),
            total_de_eventos=linha["total_de_eventos"],
        )
        for linha in linhas
    )


def _avisar_em_stderr(mensagem: str) -> None:
    """O padrão de `PersistenciaDaCaptura.aviso`: stderr, sem código de saída
    nenhum — a captura já está seguindo em frente."""
    print(mensagem, file=sys.stderr)


class PersistenciaDaCaptura:
    """Implementação concreta de `capture.session.Persistencia` (T-04).

    Liga os dois primeiros momentos de D-1 (`abrir_sessao`, `fechar_captura`)
    à captura de verdade. Os rótulos de sentido (D-6) vêm da câmera, que o
    CLI já resolveu antes de `capturar` ser chamado — e não do manifest, que
    não os conhece.

    Nenhuma falha de banco propaga: ela é só avisada (`aviso`, por padrão
    stderr) e a captura segue. É a mesma regra de `CLAUDE.md` que proíbe
    transformar falha de captura em exceção crua que derruba a execução —
    15 minutos perdidos não se recuperam, e o manifest continua sendo prova
    durável suficiente até o processamento regravar a sessão (D-7).
    """

    def __init__(
        self,
        conexao: sqlite3.Connection,
        *,
        camera: Camera,
        aviso: Callable[[str], None] | None = None,
    ) -> None:
        self._conexao = conexao
        self._camera = camera
        self._aviso = aviso or _avisar_em_stderr

    def sessao_aberta(
        self,
        *,
        id_sessao: str,
        id_camera: str,
        duracao_pedida: int,
        relogio_do_comando: datetime,
    ) -> None:
        try:
            abrir_sessao(
                self._conexao,
                id_sessao=id_sessao,
                id_camera=id_camera,
                criada_em=relogio_do_comando,
                duracao_pedida=duracao_pedida,
                sentido_a=self._camera.sentido_a,
                sentido_b=self._camera.sentido_b,
            )
        except Exception as falha:  # noqa: BLE001 — falha de banco não derruba a captura
            self._desfazer_transacao_pendente()
            self._aviso(
                f"aviso: não foi possível abrir o registro da sessão "
                f"{id_sessao} no banco: {falha}; a captura segue normalmente"
            )

    def captura_fechada(
        self,
        *,
        id_sessao: str,
        inicio: datetime | None,
        fim: datetime | None,
        duracao_real: int,
        encerrada_pelo_usuario: bool,
        status: StatusDaSessao,
        minutos_perdidos: tuple[int, ...],
    ) -> None:
        try:
            fechar_captura(
                self._conexao,
                id_sessao,
                inicio=inicio,
                fim=fim,
                duracao_real=duracao_real,
                encerrada_pelo_usuario=encerrada_pelo_usuario,
                status=status,
                minutos_perdidos=minutos_perdidos,
            )
        except Exception as falha:  # noqa: BLE001 — falha de banco não derruba a captura
            self._desfazer_transacao_pendente()
            self._aviso(
                f"aviso: não foi possível gravar o desfecho da sessão "
                f"{id_sessao} no banco: {falha}; o manifest é a prova "
                f"durável até o processamento regravar a sessão"
            )

    def _desfazer_transacao_pendente(self) -> None:
        """Deixa a conexão limpa depois de uma falha, para que uma segunda
        tentativa (ou outra chamada na mesma conexão) não herde uma
        transação pendente."""
        try:
            self._conexao.rollback()
        except Exception:  # noqa: BLE001 — a conexão pode já estar inválida
            pass

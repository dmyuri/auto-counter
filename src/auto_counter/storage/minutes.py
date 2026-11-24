"""Agregados por minuto: contagem, zero e sem dado — T-06.

Comportamento em `.spec/features/persistencia-resultados/spec.md`: AC-008.3 e
AC-008.4.

`agregar` é a regra, separada da gravação:

- a grade é **1..duração real** (D-4) — todo minuto do intervalo tem linha,
  nunca ausente da série (AC-008.3, literal);
- `CAPTURADO` quando o minuto está entre os **processados** do
  `eventos.json`; `SEM_DADO` em qualquer outro caso — o que é mais largo que
  "perdido na captura": um minuto que virou clipe mas não pôde ser lido
  também é `SEM_DADO`, porque reportá-lo como zero afirmaria que nenhum
  veículo passou, e ninguém olhou (AC-008.4);
- minuto `CAPTURADO` tem as oito contagens preenchidas, zero inclusive;
  minuto `SEM_DADO` tem as oito em `None` (SUP-035). O CHECK do schema (T-02)
  já recusa a mistura — esta função só não deve chegar lá errada.

As oito colunas são nomeadas pelos papéis `sentido_a` / `sentido_b` (D-6); a
tradução do rótulo do evento ("Icaraí") para o papel usa os dois rótulos
vigentes **daquela sessão**. Um evento com um terceiro sentido é erro
explícito: ou a câmera foi recalibrada entre a contagem e a persistência, ou
há um bug — e `CLAUDE.md` proíbe reaproveitar calibração de uma câmera em
outra, então isso é "pare e avise", não um valor a ignorar.
"""

import sqlite3
from collections import Counter
from collections.abc import Iterable, Sequence

from auto_counter.counting.events import Evento, MinutoNaoProcessado
from auto_counter.storage.model import AgregadoDoMinuto, EstadoDoMinuto
from auto_counter.storage.sessions import SessaoInexistenteError

_MOTIVO_PADRAO = (
    "o minuto não aparece no registro de processamento da sessão (nem como "
    "processado, nem como não processado)"
)
"""AC-008.4: minuto `SEM_DADO` nunca fica com motivo vazio."""

_CATEGORIAS = ("carro", "moto", "onibus", "caminhao")
"""Sufixo de coluna de cada categoria — o `.value` do enum em minúsculas."""


class SentidoDesconhecidoError(ValueError):
    """O sentido de um evento não é nenhum dos dois rótulos vigentes.

    Sinal de recalibração da câmera entre a contagem e a persistência, ou de
    bug em quem produziu o evento — nos dois casos, `CLAUDE.md` manda parar e
    avisar, não adivinhar qual papel o rótulo deveria ter.
    """

    def __init__(self, sentido_do_evento: str, *, sentido_a: str, sentido_b: str) -> None:
        self.sentido_do_evento = sentido_do_evento
        super().__init__(
            f"o evento tem sentido '{sentido_do_evento}', que não é nenhum dos "
            f"dois rótulos vigentes da câmera nesta sessão ('{sentido_a}' ou "
            f"'{sentido_b}'); isso sugere recalibração da câmera entre a "
            f"contagem e a persistência — pare e avise, não reaproveite "
            f"calibração de uma câmera em outra (CLAUDE.md)"
        )


def _papel(sentido_do_evento: str, *, sentido_a: str, sentido_b: str) -> str:
    """Traduz o rótulo do evento para o papel da coluna (D-6)."""
    if sentido_do_evento == sentido_a:
        return "sentido_a"
    if sentido_do_evento == sentido_b:
        return "sentido_b"
    raise SentidoDesconhecidoError(
        sentido_do_evento, sentido_a=sentido_a, sentido_b=sentido_b
    )


def agregar(
    eventos: Iterable[Evento],
    *,
    duracao_real: int,
    minutos_processados: Sequence[int],
    minutos_nao_processados: Sequence[MinutoNaoProcessado],
    sentido_a: str,
    sentido_b: str,
) -> tuple[AgregadoDoMinuto, ...]:
    """Calcula a grade de agregados de 1 a `duracao_real` (D-4)."""
    processados = set(minutos_processados)
    motivo_por_minuto = {item.minuto: item.motivo for item in minutos_nao_processados}

    contagem_por_minuto: dict[int, Counter[tuple[str, str]]] = {}
    for evento in eventos:
        papel = _papel(evento.sentido, sentido_a=sentido_a, sentido_b=sentido_b)
        chave = (papel, evento.categoria.value.lower())
        contagem_por_minuto.setdefault(evento.minuto, Counter())[chave] += 1

    agregados = []
    for minuto in range(1, duracao_real + 1):
        if minuto in processados:
            contagens = contagem_por_minuto.get(minuto, Counter())
            agregados.append(
                AgregadoDoMinuto(
                    minuto=minuto,
                    estado=EstadoDoMinuto.CAPTURADO,
                    motivo=None,
                    **{
                        f"{papel}_{categoria}": contagens[(papel, categoria)]
                        for papel in ("sentido_a", "sentido_b")
                        for categoria in _CATEGORIAS
                    },
                )
            )
        else:
            agregados.append(
                AgregadoDoMinuto(
                    minuto=minuto,
                    estado=EstadoDoMinuto.SEM_DADO,
                    motivo=motivo_por_minuto.get(minuto, _MOTIVO_PADRAO),
                    sentido_a_carro=None,
                    sentido_a_moto=None,
                    sentido_a_onibus=None,
                    sentido_a_caminhao=None,
                    sentido_b_carro=None,
                    sentido_b_moto=None,
                    sentido_b_onibus=None,
                    sentido_b_caminhao=None,
                )
            )

    return tuple(agregados)


_COLUNAS_DE_CONTAGEM = (
    "sentido_a_carro",
    "sentido_a_moto",
    "sentido_a_onibus",
    "sentido_a_caminhao",
    "sentido_b_carro",
    "sentido_b_moto",
    "sentido_b_onibus",
    "sentido_b_caminhao",
)


def gravar_agregados(
    conexao: sqlite3.Connection,
    id_sessao: str,
    agregados: Iterable[AgregadoDoMinuto],
) -> None:
    """Grava a grade de agregados de uma sessão (AC-008.3 e AC-008.4).

    `ON CONFLICT (id_sessao, minuto) DO UPDATE`: regravar a mesma sessão
    produz o mesmo conteúdo (AC-008.5), em vez de erro de integridade. Não dá
    `commit` — quem controla a transação é `persistir_sessao` (T-07).
    """
    linhas = [
        (
            id_sessao,
            agregado.minuto,
            agregado.estado.value,
            agregado.motivo,
            *(getattr(agregado, coluna) for coluna in _COLUNAS_DE_CONTAGEM),
        )
        for agregado in agregados
    ]
    if not linhas:
        return

    colunas_contagem_sql = ", ".join(_COLUNAS_DE_CONTAGEM)
    marcadores_contagem = ", ".join("?" for _ in _COLUNAS_DE_CONTAGEM)
    atualizacoes_contagem = ", ".join(
        f"{coluna} = excluded.{coluna}" for coluna in _COLUNAS_DE_CONTAGEM
    )

    try:
        conexao.executemany(
            f"""
            INSERT INTO minuto
                (id_sessao, minuto, estado, motivo, {colunas_contagem_sql})
            VALUES (?, ?, ?, ?, {marcadores_contagem})
            ON CONFLICT (id_sessao, minuto) DO UPDATE SET
                estado = excluded.estado,
                motivo = excluded.motivo,
                {atualizacoes_contagem}
            """,
            linhas,
        )
    except sqlite3.IntegrityError as falha:
        raise SessaoInexistenteError(id_sessao) from falha


def ler_agregados(
    conexao: sqlite3.Connection, id_sessao: str
) -> tuple[AgregadoDoMinuto, ...]:
    """Lê a grade de agregados de uma sessão, em ordem de minuto.

    Para os testes de AC-008.5 e para a exportação (`exportacao-xlsx`), que lê
    apenas o banco.
    """
    linhas = conexao.execute(
        "SELECT * FROM minuto WHERE id_sessao = ? ORDER BY minuto", (id_sessao,)
    ).fetchall()

    return tuple(
        AgregadoDoMinuto(
            minuto=linha["minuto"],
            estado=EstadoDoMinuto(linha["estado"]),
            motivo=linha["motivo"],
            **{coluna: linha[coluna] for coluna in _COLUNAS_DE_CONTAGEM},
        )
        for linha in linhas
    )

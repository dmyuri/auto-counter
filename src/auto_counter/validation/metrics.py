"""Métricas do clipe: erro por sentido, acerto de categoria e matriz (AC-014.1,
AC-014.2 e AC-015.1).

Só funções puras. Nenhum percentual em float: a fração exata é o que o
veredito compara (D-8).
"""

from collections.abc import Iterable
from fractions import Fraction

from auto_counter.counting.config import Categoria
from auto_counter.validation.model import (
    AcertoDeCategoria,
    ErroDoSentido,
    MatrizDeConfusao,
    MedicaoDoClipe,
    Pareamento,
    VeiculoAutomatico,
    VeiculoManual,
)
from auto_counter.validation.pairing import parear


def erro_por_sentido(
    manuais: Iterable[VeiculoManual],
    automaticos: Iterable[VeiculoAutomatico],
    *,
    rotulos: tuple[str, str],
) -> tuple[ErroDoSentido, ErroDoSentido]:
    """Um `ErroDoSentido` para cada um dos dois rótulos, sempre.

    Os totais contam todos os veículos, pareados ou não. Manual 0 e
    automático 0 é erro 0; manual 0 e automático > 0 é indefinido (D-2).
    """
    manuais = tuple(manuais)
    automaticos = tuple(automaticos)

    def do_sentido(rotulo: str) -> ErroDoSentido:
        manual = sum(1 for v in manuais if v.sentido == rotulo)
        automatico = sum(1 for v in automaticos if v.sentido == rotulo)
        if manual == 0:
            erro = Fraction(0) if automatico == 0 else None
        else:
            erro = Fraction(abs(automatico - manual), manual)
        return ErroDoSentido(
            sentido=rotulo, manual=manual, automatico=automatico, erro=erro
        )

    return do_sentido(rotulos[0]), do_sentido(rotulos[1])


def acerto_de_categoria(pareamento: Pareamento) -> AcertoDeCategoria:
    """Fração dos pares com a mesma categoria, os dois sentidos juntos."""
    pares = len(pareamento.pares)
    acertos = sum(
        1 for p in pareamento.pares if p.manual.categoria == p.automatico.categoria
    )
    fracao = None if pares == 0 else Fraction(acertos, pares)
    return AcertoDeCategoria(pares=pares, acertos=acertos, fracao=fracao)


def matriz_de_confusao(pareamento: Pareamento) -> MatrizDeConfusao:
    """Linhas = categoria manual, colunas = automática, na ordem do enum."""
    categorias = list(Categoria)
    celulas = [[0] * len(categorias) for _ in categorias]
    for par in pareamento.pares:
        celulas[categorias.index(par.manual.categoria)][
            categorias.index(par.automatico.categoria)
        ] += 1
    return MatrizDeConfusao(linhas=tuple(tuple(linha) for linha in celulas))


def medir_clipe(
    manuais: Iterable[VeiculoManual],
    automaticos: Iterable[VeiculoAutomatico],
    *,
    rotulos: tuple[str, str],
) -> MedicaoDoClipe:
    manuais = tuple(manuais)
    automaticos = tuple(automaticos)
    pareamento = parear(manuais, automaticos)
    return MedicaoDoClipe(
        erros=erro_por_sentido(manuais, automaticos, rotulos=rotulos),
        acerto=acerto_de_categoria(pareamento),
        matriz=matriz_de_confusao(pareamento),
        pareamento=pareamento,
    )

"""Veredito por clipe e do conjunto (AC-014.4 e a regra de decisão do gate).

A meta vale por clipe (Q-007): não existe média entre clipes em nenhum ponto.
"""

from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal

from auto_counter.validation.model import (
    Condicao,
    MedicaoDoClipe,
    VereditoDoClipe,
    VereditoDoConjunto,
    Violacao,
)

# Origem: §Contexto, AC-014.3 e Q-007 da spec `validacao-acuracia`. A meta foi
# fixada antes de qualquer medição. Mudar o número para caber no resultado é
# proibido (CLAUDE.md): se a validação real reprovar, quem muda é o sistema, por
# revisão de spec de `contagem-veiculos`. Inteiros, para a comparação ser exata.
ERRO_MAXIMO_PERCENTUAL = 10
ACERTO_MINIMO_PERCENTUAL = 80

_METRICA_ERRO = "erro de contagem"
_METRICA_ACERTO = "acerto de categoria"


def veredito_do_clipe(condicao: Condicao, medicao: MedicaoDoClipe) -> VereditoDoClipe:
    """Compara as medições de um clipe com os limites, em aritmética exata (D-8).

    Erro: violação se |auto − manual| × 100 > 10 × manual. Acerto: violação se
    acertos × 100 < 80 × pares. Métrica indefinida é violação (D-2).
    """
    violacoes: list[Violacao] = []

    for erro in medicao.erros:
        diferenca = abs(erro.automatico - erro.manual)
        if erro.erro is None:
            violada = True
        else:
            violada = diferenca * 100 > ERRO_MAXIMO_PERCENTUAL * erro.manual
        if violada:
            violacoes.append(
                Violacao(
                    condicao=condicao,
                    metrica=_METRICA_ERRO,
                    sentido=erro.sentido,
                    valor=erro.erro,
                    numerador=diferenca,
                    denominador=erro.manual,
                    limite=ERRO_MAXIMO_PERCENTUAL,
                )
            )

    acerto = medicao.acerto
    if acerto.fracao is None or acerto.acertos * 100 < ACERTO_MINIMO_PERCENTUAL * acerto.pares:
        violacoes.append(
            Violacao(
                condicao=condicao,
                metrica=_METRICA_ACERTO,
                sentido=None,
                valor=acerto.fracao,
                numerador=acerto.acertos,
                denominador=acerto.pares,
                limite=ACERTO_MINIMO_PERCENTUAL,
            )
        )

    return VereditoDoClipe(
        condicao=condicao, passou=not violacoes, violacoes=tuple(violacoes)
    )


def veredito_do_conjunto(vereditos: Iterable[VereditoDoClipe]) -> VereditoDoConjunto:
    """Passa se, e somente se, os três clipes obrigatórios foram medidos e
    cada um passou. A chuva é ignorada no veredito. Obrigatório faltando é
    reprovação, nunca aprovação por omissão.
    """
    ordem = list(Condicao)
    clipes = tuple(sorted(vereditos, key=lambda v: ordem.index(v.condicao)))
    obrigatorios = [v for v in clipes if v.condicao.obrigatoria]

    medidas = {v.condicao for v in obrigatorios}
    ausentes = tuple(c for c in Condicao if c.obrigatoria and c not in medidas)
    violacoes = tuple(violacao for v in obrigatorios for violacao in v.violacoes)

    return VereditoDoConjunto(
        passou=not ausentes and not violacoes,
        clipes=clipes,
        violacoes=violacoes,
        ausentes=ausentes,
    )


def _percentual(numerador: int, denominador: int) -> str:
    valor = Decimal(numerador * 100) / Decimal(denominador)
    return f"{valor.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}%"


def _linha(violacao: Violacao) -> str:
    comparador = "≤" if violacao.metrica == _METRICA_ERRO else "≥"
    limite = f"limite {comparador} {violacao.limite}%"
    clipe = f"clipe {violacao.condicao.value}: {violacao.metrica}"

    if violacao.metrica == _METRICA_ERRO:
        clipe += f" no sentido {violacao.sentido}"
        if violacao.valor is None:
            medido = (
                f"indefinido (manual {violacao.denominador}, "
                f"automático {violacao.numerador})"
            )
        else:
            medido = (
                f"{_percentual(violacao.numerador, violacao.denominador)} "
                f"({violacao.numerador}/{violacao.denominador})"
            )
    elif violacao.valor is None:
        medido = f"indefinido ({violacao.denominador} pares)"
    else:
        medido = (
            f"{_percentual(violacao.numerador, violacao.denominador)} "
            f"({violacao.numerador}/{violacao.denominador})"
        )
    return f"  - {clipe} = {medido}; {limite}"


def mensagem_de_falha(veredito: VereditoDoConjunto) -> str:
    """Uma linha por violação, com clipe, métrica, valor e limite (AC-014.4).

    Devolve texto vazio quando o conjunto passou.
    """
    if veredito.passou:
        return ""
    linhas = ["validação reprovada:"]
    linhas.extend(_linha(violacao) for violacao in veredito.violacoes)
    linhas.extend(
        f"  - clipe {condicao.value}: não medido; a validação exige os três "
        f"clipes obrigatórios"
        for condicao in veredito.ausentes
    )
    return "\n".join(linhas)

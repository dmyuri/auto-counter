"""Pareamento entre veículo manual e automático (AC-014.2).

Regra de SUP-046 e D-7 da feature `validacao-acuracia`: por sentido, janela de
2 s no instante do cruzamento, cada veículo em no máximo um par. A categoria
não participa: se participasse, o pareamento escolheria o par de mesma
categoria e inflaria o acerto de AC-014.2.
"""

from collections.abc import Iterable
from decimal import Decimal

from auto_counter.validation.model import (
    Par,
    Pareamento,
    VeiculoAutomatico,
    VeiculoManual,
)

# SUP-046: janela de 2 s, inclusive. Não muda para acomodar um resultado.
JANELA_DE_PAREAMENTO_EM_SEGUNDOS = Decimal("2")


def parear(
    manuais: Iterable[VeiculoManual], automaticos: Iterable[VeiculoAutomatico]
) -> Pareamento:
    """Casa manuais e automáticos de forma gulosa pelo menor |Δt|.

    Candidato: mesmo sentido e |Δt| <= janela. Os candidatos são tomados em
    ordem crescente de |Δt|, com desempate por instante manual, linha do CSV,
    instante automático e id de rastreio. Função pura e determinística: a
    ordem de entrada não altera o resultado.
    """
    manuais = tuple(manuais)
    automaticos = tuple(automaticos)

    candidatos = [
        (abs(a.instante_s - m.instante_s), m, a)
        for m in manuais
        for a in automaticos
        if m.sentido == a.sentido
        and abs(a.instante_s - m.instante_s) <= JANELA_DE_PAREAMENTO_EM_SEGUNDOS
    ]
    candidatos.sort(
        key=lambda c: (
            c[0],
            c[1].instante_s,
            c[1].linha,
            c[2].instante_s,
            c[2].id_de_rastreio,
            c[2].categoria.value,
        )
    )

    manuais_usados: set[int] = set()
    automaticos_usados: set[int] = set()
    pares: list[Par] = []
    for _, manual, automatico in candidatos:
        if id(manual) in manuais_usados or id(automatico) in automaticos_usados:
            continue
        manuais_usados.add(id(manual))
        automaticos_usados.add(id(automatico))
        pares.append(
            Par(
                manual=manual,
                automatico=automatico,
                delta_s=automatico.instante_s - manual.instante_s,
            )
        )

    pares.sort(key=lambda p: (p.manual.instante_s, p.manual.linha))
    manuais_sem_par = sorted(
        (m for m in manuais if id(m) not in manuais_usados),
        key=lambda m: (m.instante_s, m.linha),
    )
    automaticos_sem_par = sorted(
        (a for a in automaticos if id(a) not in automaticos_usados),
        key=lambda a: (a.instante_s, a.id_de_rastreio, a.sentido, a.categoria.value),
    )
    return Pareamento(
        pares=tuple(pares),
        manuais_sem_par=tuple(manuais_sem_par),
        automaticos_sem_par=tuple(automaticos_sem_par),
    )

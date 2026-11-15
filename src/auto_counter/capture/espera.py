"""Espera que olha o pedido de parada enquanto o tempo passa.

As esperas da captura são longas: 10 s entre checagens (SUP-008) e 3 s ou 8 s
entre tentativas de download (AC-004.1). Dormidas de uma vez, elas seguravam o
pedido de parada da interface (AC-012.7 de `interface-sessao`) até acordar.
Fatiada, a espera devolve o controle em menos de um segundo depois do pedido.

Sem quem possa pedir a parada (`None`), a espera é feita de uma vez, como
sempre foi.
"""

from collections.abc import Callable
from typing import Protocol

FATIA_DA_ESPERA = 0.5
"""Segundos de cada pedaço da espera: o atraso máximo para notar a parada."""


class ComParada(Protocol):
    """Qualquer objeto que diga se a parada foi pedida."""

    def foi_pedida(self) -> bool: ...


def esperar(
    segundos: float,
    *,
    dormir: Callable[[float], None],
    parada: ComParada | None,
) -> bool:
    """Espera `segundos` em pedaços curtos. Devolve se a parada foi pedida.

    A parada é olhada antes de cada pedaço; pedida, a espera para ali e o
    restante não é dormido.
    """
    if parada is None:
        dormir(segundos)
        return False
    restante = segundos
    while restante > 0:
        if parada.foi_pedida():
            return True
        pedaco = min(FATIA_DA_ESPERA, restante)
        dormir(pedaco)
        restante -= pedaco
    return parada.foi_pedida()

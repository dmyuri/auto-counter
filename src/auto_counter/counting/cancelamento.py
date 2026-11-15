"""Cancelamento do processamento a pedido do usuário — AC-012.5.

Fica fora de `session.py` porque o pedido de parada é consultado em dois níveis:
entre os clipes (`processar_sessao`) e dentro de cada clipe (`processar_clipe`,
SUP-108). `session.py` importa `clip.py`, então a exceção e o protocolo não
poderiam viver lá sem um ciclo de importação. `counting.session` os reexporta,
e quem já importava de lá continua funcionando.

Nada aqui importa `httpx`: o processamento não pode depender da captura.
"""

from typing import Protocol


class ProcessamentoCancelado(RuntimeError):
    """O usuário encerrou a sessão durante o processamento (AC-012.5).

    Erro explícito, e não resultado parcial: o que foi contado até aqui não é a
    contagem da sessão e não pode ser lido como se fosse.
    """


class ParadaDoProcessamento(Protocol):
    """Qualquer objeto que diga se o usuário pediu para encerrar.

    Declarado aqui, e não importado de `capture.session`, para que o
    processamento não passe a depender de `httpx`.
    """

    def foi_pedida(self) -> bool: ...

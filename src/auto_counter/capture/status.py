"""Vocabulário de status da sessão e a regra dos 20%.

Comportamento definido em `.spec/features/captura-clipes/spec.md`: AC-004.4,
AC-004.5 e AC-004.6.

São exatamente três status — `COMPLETA`, `DEGRADADA` e `INVALIDA` — e o
§Contexto da spec exige que esse mesmo vocabulário valha no banco, na interface
e no XLSX. O encerramento pelo usuário **não** cria um quarto: Q-003 decidiu
que ele é um campo à parte da sessão (AC-003.6), não um status.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum


class StatusDaSessao(Enum):
    """Os três status possíveis de uma sessão, e nenhum outro.

    O valor de cada membro é o próprio nome porque é assim que ele aparece na
    interface e no XLSX (§Contexto): serializar o status é escrever `.value`,
    sem tabela de tradução no meio.
    """

    COMPLETA = "COMPLETA"
    DEGRADADA = "DEGRADADA"
    INVALIDA = "INVALIDA"


@dataclass(frozen=True)
class ResultadoDoStatus:
    """O status e a lista de minutos perdidos que o justifica.

    AC-004.5 e AC-004.6 exigem que a lista fique registrada, então ela viaja
    junto do status em vez de ser recalculada depois. A gravação em disco é do
    manifest (T-06); aqui a lista só é carregada.
    """

    status: StatusDaSessao
    minutos_perdidos: tuple[int, ...]


def classificar(base: int, minutos_perdidos: Sequence[int]) -> ResultadoDoStatus:
    """Classifica a sessão a partir do denominador e dos minutos perdidos.

    - nenhum minuto perdido → `COMPLETA` (AC-004.4);
    - pelo menos um e no máximo 20% de `base` → `DEGRADADA` (AC-004.5);
    - mais de 20% de `base` → `INVALIDA` (AC-004.6).

    `base` é o denominador e chega **por parâmetro** (SUP-013). Esta função não
    conhece interrupção: quem decide se o denominador é o N pedido ou a duração
    real de uma sessão encerrada pelo usuário (AC-003.6) é o laço de captura.
    Embutir essa escolha aqui misturaria duas regras que a spec separa.

    A fronteira é comparada em aritmética inteira — `perdidos * 5 <= base` —
    porque AC-004.5 é "no máximo 20%" (inclusive) e AC-004.6 é "mais de 20%":
    com `perdidos / base <= 0.2` o arredondamento binário decidiria a fronteira
    exata, e ela é justamente onde os dois critérios se encostam.

    `base` menor que 1 é erro de programação, não status: uma sessão sem
    denominador não tem percentual, e inventar um status para ela esconderia o
    bug de quem chamou.
    """
    if base < 1:
        raise ValueError(
            f"a base do cálculo de status precisa ser de pelo menos 1 minuto, "
            f"e não {base}; ela é o N pedido, ou a duração real quando o "
            f"usuário encerra a sessão (SUP-013)"
        )

    perdidos = tuple(minutos_perdidos)

    if not perdidos:
        return ResultadoDoStatus(StatusDaSessao.COMPLETA, perdidos)

    if len(perdidos) * 5 <= base:
        return ResultadoDoStatus(StatusDaSessao.DEGRADADA, perdidos)

    return ResultadoDoStatus(StatusDaSessao.INVALIDA, perdidos)

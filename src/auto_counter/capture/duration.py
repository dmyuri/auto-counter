"""Validação da duração pedida para a sessão de captura.

Comportamento em `.spec/features/captura-clipes/spec.md`: AC-003.3 — duração
fora do intervalo de 1 a 15 minutos é rejeitada com erro que cita o limite,
antes de qualquer requisição ao servidor.

Este módulo é puro de propósito: não importa cliente HTTP, não lê variável de
ambiente e não abre socket. É assim que o "antes de qualquer requisição" de
AC-003.3 fica garantido por construção, e não por ordem de chamada que alguém
pode inverter depois.
"""

DURACAO_MINIMA = 1
"""Menor duração aceita, em minutos (AC-003.3)."""

DURACAO_MAXIMA = 15
"""Maior duração aceita, em minutos (AC-003.3).

O teto vem da spec, não do disco: uma sessão de 15 minutos ocupa ~480 MB
enquanto dura (§Contexto).
"""


class DuracaoForaDoIntervaloError(Exception):
    """A duração pedida não está em 1..15 minutos (AC-003.3).

    A mensagem cita os dois limites e o valor recebido: quem digitou 60 precisa
    ler qual é o teto, não só que errou.
    """


def validar_duracao(minutos: int) -> int:
    """Devolve a duração se ela estiver em 1..15 minutos; senão levanta erro.

    Ordem de chamada, tanto no laço de captura (T-07) quanto no CLI (T-10):
    **valida primeiro, constrói o cliente HTTP depois**. AC-003.3 exige que a
    rejeição aconteça antes de qualquer requisição ao servidor, e a validação
    só cumpre isso se nada de rede tiver sido montado até aqui.

    Valor não inteiro cai no mesmo erro: o intervalo é de minutos inteiros, e
    `bool` é rejeitado explicitamente porque, sendo subclasse de `int`, `True`
    passaria por uma duração de 1 minuto.
    """
    if isinstance(minutos, bool) or not isinstance(minutos, int):
        raise DuracaoForaDoIntervaloError(
            f"a duração da captura precisa ser um número inteiro de minutos "
            f"entre {DURACAO_MINIMA} e {DURACAO_MAXIMA}, e não {minutos!r}"
        )

    if not DURACAO_MINIMA <= minutos <= DURACAO_MAXIMA:
        raise DuracaoForaDoIntervaloError(
            f"a duração da captura precisa estar entre {DURACAO_MINIMA} e "
            f"{DURACAO_MAXIMA} minutos, e não {minutos}"
        )

    return minutos

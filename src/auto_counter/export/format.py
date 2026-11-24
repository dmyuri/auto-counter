"""Nome do arquivo, conversão de fuso e linha de aviso — T-06.

Comportamento em `.spec/features/exportacao-xlsx/spec.md`: AC-010.1 e AC-010.5
(nome do arquivo e aviso), SUP-032 (padrão do nome) e SUP-033 (horário de
Brasília). Funções puras: sem `openpyxl` e sem banco.

Por `processamento-upload` (AC-030.3, AC-030.4, D-10), a sessão de upload leva
`_upload` antes do sufixo de status no nome, e o aviso fala em minutos sem dado
por falha de leitura. O nome e o aviso da sessão ao vivo não mudam.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from auto_counter.capture.status import StatusDaSessao
from auto_counter.storage.model import OrigemDaSessao, SessaoGravada

FUSO = ZoneInfo("America/Sao_Paulo")
"""D-9: fuso IANA, e não offset fixo de -03:00."""


def para_brasilia(instante: datetime) -> datetime:
    """Converte para o horário de Brasília e devolve **sem** `tzinfo`.

    O Excel não aceita `datetime` com fuso (D-9). Sem `tzinfo` na entrada não
    há como saber o fuso, e assumir seria inventar hora — mesma recusa de
    `storage/sessions.py`.
    """
    if instante.tzinfo is None:
        raise ValueError(
            f"instante sem fuso horário ({instante!r}); a conversão para o "
            f"horário de Brasília exige fuso explícito, e um datetime ingênuo "
            f"não diz qual é o dele"
        )
    return instante.astimezone(FUSO).replace(tzinfo=None)


def percentual_perdido(sessao: SessaoGravada) -> float:
    """Minutos perdidos na captura sobre a duração real (D-5, SUP-013)."""
    if not sessao.duracao_real:
        raise ValueError(
            f"a sessão '{sessao.id_sessao}' não tem duração real; sem ela não "
            f"há percentual de minutos perdidos"
        )
    return len(sessao.minutos_perdidos) / sessao.duracao_real * 100


def linha_de_aviso(sessao: SessaoGravada) -> str | None:
    """O aviso de AC-010.5 (D-10), ou `None` para sessão COMPLETA."""
    if sessao.status in (None, StatusDaSessao.COMPLETA):
        return None
    percentual = f"{percentual_perdido(sessao):.1f}".replace(".", ",")
    if sessao.origem is OrigemDaSessao.UPLOAD:
        return (
            f"ATENÇÃO: sessão {sessao.status.value} — "
            f"{len(sessao.minutos_perdidos)} de {sessao.duracao_real} minutos "
            f"sem dado por falha de leitura ({percentual}%)"
        )
    return (
        f"ATENÇÃO: sessão {sessao.status.value} — "
        f"{len(sessao.minutos_perdidos)} de {sessao.duracao_real} minutos "
        f"perdidos na captura ({percentual}%)"
    )


def nome_do_arquivo(sessao: SessaoGravada) -> str:
    """`<id_camera>_<AAAAMMDD>_<HHMM>_<N>min[_<STATUS>].xlsx` (SUP-032).

    Data e hora vêm de `inicio` em horário de Brasília (D-8) e `N` é a
    duração real (D-4).
    """
    if sessao.inicio is None or sessao.duracao_real is None:
        raise ValueError(
            f"a sessão '{sessao.id_sessao}' não tem início ou duração real; "
            f"o nome do arquivo não pode ser montado"
        )
    inicio = para_brasilia(sessao.inicio)
    nome = (
        f"{sessao.id_camera}_{inicio:%Y%m%d}_{inicio:%H%M}_"
        f"{sessao.duracao_real}min"
    )
    if sessao.origem is OrigemDaSessao.UPLOAD:
        nome += "_upload"
    if sessao.status is not StatusDaSessao.COMPLETA:
        nome += f"_{sessao.status.value}"
    return f"{nome}.xlsx"

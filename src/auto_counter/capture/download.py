"""Download do clipe, com até 3 tentativas dentro da janela do minuto.

Comportamento em `.spec/features/captura-clipes/spec.md`: AC-004.1 — falha por
erro de rede, timeout ou resposta HTTP de erro é repetida até 3 tentativas com
espera crescente **dentro da janela daquele minuto**, e só depois o minuto é
marcado como não capturado.

Esta função não conhece minuto: ela baixa um arquivo ou levanta
`DownloadFalhouError`. Quem traduz o erro em "minuto não capturado", registra o
motivo no manifest e segue para o minuto seguinte é o laço de captura (T-07).

SUP-008 fixa a janela de 90 s e exige que as 3 tentativas caibam nela. Os
valores concretos do backoff **não** estão na spec: estão fixados aqui, por
T-04 do `_tasks.md`, e é neste módulo que se mudam.

`dormir` e `agora` entram por parâmetro (D-7), assim como o `httpx.Client`:
nenhum teste deste projeto espera o relógio real nem toca o servidor da
NitTrans. A URL chega pronta de `auto_counter.cameras.url.url_do_clipe`.
"""

from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

import httpx

TENTATIVAS_MAXIMAS = 3
"""Quantas tentativas de download um mesmo clipe recebe (AC-004.1)."""

ESPERAS_ENTRE_TENTATIVAS: tuple[float, ...] = (3.0, 8.0)
"""Segundos de espera antes da 2ª e da 3ª tentativa — a espera é crescente.

Valores fixados por T-04, não pela spec. Com o timeout de 20 s por tentativa, o
pior caso é 20 + 3 + 20 + 8 + 20 = 71 s, dentro dos 90 s da janela (SUP-008).
"""

TEMPO_LIMITE_POR_TENTATIVA = 20.0
"""Segundos que uma tentativa pode gastar antes de virar timeout.

Folgado para os ~32 MB de um clipe (§Contexto) e curto o bastante para que as
três tentativas mais as esperas caibam na janela de 90 s.
"""


class DownloadFalhouError(Exception):
    """O clipe não foi baixado nesta janela (AC-004.1).

    Um único tipo para os dois desfechos — tentativas esgotadas e prazo da
    janela vencido — porque para o chamador o resultado é o mesmo: não há
    arquivo. Qual dos dois foi, o que falhou e quantas tentativas houve estão
    na mensagem.
    """


def _descarta_parcial(destino: Path) -> None:
    """Apaga o arquivo da tentativa que falhou, se ele chegou a existir.

    O destino nunca pode ficar com bytes de duas tentativas, e um `.mp4`
    truncado no diretório da sessão passaria por material capturado.
    """
    try:
        destino.unlink()
    except OSError:
        pass


def _uma_tentativa(cliente: httpx.Client, url: str, destino: Path) -> None:
    """GET único, gravando o corpo direto no destino. Erro sobe para o laço."""
    try:
        with cliente.stream(
            "GET", url, follow_redirects=True, timeout=TEMPO_LIMITE_POR_TENTATIVA
        ) as resposta:
            resposta.raise_for_status()
            with destino.open("wb") as arquivo:
                for pedaco in resposta.iter_bytes():
                    arquivo.write(pedaco)
    except BaseException:
        _descarta_parcial(destino)
        raise


def baixar(
    cliente: httpx.Client,
    url: str,
    destino: str | Path,
    *,
    prazo: datetime,
    dormir: Callable[[float], None],
    agora: Callable[[], datetime],
) -> Path:
    """Baixa o clipe para `destino`, repetindo até 3 vezes dentro da janela.

    `prazo` é o fim da janela daquele minuto e **tem precedência sobre a
    contagem de tentativas**: se a espera mais a tentativa seguinte fossem
    atravessar o prazo, o download desiste ali. Sem isso, um ETag que só muda no
    segundo 80 daria retry passando por cima da janela de 90 s (SUP-008), e o
    minuto seguinte começaria atrasado.

    A primeira tentativa só é barrada pelo prazo já vencido: dentro da janela
    ela sempre acontece, porque desistir de tentar seria perder o clipe de vez —
    a URL não tem histórico.

    Devolve o caminho gravado. Esgotadas as tentativas, ou vencido o prazo,
    levanta `DownloadFalhouError` dizendo o que falhou e quantas tentativas
    houve. Nenhuma exceção de rede ou de disco escapa crua (`CLAUDE.md`).
    """
    destino = Path(destino)
    ultima_falha = "nenhuma tentativa chegou a acontecer"
    tentativas_feitas = 0

    for tentativa in range(1, TENTATIVAS_MAXIMAS + 1):
        if tentativa == 1:
            if agora() >= prazo:
                raise DownloadFalhouError(
                    f"o prazo da janela do clipe venceu antes da primeira "
                    f"tentativa de baixar {url}"
                )
        else:
            espera = ESPERAS_ENTRE_TENTATIVAS[tentativa - 2]
            proximo_fim = agora() + timedelta(
                seconds=espera + TEMPO_LIMITE_POR_TENTATIVA
            )
            if proximo_fim > prazo:
                raise DownloadFalhouError(
                    f"o prazo da janela do clipe não comporta a tentativa "
                    f"{tentativa} de baixar {url}; houve {tentativas_feitas} "
                    f"tentativa(s), e a última falhou assim: {ultima_falha}"
                )
            dormir(espera)

        tentativas_feitas = tentativa
        try:
            _uma_tentativa(cliente, url, destino)
        except httpx.HTTPStatusError as erro:
            ultima_falha = f"o servidor respondeu {erro.response.status_code}"
        except httpx.HTTPError as erro:
            ultima_falha = f"falha de rede ou timeout ({erro})"
        except OSError as erro:
            ultima_falha = f"falha ao gravar o clipe em disco ({erro})"
        else:
            return destino

    raise DownloadFalhouError(
        f"não foi possível baixar {url} em {tentativas_feitas} tentativas; "
        f"a última falhou assim: {ultima_falha}"
    )

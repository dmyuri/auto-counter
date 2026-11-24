"""Checagem de clipe novo por HEAD, pelo ETag e pelo Last-Modified.

Comportamento em `.spec/features/captura-clipes/spec.md`: AC-003.2 — com o
mesmo ETag da checagem anterior o conteúdo **não** é baixado de novo e o
sistema aguarda a próxima checagem.

Implementa SUP-008 (checagem por requisição HEAD; clipe novo é ETag que mudou)
e SUP-009 (a identidade do clipe é o ETag e sua referência de tempo é o
Last-Modified do servidor — o relógio local é gravado à parte, apenas como
informação de diagnóstico, e nada do tempo da sessão sai dele).

Nada aqui baixa vídeo: este módulo só pergunta ao servidor se há clipe novo. O
download com retry é de `capture.download` (AC-004.1).

Conforme D-4 do `_tasks.md` de `captura-clipes`, uma checagem sem ETag, sem
Last-Modified, com Last-Modified que não parseia ou com HTTP 4xx não produz
clipe identificável: `checar` devolve `None`, o chamador aguarda a próxima
checagem e, se a janela de 90 s se esgotar assim, o minuto é marcado como não
capturado (AC-004.2). Erro de conexão, DNS, rede, timeout e HTTP 500 a 599 têm
desfecho próprio, `FalhaDeServidor` (AC-033.1). **Nenhuma exceção crua sai
deste módulo** (`CLAUDE.md`).

O `httpx.Client` e o relógio entram por parâmetro (D-7): nenhum teste deste
projeto toca o servidor da NitTrans nem espera o relógio real. A URL vem de
`auto_counter.cameras.url.url_do_clipe`, que já prova AC-001.4 e AC-001.5 —
este módulo recebe a URL pronta e não a remonta.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx


@dataclass(frozen=True)
class Checagem:
    """O que uma checagem HEAD bem-sucedida apurou sobre o clipe publicado.

    `etag` chega normalizado (ver `normalizar_etag`), porque é ele que serve de
    identidade do clipe no manifest da sessão (T-06) e no conjunto de ETags já
    aceitos: guardar a forma crua deixaria o mesmo clipe aparecer com duas
    identidades diferentes.

    `last_modified` é a referência de tempo da sessão (AC-003.4 e SUP-009),
    sempre em UTC e ciente de fuso. `relogio_local` é diagnóstico e só isso.
    """

    etag: str
    last_modified: datetime
    relogio_local: datetime


@dataclass(frozen=True)
class FalhaDeServidor:
    """Uma checagem que falhou por culpa do servidor, e não do clipe (AC-033.1).

    Vale para erro de conexão, DNS ou rede, timeout e HTTP de 500 a 599. Uma
    resposta qualquer do servidor (404, 403, 200) não é falha de servidor.
    `instante` é o `agora()` da checagem.
    """

    descricao: str
    instante: datetime


def normalizar_etag(bruto: str) -> str:
    """Reduz o ETag à sua identidade: sem espaços, sem `W/`, sem aspas.

    O prefixo `W/` marca ETag fraco e as aspas fazem parte da sintaxe do
    header, não do valor. Comparar sem normalizar faria `W/"abc"` e `"abc"`
    parecerem dois clipes, o que abriria um segundo minuto para o mesmo vídeo e
    quebraria a exigência de N clipes **distintos** de AC-003.1.
    """
    valor = bruto.strip()
    if valor[:2].upper() == "W/":
        valor = valor[2:].strip()
    return valor.strip('"')


def _last_modified_em_utc(bruto: str) -> datetime | None:
    """Converte o Last-Modified do formato HTTP (RFC 7231) para UTC.

    Devolve `None` quando o valor não parseia, para cair no caminho de D-4 em
    vez de estourar. A conversão usa `email.utils`, que lê o formato
    `%a, %d %b %Y %H:%M:%S GMT` sem depender do locale da máquina — com
    `strptime`, `Sun` e `Sep` mudariam de significado fora do locale C.
    """
    try:
        instante = parsedate_to_datetime(bruto)
    except (TypeError, ValueError):
        return None
    if instante is None:
        return None
    if instante.tzinfo is None:
        instante = instante.replace(tzinfo=timezone.utc)
    return instante.astimezone(timezone.utc)


def checar(
    cliente: httpx.Client, url: str, *, agora: Callable[[], datetime]
) -> Checagem | FalhaDeServidor | None:
    """Pergunta ao servidor, por HEAD, qual clipe está publicado agora.

    Devolve a `Checagem` quando o servidor entrega os dois headers e o
    Last-Modified parseia. Devolve `FalhaDeServidor` em erro de conexão, DNS ou
    rede, timeout e HTTP 500 a 599 (AC-033.1). Devolve `None` nos demais casos
    — headers faltando, data ilegível ou HTTP 4xx —, em que o servidor
    respondeu mas a checagem não produziu clipe identificável, e o certo é
    aguardar a próxima (D-4 de `captura-clipes`).

    É sempre HEAD: nesta etapa o conteúdo não é baixado, nem quando o clipe é
    novo. Quem baixa é `capture.download`, e só depois de `e_novo` aprovar.
    """
    try:
        resposta = cliente.head(url, follow_redirects=True)
        resposta.raise_for_status()
    except httpx.TimeoutException:
        return FalhaDeServidor("timeout", agora())
    except httpx.TransportError as erro:
        return FalhaDeServidor(str(erro) or type(erro).__name__, agora())
    except httpx.HTTPStatusError as erro:
        codigo = erro.response.status_code
        if 500 <= codigo <= 599:
            return FalhaDeServidor(f"o servidor respondeu {codigo}", agora())
        return None
    except httpx.HTTPError:
        return None

    etag_bruto = resposta.headers.get("ETag")
    last_modified_bruto = resposta.headers.get("Last-Modified")
    if not etag_bruto or not last_modified_bruto:
        return None

    etag = normalizar_etag(etag_bruto)
    if not etag:
        return None

    last_modified = _last_modified_em_utc(last_modified_bruto)
    if last_modified is None:
        return None

    return Checagem(etag=etag, last_modified=last_modified, relogio_local=agora())


def e_novo(
    checagem: Checagem | FalhaDeServidor | None, etags_ja_aceitos: Iterable[str]
) -> bool:
    """Diz se esta checagem revelou um clipe que ainda não virou minuto.

    Falso quando o ETag é o mesmo já visto — e aí o conteúdo **não** é baixado
    de novo, o sistema apenas aguarda a próxima checagem (AC-003.2).

    O parâmetro é o conjunto de ETags **já aceitos na sessão**, e não só o da
    checagem anterior: AC-003.1 exige N clipes distintos, então um ETag que já
    virou minuto nunca pode abrir um segundo. Os ETags de dentro do conjunto
    são normalizados na comparação, para que a origem deles (header cru ou
    manifest) não mude a resposta.

    Checagem `None` ou `FalhaDeServidor` é falso, sem estourar: ela não produziu
    clipe (D-4).
    """
    if not isinstance(checagem, Checagem):
        return False
    aceitos = {normalizar_etag(etag) for etag in etags_ja_aceitos}
    return checagem.etag not in aceitos

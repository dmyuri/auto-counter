"""Laço de captura da sessão: a costura entre checagem, download e manifest.

Comportamento em `.spec/features/captura-clipes/spec.md`:

- AC-003.1 — uma sessão de N minutos sem falhas grava exatamente N clipes
  **distintos** em disco, cada um associado ao seu minuto, ETag e Last-Modified;
- AC-003.2 — ETag igual ao da checagem anterior não baixa o conteúdo de novo: o
  sistema aguarda a próxima checagem;
- AC-004.2 — ETag parado por toda a janela marca o minuto como não capturado e
  a captura **segue para o minuto seguinte, sem interromper a sessão**;
- AC-004.1 e AC-004.3 entram aqui como tradução: download esgotado e clipe
  ilegível viram desfecho de minuto, nunca exceção para o usuário.

Os números de SUP-008 são normativos: checagem HEAD a cada 10 s e janela de
90 s por minuto antes de declará-lo perdido. A janela do minuto k começa quando
o minuto k-1 é resolvido, e a do minuto 1 começa no instante do comando
(`_tasks.md`, §Restrições estruturais). O minuto 1 aceita o clipe que já está no
servidor, porque na primeira checagem não existe "checagem anterior" no sentido
de AC-003.2 (D-2).

O denominador do status é o N **pedido** (SUP-013). Quem substitui esse
denominador pela duração real é o encerramento explícito pelo usuário
(AC-003.6): quando `parada` sinaliza, a sessão passa a valer a duração que
realmente aconteceu, e é sobre ela que o status é calculado — desistência nunca
cai na regra do denominador pedido. Enquanto `parada` for `None`, ou nunca
sinalizar, o laço segue até o minuto N.

Relógio, espera e cliente HTTP entram por parâmetro (D-7): uma sessão de 15
minutos com janela de 90 s não teria como ser testada em tempo real.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol

import httpx

from auto_counter.cameras.model import Camera
from auto_counter.cameras.url import url_do_clipe
from auto_counter.capture.download import DownloadFalhouError, baixar
from auto_counter.capture.duration import validar_duracao
from auto_counter.capture.manifest import (
    ManifestDaSessao,
    MinutoCapturado,
    MinutoPerdido,
    diretorio_da_sessao,
    id_da_sessao,
    nome_do_arquivo_do_minuto,
)
from auto_counter.capture.probe import Checagem, checar, e_novo
from auto_counter.capture.readable import descartar, e_legivel
from auto_counter.capture.status import ResultadoDoStatus, StatusDaSessao, classificar

INTERVALO_ENTRE_CHECAGENS = 10.0
"""Segundos entre duas checagens HEAD do mesmo minuto (SUP-008). Normativo."""

JANELA_DO_MINUTO = 90.0
"""Segundos de espera por um clipe novo antes de dar o minuto por perdido.

Número de SUP-008, e o mesmo prazo que limita as 3 tentativas de download de
AC-004.1 (T-04). Não é reinventado aqui: é lido da spec.
"""

MOTIVO_JANELA_ESGOTADA = (
    "a janela de 90 s se esgotou sem clipe novo: o ETag não mudou no servidor "
    "ou as checagens não trouxeram ETag e Last-Modified utilizáveis"
)
"""Perda por AC-004.2 e por D-4 — para o minuto, os dois são o mesmo desfecho."""


class Parada(Protocol):
    """O sinal de encerramento explícito pelo usuário (AC-003.6).

    Modelado como objeto vindo de fora, e não como morte do processo, porque
    fechar a interface não interrompe nada (AC-012.4 de `interface-sessao`). É
    o mesmo gancho que o Ctrl+C do CLI (T-10) e, depois, o botão da interface
    (AC-012.4) acionam.

    O sinal é consultado **entre checagens e entre minutos**: uma parada não
    espera a janela de 90 s vencer para ter efeito, e um minuto abandonado no
    meio da janela não vira minuto perdido.
    """

    def foi_pedida(self) -> bool: ...


@dataclass(frozen=True)
class ResultadoDaSessao:
    """O desfecho da sessão, já classificado e já gravado no manifest.

    `inicio` e `fim` vêm do Last-Modified do primeiro e do último clipe
    **efetivamente capturados** (AC-003.4) — o manifest é quem os calcula, e
    eles são nulos quando nenhum minuto virou vídeo.
    """

    id_sessao: str
    dir_sessao: Path
    duracao_pedida: int
    duracao_real: int
    encerrada_pelo_usuario: bool
    status: StatusDaSessao
    minutos_capturados: tuple[MinutoCapturado, ...]
    minutos_perdidos: tuple[MinutoPerdido, ...]
    inicio: datetime | None
    fim: datetime | None


@dataclass(frozen=True)
class _ClipeAceito:
    """Um clipe que baixou, abriu como vídeo e já está no lugar definitivo."""

    checagem: Checagem
    arquivo: str


@dataclass(frozen=True)
class _MinutoPerdido:
    """A janela terminou sem clipe aceitável, e este foi o último motivo."""

    motivo: str


@dataclass(frozen=True)
class _ParadaPedida:
    """O usuário encerrou a sessão no meio desta janela (AC-003.6).

    Este minuto **não** é perdido: ele simplesmente não existe. Contá-lo como
    perda é a diferença entre uma sessão `DEGRADADA` falsa e a `COMPLETA`
    correta — pedir 15 e parar no 7 sem falha nenhuma não pode virar "8 minutos
    perdidos".
    """


def _parada_pedida(parada: "Parada | None") -> bool:
    """Consulta o sinal de encerramento; `None` significa "ninguém encerrou"."""
    return parada is not None and parada.foi_pedida()


def _janela_de_um_minuto(
    *,
    minuto: int,
    cliente: httpx.Client,
    url: str,
    dir_sessao: Path,
    etags_ja_aceitos: set[str],
    inicio_da_janela: datetime,
    agora: Callable[[], datetime],
    dormir: Callable[[float], None],
    parada: "Parada | None",
) -> _ClipeAceito | _MinutoPerdido | _ParadaPedida:
    """Roda a janela de 90 s de um minuto e devolve o desfecho dele.

    Checagem HEAD imediata e depois a cada 10 s (SUP-008), até a janela vencer:

    - ETag igual ao da checagem anterior, ou já aceito na sessão → não baixa e
      aguarda a próxima checagem (AC-003.2);
    - checagem sem headers utilizáveis → o mesmo, aguarda (D-4);
    - ETag novo → baixa com retry dentro do prazo da janela (AC-004.1) e valida
      a legibilidade (AC-004.3);
    - clipe ilegível → descarta o arquivo e **continua checando dentro do que
      sobrou da janela**, porque o servidor pode publicar outro clipe;
    - parada pedida entre duas checagens → a janela é abandonada e o minuto não
      existe, nem como capturado nem como perdido (AC-003.6);
    - janela vencida → minuto perdido, com o motivo.

    Nenhuma exceção das camadas de baixo escapa: rede, HTTP, header ausente e
    arquivo corrompido já têm caminho definido acima (`CLAUDE.md`).
    """
    prazo = inicio_da_janela + timedelta(seconds=JANELA_DO_MINUTO)
    destino = dir_sessao / nome_do_arquivo_do_minuto(minuto)
    motivo = MOTIVO_JANELA_ESGOTADA

    while agora() < prazo:
        if _parada_pedida(parada):
            return _ParadaPedida()

        checagem = checar(cliente, url, agora=agora)

        if e_novo(checagem, etags_ja_aceitos):
            assert checagem is not None  # `e_novo` é falso para checagem nula.
            try:
                baixar(
                    cliente,
                    url,
                    destino,
                    prazo=prazo,
                    dormir=dormir,
                    agora=agora,
                )
            except DownloadFalhouError as erro:
                # AC-004.1: esgotadas as 3 tentativas dentro da janela, o
                # minuto é marcado como não capturado — não se recomeça a
                # espera por outro clipe.
                return _MinutoPerdido(motivo=str(erro))

            if e_legivel(destino):
                return _ClipeAceito(checagem=checagem, arquivo=destino.name)

            # AC-004.3: o arquivo inválido não pode ficar no diretório da
            # sessão fingindo ser material capturado, e a janela continua.
            descartar(destino)
            etags_ja_aceitos.add(checagem.etag)
            motivo = (
                f"o clipe de ETag {checagem.etag} não abriu como vídeo legível "
                f"e foi descartado; a janela se esgotou sem outro clipe válido"
            )

        restante = (prazo - agora()).total_seconds()
        if restante <= 0:
            break
        dormir(min(INTERVALO_ENTRE_CHECAGENS, restante))

    return _MinutoPerdido(motivo=motivo)


def _duracao_real(
    manifest: ManifestDaSessao, *, duracao_pedida: int, encerrada: bool
) -> int:
    """Quantos minutos a sessão realmente teve.

    Sem encerramento pelo usuário, a duração real é o N pedido: todo minuto de
    1 a N foi resolvido, capturado ou perdido. Com encerramento no minuto k
    (AC-003.6), é o número de minutos **já resolvidos** — o minuto em curso
    quando a parada chegou não existe, e os minutos que nem começaram também
    não. Contar pelo manifest, e não por `k - 1`, é o que mantém a duração real
    igual ao que ficou registrado em disco.
    """
    if not encerrada:
        return duracao_pedida
    return len(manifest.minutos_capturados) + len(manifest.minutos_perdidos)


def _classificar_a_sessao(base: int, minutos_perdidos: list[int]) -> ResultadoDoStatus:
    """Classifica a sessão pelo denominador que o laço escolheu (SUP-013).

    Uma sessão encerrada antes do primeiro minuto resolvido tem duração real 0,
    e `classificar` rejeita `base < 1` como erro de programação — com razão: não
    existe percentual sobre zero. Decisão do autor do projeto para este caso:
    `INVALIDA`, sem passar por `classificar`, com a lista de perdidos vazia.
    Coerente com o §Contexto da spec, onde o status responde se aquele número
    pode ser comparado ao de outra sessão — sem nenhum minuto, não pode. Segue
    sendo sessão, não exceção (AC-003.6), e não é um quarto status (Q-003).
    """
    if base < 1:
        return ResultadoDoStatus(StatusDaSessao.INVALIDA, ())
    return classificar(base, minutos_perdidos)


def capturar(
    camera: Camera,
    minutos: int,
    *,
    data_dir: str | Path,
    cliente: httpx.Client,
    agora: Callable[[], datetime],
    dormir: Callable[[float], None],
    parada: Parada | None = None,
) -> ResultadoDaSessao:
    """Captura N minutos de clipes da câmera e devolve o desfecho da sessão.

    A ordem é obrigatória: valida a duração **antes** de montar URL ou tocar a
    rede (AC-003.3), cria o diretório e o manifest da sessão (SUP-012, D-3),
    roda a janela de cada minuto de 1 a N e só então classifica o status com
    `base = N` pedido (SUP-013) e fecha o manifest.

    Os N clipes são distintos por construção (AC-003.1): o conjunto de ETags já
    aceitos é o guarda disso, e um ETag que já virou minuto — ou que virou
    arquivo ilegível descartado — nunca abre um segundo.

    A janela de cada minuto começa quando o minuto anterior é **resolvido**,
    capturado ou perdido; a do minuto 1 começa no instante do comando. Um minuto
    perdido não interrompe a sessão: a captura segue para o seguinte (AC-004.2).

    `parada` é o encerramento explícito pelo usuário (AC-003.6), consultado
    entre minutos e entre checagens. Quando ele sinaliza no minuto k, a duração
    real da sessão passa a ser o número de minutos já resolvidos, o status é
    calculado sobre essa duração e não sobre o N pedido (SUP-013), o
    encerramento fica registrado no manifest, e os minutos já capturados seguem
    para processamento: o retorno é um resultado de sessão normal, com status
    próprio, e não um erro. Enquanto `parada` for `None`, o laço vai até N.
    """
    duracao_pedida = validar_duracao(minutos)
    url = url_do_clipe(camera)

    relogio_do_comando = agora()
    id_sessao = id_da_sessao(camera.id, relogio_do_comando)
    dir_sessao = diretorio_da_sessao(data_dir, id_sessao)
    manifest = ManifestDaSessao.criar(
        dir_sessao,
        id_sessao=id_sessao,
        id_camera=camera.id,
        duracao_pedida=duracao_pedida,
    )

    etags_ja_aceitos: set[str] = set()
    inicio_da_janela = relogio_do_comando
    encerrada_pelo_usuario = False

    for minuto in range(1, duracao_pedida + 1):
        if _parada_pedida(parada):
            encerrada_pelo_usuario = True
            break

        desfecho = _janela_de_um_minuto(
            minuto=minuto,
            cliente=cliente,
            url=url,
            dir_sessao=dir_sessao,
            etags_ja_aceitos=etags_ja_aceitos,
            inicio_da_janela=inicio_da_janela,
            agora=agora,
            dormir=dormir,
            parada=parada,
        )

        if isinstance(desfecho, _ParadaPedida):
            encerrada_pelo_usuario = True
            break

        if isinstance(desfecho, _ClipeAceito):
            etags_ja_aceitos.add(desfecho.checagem.etag)
            manifest.registrar_minuto(
                minuto,
                etag=desfecho.checagem.etag,
                last_modified=desfecho.checagem.last_modified,
                relogio_local=desfecho.checagem.relogio_local,
                arquivo=desfecho.arquivo,
            )
        else:
            manifest.registrar_perda(minuto, motivo=desfecho.motivo)

        inicio_da_janela = agora()

    minutos_perdidos = [item.minuto for item in manifest.minutos_perdidos]
    duracao_real = _duracao_real(
        manifest, duracao_pedida=duracao_pedida, encerrada=encerrada_pelo_usuario
    )
    resultado = _classificar_a_sessao(duracao_real, minutos_perdidos)
    manifest.fechar(
        resultado,
        duracao_real=duracao_real,
        encerrada_pelo_usuario=encerrada_pelo_usuario,
    )

    return ResultadoDaSessao(
        id_sessao=id_sessao,
        dir_sessao=dir_sessao,
        duracao_pedida=duracao_pedida,
        duracao_real=duracao_real,
        encerrada_pelo_usuario=encerrada_pelo_usuario,
        status=resultado.status,
        minutos_capturados=manifest.minutos_capturados,
        minutos_perdidos=manifest.minutos_perdidos,
        inicio=manifest.inicio,
        fim=manifest.fim,
    )

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
(AC-003.6), tratado em T-08: `parada` já entra na assinatura como o gancho
dele, e enquanto for `None` o laço segue até o minuto N.

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
from auto_counter.capture.status import StatusDaSessao, classificar

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
    fechar a interface não interrompe nada (AC-012.4 de `interface-sessao`). O
    consumo deste sinal é de T-08; aqui ele só é aceito e, quando `None`,
    ignorado.
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
) -> _ClipeAceito | _MinutoPerdido:
    """Roda a janela de 90 s de um minuto e devolve o desfecho dele.

    Checagem HEAD imediata e depois a cada 10 s (SUP-008), até a janela vencer:

    - ETag igual ao da checagem anterior, ou já aceito na sessão → não baixa e
      aguarda a próxima checagem (AC-003.2);
    - checagem sem headers utilizáveis → o mesmo, aguarda (D-4);
    - ETag novo → baixa com retry dentro do prazo da janela (AC-004.1) e valida
      a legibilidade (AC-004.3);
    - clipe ilegível → descarta o arquivo e **continua checando dentro do que
      sobrou da janela**, porque o servidor pode publicar outro clipe;
    - janela vencida → minuto perdido, com o motivo.

    Nenhuma exceção das camadas de baixo escapa: rede, HTTP, header ausente e
    arquivo corrompido já têm caminho definido acima (`CLAUDE.md`).
    """
    prazo = inicio_da_janela + timedelta(seconds=JANELA_DO_MINUTO)
    destino = dir_sessao / nome_do_arquivo_do_minuto(minuto)
    motivo = MOTIVO_JANELA_ESGOTADA

    while agora() < prazo:
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

    `parada` é o gancho do encerramento explícito pelo usuário (AC-003.6),
    consumido em T-08. Enquanto for `None`, o laço vai até o minuto N.
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

    for minuto in range(1, duracao_pedida + 1):
        desfecho = _janela_de_um_minuto(
            minuto=minuto,
            cliente=cliente,
            url=url,
            dir_sessao=dir_sessao,
            etags_ja_aceitos=etags_ja_aceitos,
            inicio_da_janela=inicio_da_janela,
            agora=agora,
            dormir=dormir,
        )

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

    resultado = classificar(
        duracao_pedida, [item.minuto for item in manifest.minutos_perdidos]
    )
    manifest.fechar(resultado, duracao_real=duracao_pedida)

    return ResultadoDaSessao(
        id_sessao=id_sessao,
        dir_sessao=dir_sessao,
        duracao_pedida=duracao_pedida,
        duracao_real=duracao_pedida,
        encerrada_pelo_usuario=False,
        status=resultado.status,
        minutos_capturados=manifest.minutos_capturados,
        minutos_perdidos=manifest.minutos_perdidos,
        inicio=manifest.inicio,
        fim=manifest.fim,
    )

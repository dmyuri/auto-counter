"""Processamento da sessão inteira, do manifest ao `eventos.json` — T-12.

Costura T-11 (um clipe), T-10 (a emenda) e T-07 (a gravação) na ordem que a
spec impõe, e é aqui que as decisões que dependem da **sessão** — e que nenhum
dos três módulos anteriores tem como tomar — acontecem:

- AC-007.3 — cada minuto ganha rastreador novo, porque quem cria o rastreador é
  `processar_clipe`, chamada uma vez por minuto;
- AC-007.1 e AC-007.2 — a deduplicação da emenda é aplicada entre o minuto
  anterior e o atual, com os `fps` e a duração lidos de cada clipe. Por
  SUP-053 de `acompanhamento-ao-vivo`, ela é aplicada **evento a evento**, no
  momento em que o cruzamento é gerado (`FiltroDaEmenda`), e não depois do clipe
  inteiro; o resultado gravado é o mesmo;
- AC-007.4 — **a adjacência é decidida aqui**, a partir do manifest: dois
  minutos são adjacentes quando são consecutivos e os dois foram capturados
  **e processados**. Minuto perdido na captura (AC-004.5) ou não processado por
  D-4 quebra a adjacência, a janela não se aplica e todos os cruzamentos
  contam;
- SUP-021 — sessão com status `INVALIDA` é processada como qualquer outra. Não
  existe desvio para ela neste módulo, e é de propósito.

**D-4:** clipe ausente ou ilegível vira minuto não processado com o motivo e a
sessão segue. Se **nenhum** clipe da sessão existir, o processamento falha com
`SessaoSemClipes` e nada é gravado — provavelmente é uma sessão já descartada
por D-5, e um `eventos.json` zerado ali seria lido depois como se nenhum
veículo tivesse passado.

A gravação é incremental, minuto a minuto, pelo mesmo motivo do manifest: 15
minutos de processamento não podem ser perdidos por uma queda no minuto 14. O
primeiro arquivo só aparece depois do primeiro minuto **processado**, que é o
que mantém a promessa de D-4 acima.

Esta função **não** apaga vídeo: o descarte é de T-13 (D-5), depois que o
processamento termina com sucesso.

Para `interface-sessao`, o processamento é observável e interrompível:
`ao_resolver_minuto` informa o progresso (AC-012.2) e `parada` é consultada
antes de cada clipe (AC-012.5). Pedida a parada, a função levanta
`ProcessamentoCancelado`; o `eventos.json` parcial que já tenha sido gravado
fica onde está, e quem decide o que fazer com ele é o chamador.

Para `acompanhamento-ao-vivo`, `ao_aceitar_evento` publica cada evento aceito
(já depois da emenda e de AC-006.6) assim que ele é gerado, e
`ao_descartar_minuto` avisa que os eventos já publicados de um clipe que falhou
no meio da leitura foram jogados fora (D-4, AC-016.8), antes de
`ao_resolver_minuto`.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from auto_counter.cameras.model import Camera
from auto_counter.capture import manifest as manifest_da_captura
from auto_counter.counting.clip import (
    DetectorDoClipe,
    ResultadoDoClipe,
    processar_clipe,
)
from auto_counter.counting.config import ConfiguracaoDoProcessamento
from auto_counter.counting.events import (
    Evento,
    MinutoNaoProcessado,
    RegistroDeEventos,
)
from auto_counter.counting.events import ler as ler_eventos
from auto_counter.counting.seam import FiltroDaEmenda
from auto_counter.counting.tracking import RastreadorDoSupervision, criar_bytetrack

MOTIVO_MINUTO_PERDIDO_NA_CAPTURA = "minuto perdido na captura: {motivo}"
"""O minuto que nunca virou clipe entra no `eventos.json` carregando o motivo
que a captura registrou (AC-004.5), e não um texto novo: quem ler depois
precisa saber que a perda é da captura, não do processamento."""


class SessaoSemClipes(RuntimeError):
    """Nenhum minuto da sessão pôde ser processado (D-4).

    Erro explícito, e não resultado vazio: é o que separa "passou zero veículo"
    de "não havia vídeo nenhum para olhar".
    """


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


@dataclass(frozen=True)
class ResultadoDaContagem:
    """O que a sessão rendeu, e onde isso ficou gravado.

    `registro` é exatamente o que está no `eventos.json` — o mesmo objeto de
    T-07 —, e o caminho vem junto porque quem chama (a CLI de T-13) precisa
    dizer ao usuário onde o resultado foi parar.
    """

    registro: RegistroDeEventos
    caminho: Path

    @property
    def eventos(self) -> tuple[Evento, ...]:
        """Os eventos aceitos da sessão, já deduplicados nas emendas."""
        return self.registro.eventos

    @property
    def minutos_processados(self) -> tuple[int, ...]:
        """Os minutos que foram analisados, em ordem de minuto."""
        return self.registro.minutos_processados

    @property
    def minutos_nao_processados(self) -> tuple[MinutoNaoProcessado, ...]:
        """Os minutos sem dado, com o motivo de cada um (AC-008.4)."""
        return self.registro.minutos_nao_processados


def processar_sessao(
    dir_sessao: str | Path,
    *,
    camera: Camera,
    detector: DetectorDoClipe,
    config: ConfiguracaoDoProcessamento,
    versao_do_modelo: str,
    fabrica_de_bytetrack: Callable[[], RastreadorDoSupervision] = criar_bytetrack,
    parada: ParadaDoProcessamento | None = None,
    ao_resolver_minuto: Callable[[int], None] | None = None,
    ao_aceitar_evento: Callable[[int, Evento], None] | None = None,
    ao_descartar_minuto: Callable[[int], None] | None = None,
) -> ResultadoDaContagem:
    """Processa todos os clipes de uma sessão e grava o `eventos.json` (D-1).

    `dir_sessao` é o diretório da sessão, o mesmo que guarda o `manifest.json` e
    os `.mp4`. O manifest é lido por `capture.manifest.ler` — a associação entre
    minuto, arquivo e Last-Modified já é entrega daquela feature, e AC-006.5
    depende do Last-Modified de **cada** clipe.

    `versao_do_modelo` vem de fora porque quem conhece o `.onnx` é a CLI (T-13):
    este módulo grava a versão usada (AC-008.1), não a descobre.

    `parada` é consultada **antes de cada clipe** (AC-012.5): pedida, levanta
    `ProcessamentoCancelado` sem abrir o clipe seguinte. `ao_resolver_minuto`
    recebe o número de cada minuto capturado depois de resolvido, processado ou
    não processado (AC-012.2). Sem os dois, nada muda.

    `ao_aceitar_evento(minuto, evento)` é chamado a cada evento aceito, no
    momento em que o cruzamento é gerado (AC-016.2). `ao_descartar_minuto(minuto)`
    é chamado quando o clipe falha (D-4), antes de `ao_resolver_minuto`
    (AC-016.8). Minuto perdido na captura nunca chega ao clipe e não publica
    nada (AC-016.6).
    """
    dir_sessao = Path(dir_sessao)
    manifest = manifest_da_captura.ler(dir_sessao)

    eventos: list[Evento] = []
    processados: list[int] = []
    nao_processados: list[MinutoNaoProcessado] = [
        MinutoNaoProcessado(
            minuto=perdido.minuto,
            motivo=MOTIVO_MINUTO_PERDIDO_NA_CAPTURA.format(motivo=perdido.motivo),
        )
        for perdido in manifest.minutos_perdidos
    ]

    # O minuto anterior **processado**, com o resultado dele: é o lado esquerdo
    # da emenda. Fica nulo enquanto não houver nenhum, e volta a ser nulo a cada
    # minuto que não deu resultado — é assim que D-4 quebra a adjacência pela
    # mesma regra de AC-007.4.
    anterior: tuple[int, ResultadoDoClipe] | None = None

    def grava() -> Path:
        """O `eventos.json` do que já foi decidido até aqui."""
        return RegistroDeEventos(
            id_sessao=manifest.id_sessao,
            id_camera=manifest.id_camera,
            configuracao=config,
            versao_do_modelo=versao_do_modelo,
            minutos_processados=tuple(processados),
            minutos_nao_processados=tuple(
                sorted(nao_processados, key=lambda item: item.minuto)
            ),
            eventos=tuple(eventos),
        ).gravar(dir_sessao)

    caminho: Path | None = None

    for capturado in sorted(manifest.minutos_capturados, key=lambda item: item.minuto):
        minuto = capturado.minuto
        if parada is not None and parada.foi_pedida():
            raise ProcessamentoCancelado(
                f"o processamento da sessão {manifest.id_sessao} foi cancelado "
                f"a pedido do usuário antes do minuto {minuto}"
            )
        if anterior is None:
            filtro = FiltroDaEmenda.sem_anterior()
        else:
            minuto_anterior, clipe_anterior = anterior
            filtro = FiltroDaEmenda(
                eventos_do_clipe_anterior=clipe_anterior.eventos,
                adjacentes=(minuto == minuto_anterior + 1),
                fps_do_clipe_anterior=clipe_anterior.fps,
                duracao_do_clipe_anterior=clipe_anterior.duracao_em_segundos,
                config=config,
            )
        aceitos: list[Evento] = []

        def ao_gerar(evento: Evento, fps: float) -> None:
            if filtro.aceita(evento, fps_do_clipe_atual=fps):
                aceitos.append(evento)
                if ao_aceitar_evento is not None:
                    ao_aceitar_evento(minuto, evento)

        resultado = processar_clipe(
            dir_sessao / capturado.arquivo,
            camera=camera,
            minuto=minuto,
            inicio_do_clipe=capturado.last_modified,
            detector=detector,
            config=config,
            fabrica_de_bytetrack=fabrica_de_bytetrack,
            ao_gerar_evento=ao_gerar,
        )

        if resultado.motivo is not None:
            nao_processados.append(
                MinutoNaoProcessado(minuto=minuto, motivo=resultado.motivo)
            )
            anterior = None
            if ao_descartar_minuto is not None:
                ao_descartar_minuto(minuto)
            if ao_resolver_minuto is not None:
                ao_resolver_minuto(minuto)
            continue

        eventos.extend(aceitos)
        processados.append(minuto)
        anterior = (minuto, resultado)
        caminho = grava()
        if ao_resolver_minuto is not None:
            ao_resolver_minuto(minuto)

    if caminho is None:
        raise SessaoSemClipes(
            f"nenhum clipe da sessão {manifest.id_sessao} pôde ser processado em "
            f"{dir_sessao}; a contagem não foi gravada, porque um resultado "
            f"zerado seria indistinguível de uma sessão sem nenhum veículo (D-4)"
        )

    return ResultadoDaContagem(registro=_ler_gravado(caminho), caminho=caminho)


def _ler_gravado(caminho: Path) -> RegistroDeEventos:
    """O registro como ele ficou no disco, que é o resultado da sessão.

    Devolver o que foi lido de volta, e não o objeto montado em memória, faz o
    resultado carregar exatamente o que `persistencia-resultados` e
    `validacao-acuracia` vão encontrar — inclusive a ordenação de
    `eventos_em_ordem`, que a gravação aplica.
    """
    return ler_eventos(caminho)

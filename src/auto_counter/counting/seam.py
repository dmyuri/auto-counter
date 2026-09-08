"""Deduplicação na emenda entre dois clipes — T-10.

Comportamento em `.spec/features/contagem-veiculos/spec.md`:

- AC-007.1 — um cruzamento nos últimos 2 s de um clipe e um cruzamento de
  assinatura compatível nos primeiros 2 s do clipe imediatamente seguinte são o
  mesmo veículo passando por cima do corte: o segundo não gera evento novo;
- AC-007.2 — assinaturas diferentes são veículos diferentes, e os dois contam;
- AC-007.4 — se os dois clipes não forem adjacentes, a janela não se aplica.

Implementa SUP-019: a assinatura é a tripla categoria + sentido + posição do
cruzamento ao longo da linha, com tolerância de 10% do comprimento da linha.
A `posicao_na_linha` do `Evento` já é a fração de 0 a 1 ao longo da linha
(T-09), então a tolerância de `ConfiguracaoDoProcessamento` é comparada
diretamente com a diferença das frações — nenhum comprimento em pixels entra
aqui.

Esta é a **única** ponte entre clipes. O rastreador reinicia a cada clipe
(AC-007.3) e os ids nunca coincidem, então o pareamento não pode usar id de
rastreio — daí a assinatura de SUP-019, que é feita só de grandezas
observáveis do cruzamento.

**A janela usa o deslocamento dentro do clipe** — índice do frame ÷ fps —, e
não o `timestamp` do evento: AC-006.5 trunca o timestamp para o segundo, e
truncar perderia resolução justamente na borda que decide a emenda. Por isso a
duração e o fps de cada clipe entram como parâmetro: os dois são lidos do
próprio arquivo de vídeo (T-11), e nada aqui fixa 59,93 s nem 30 fps.

Este módulo não conhece manifest nem sessão: quem decide se dois clipes são
adjacentes é T-12, e passa a decisão em `adjacentes`.
"""

from dataclasses import dataclass
from typing import Iterable

from auto_counter.counting.config import Categoria, ConfiguracaoDoProcessamento
from auto_counter.counting.events import Evento


@dataclass(frozen=True)
class Assinatura:
    """A tripla de SUP-019 que identifica um cruzamento na emenda.

    Deliberadamente **sem** id de rastreio e sem minuto: os ids reiniciam a cada
    clipe (AC-007.3), e incluí-los faria dois lados da mesma emenda nunca
    combinarem — a deduplicação de AC-007.1 jamais aconteceria.

    A posição fica no objeto mas não entra na igualdade útil: duas assinaturas
    são comparadas por `compativeis`, com a tolerância de SUP-019, e não por
    `==`, que exigiria posições idênticas ao último dígito.
    """

    categoria: Categoria
    sentido: str
    posicao_na_linha: float


def assinatura(evento: Evento) -> Assinatura:
    """A assinatura de SUP-019 do cruzamento registrado por `evento`."""
    return Assinatura(
        categoria=evento.categoria,
        sentido=evento.sentido,
        posicao_na_linha=evento.posicao_na_linha,
    )


def compativeis(
    uma: Assinatura, outra: Assinatura, *, tolerancia: float
) -> bool:
    """Duas assinaturas são o mesmo veículo dos dois lados do corte?

    Categoria e sentido são exatos — trocar de categoria ou de mão no corte não
    é o mesmo veículo. A posição admite a tolerância de SUP-019, porque o
    veículo anda entre o último frame de um clipe e o primeiro do seguinte e
    nunca toca a linha exatamente no mesmo ponto.
    """
    return (
        uma.categoria == outra.categoria
        and uma.sentido == outra.sentido
        and abs(uma.posicao_na_linha - outra.posicao_na_linha) <= tolerancia
    )


def _deslocamento(evento: Evento, fps: float) -> float:
    """Segundos entre o início do clipe e o frame do cruzamento.

    Sem truncar: é o que separa esta janela do timestamp de AC-006.5.
    """
    if fps <= 0:
        raise ValueError(
            f"fps precisa ser positivo, e veio {fps!r}; sem taxa de quadros não "
            f"existe deslocamento do frame dentro do clipe"
        )
    return evento.indice_do_frame / fps


def deduplicar(
    eventos_do_clipe_anterior: Iterable[Evento],
    eventos_do_clipe_atual: Iterable[Evento],
    *,
    adjacentes: bool,
    fps_do_clipe_anterior: float,
    duracao_do_clipe_anterior: float,
    fps_do_clipe_atual: float,
    config: ConfiguracaoDoProcessamento,
) -> tuple[Evento, ...]:
    """Os eventos do clipe atual que sobrevivem à emenda, na ordem recebida.

    Os eventos do clipe anterior já foram aceitos quando aquele clipe foi
    processado — eles entram aqui só como supressores. O que esta função decide
    é quais cruzamentos do clipe **atual** são veículos novos.

    `adjacentes` falso desliga a deduplicação inteira e devolve tudo (AC-007.4):
    se houve minuto perdido entre os dois clipes, eles não se tocam no tempo e
    nenhum cruzamento de um pode ser a continuação do outro. Quem decide a
    adjacência é T-12, a partir do manifest.

    **Pareamento 1 para 1:** cada evento do lado esquerdo suprime no máximo um
    do lado direito. Sem isso, dois carros na mesma faixa no início do clipe
    seguinte — mesma categoria, mesmo sentido, mesma posição — seriam ambos
    engolidos por um único cruzamento anterior, e AC-007.2 quebraria justamente
    no caso mais provável.
    """
    atuais = tuple(eventos_do_clipe_atual)
    if not adjacentes:
        return atuais

    janela = config.janela_de_emenda_em_segundos
    limite_do_clipe_anterior = duracao_do_clipe_anterior - janela

    # Lado esquerdo: cruzamentos nos últimos `janela` segundos do clipe
    # anterior. Cada um pode gastar sua supressão uma única vez.
    supressores = [
        assinatura(evento)
        for evento in eventos_do_clipe_anterior
        if _deslocamento(evento, fps_do_clipe_anterior) >= limite_do_clipe_anterior
    ]
    ja_usados = [False] * len(supressores)

    aceitos: list[Evento] = []
    for evento in atuais:
        # Lado direito: só os cruzamentos dos primeiros `janela` segundos do
        # clipe atual são candidatos a ser continuação do clipe anterior.
        na_janela = _deslocamento(evento, fps_do_clipe_atual) <= janela
        if not na_janela:
            aceitos.append(evento)
            continue

        candidata = assinatura(evento)
        for posicao, supressor in enumerate(supressores):
            if ja_usados[posicao]:
                continue
            if compativeis(
                supressor, candidata, tolerancia=config.tolerancia_da_assinatura
            ):
                ja_usados[posicao] = True
                break
        else:
            aceitos.append(evento)

    return tuple(aceitos)

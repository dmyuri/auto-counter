"""Cruzamento da linha de contagem, com sentido — T-09.

Comportamento em `.spec/features/contagem-veiculos/spec.md`:

- AC-006.1 — cada trajetória que passa de um lado da linha para o outro
  registra exatamente um evento com timestamp, categoria, sentido e id de
  rastreio;
- AC-006.2 — aproximar-se da linha sem atravessá-la não registra nada. Não há
  tolerância de proximidade: cruzou ou não cruzou;
- AC-006.3 — cada evento recebe o rótulo de sentido configurado para **aquela**
  câmera (AC-001.1);
- AC-006.4 — cruzar e voltar dentro do mesmo clipe gera dois eventos, um por
  sentido;
- AC-006.6 — no máximo um evento por par (id de rastreio, sentido) no clipe.

Implementa SUP-018: quem decide se houve cruzamento é o `LineZone` da
`supervision`, com o ponto de ancoragem no **centro da base** da caixa — o
contato com o solo, não o centro da caixa.

**O sentido não sai da convenção "in"/"out" do `LineZone`.** Ele sai da normal
de SUP-003, calculada por `cameras.geometry.normal_da_linha`: o deslocamento do
ponto de ancoragem entre o frame anterior e o do cruzamento é projetado na
normal, e o sinal dessa projeção escolhe entre `sentido_a` (a favor da normal) e
`sentido_b` (contra). Assim o rótulo depende de uma grandeza que a spec define,
e não de uma convenção interna da biblioteca que uma atualização dela poderia
inverter em silêncio. Os dois testes de AC-006.3 são o que ancora isso — em
particular o que inverte `p1` e `p2` e espera os rótulos trocados.

Os rótulos são texto vindo do YAML da câmera. Nada aqui os fixa em código nem
os reaproveita entre câmeras (`CLAUDE.md`).

O avaliador é **de um clipe**, como o rastreador de T-08: o conjunto de pares já
registrados de AC-006.6 vive nele e morre com ele. Nenhum estado atravessa a
emenda — a única ponte entre clipes é a janela de deduplicação de T-10.
"""

from datetime import datetime

import supervision as sv

from auto_counter.cameras.geometry import normal_da_linha
from auto_counter.cameras.model import Camera
from auto_counter.counting.events import Evento
from auto_counter.counting.timestamps import instante_do_evento
from auto_counter.counting.tracking import CHAVE_DO_ID_DE_RASTREIO, Rastreador

ANCORA = sv.Position.BOTTOM_CENTER
"""O ponto do veículo é o centro da base da caixa (SUP-018)."""


def _ancora_da_caixa(caixa) -> tuple[float, float]:
    """O centro da base da caixa `xyxy` (SUP-018), em pixels do frame."""
    x1, _, x2, y2 = (float(valor) for valor in caixa)
    return ((x1 + x2) / 2.0, y2)


class AvaliadorDeCruzamento:
    """Decide, frame a frame, quais rastreios cruzaram a linha e em que sentido.

    Construído a partir da `Camera` — a linha e os dois rótulos vêm dela
    (AC-001.1) — e do `Rastreador` daquele clipe, que é quem sabe a categoria do
    rastreio pelo voto de SUP-023 e a confiança média da categoria vencedora.

    `inicio_do_clipe` é o Last-Modified do clipe e `fps` a taxa do vídeo: os dois
    juntos datam o evento pelo índice do frame (AC-006.5, via T-06).
    """

    def __init__(
        self,
        camera: Camera,
        rastreador: Rastreador,
        inicio_do_clipe: datetime,
        fps: float,
    ) -> None:
        self._camera = camera
        self._rastreador = rastreador
        self._inicio_do_clipe = inicio_do_clipe
        self._fps = fps

        linha = camera.linha
        self._p1 = (float(linha.p1.x), float(linha.p1.y))
        self._p2 = (float(linha.p2.x), float(linha.p2.y))
        self._normal = normal_da_linha(linha)

        self._line_zone = sv.LineZone(
            start=sv.Point(x=self._p1[0], y=self._p1[1]),
            end=sv.Point(x=self._p2[0], y=self._p2[1]),
            triggering_anchors=[ANCORA],
        )

        self._ancora_anterior: dict[str, tuple[float, float]] = {}
        self._pares_registrados: set[tuple[str, str]] = set()

    @property
    def pares_registrados(self) -> frozenset[tuple[str, str]]:
        """Os pares (id de rastreio, sentido) já contados neste clipe (AC-006.6)."""
        return frozenset(self._pares_registrados)

    def avaliar(
        self, rastreadas: sv.Detections, indice_do_frame: int
    ) -> tuple[Evento, ...]:
        """Os eventos gerados pelos cruzamentos vistos neste frame.

        Recebe as detecções **já rastreadas** por T-08 — com `tracker_id`, que é
        o que o `LineZone` consome, e com o id composto de D-9 no `data`, que é
        o que vai para o evento.

        Devolve tupla vazia quando ninguém cruzou, que é o caso de AC-006.2 e o
        caso comum de qualquer frame.
        """
        if len(rastreadas) == 0:
            return ()

        entrou, saiu = self._line_zone.trigger(rastreadas)

        ids = rastreadas.data[CHAVE_DO_ID_DE_RASTREIO]
        eventos: list[Evento] = []

        for indice in range(len(rastreadas)):
            id_de_rastreio = str(ids[indice])
            ancora = _ancora_da_caixa(rastreadas.xyxy[indice])
            anterior = self._ancora_anterior.get(id_de_rastreio)
            self._ancora_anterior[id_de_rastreio] = ancora

            if not (bool(entrou[indice]) or bool(saiu[indice])):
                continue
            if anterior is None:
                # Cruzamento sem frame anterior daquele id não tem deslocamento
                # de onde tirar o sentido. Não acontece com o LineZone, que só
                # dispara na transição, mas inventar um sentido aqui seria pior
                # do que não contar.
                continue

            evento = self._evento_do_cruzamento(
                id_de_rastreio=id_de_rastreio,
                ancora=ancora,
                anterior=anterior,
                indice_do_frame=indice_do_frame,
            )
            if evento is not None:
                eventos.append(evento)

        return tuple(eventos)

    def _evento_do_cruzamento(
        self,
        id_de_rastreio: str,
        ancora: tuple[float, float],
        anterior: tuple[float, float],
        indice_do_frame: int,
    ) -> Evento | None:
        """Monta o evento do cruzamento, ou `None` se ele for descartado.

        Descarta por AC-006.6 — o par (id, sentido) já contado neste clipe — e
        também quando o rastreio não tem categoria, o que só aconteceria se o
        cruzamento viesse de um id que nunca passou pelo rastreador.
        """
        sentido = self._sentido_do_deslocamento(anterior, ancora)
        par = (id_de_rastreio, sentido)
        if par in self._pares_registrados:
            return None

        categoria = self._rastreador.categoria_do_rastreio(id_de_rastreio)
        confianca = self._rastreador.confianca_do_rastreio(id_de_rastreio)
        if categoria is None or confianca is None:
            return None

        self._pares_registrados.add(par)

        return Evento(
            timestamp=instante_do_evento(
                self._inicio_do_clipe, indice_do_frame, self._fps
            ),
            categoria=categoria,
            sentido=sentido,
            id_de_rastreio=id_de_rastreio,
            confianca=confianca,
            minuto=self._rastreador.minuto,
            indice_do_frame=indice_do_frame,
            posicao_na_linha=self._posicao_na_linha(ancora),
        )

    def _sentido_do_deslocamento(
        self, anterior: tuple[float, float], atual: tuple[float, float]
    ) -> str:
        """O rótulo da câmera para o lado em que o veículo atravessou (AC-006.3).

        A favor da normal de SUP-003 é `sentido_a`; contra ela, `sentido_b`.
        Projeção exatamente zero não existe aqui: o `LineZone` só dispara quando
        o ponto mudou de lado, e mudar de lado implica deslocamento não nulo na
        normal.
        """
        deslocamento = (atual[0] - anterior[0], atual[1] - anterior[1])
        projecao = (
            deslocamento[0] * self._normal[0] + deslocamento[1] * self._normal[1]
        )
        return self._camera.sentido_a if projecao > 0 else self._camera.sentido_b

    def _posicao_na_linha(self, ancora: tuple[float, float]) -> float:
        """Onde ao longo da linha o cruzamento aconteceu, de 0 a 1 (SUP-019).

        É a projeção do ponto de ancoragem sobre o segmento `p1 -> p2`,
        normalizada pelo comprimento. Fica presa em 0..1 porque o `LineZone`
        também conta quem cruza o prolongamento da linha, e `Evento` recusa
        fração fora desse intervalo.
        """
        dx = self._p2[0] - self._p1[0]
        dy = self._p2[1] - self._p1[1]
        comprimento_ao_quadrado = dx * dx + dy * dy
        projecao = (
            (ancora[0] - self._p1[0]) * dx + (ancora[1] - self._p1[1]) * dy
        ) / comprimento_ao_quadrado
        return min(1.0, max(0.0, projecao))

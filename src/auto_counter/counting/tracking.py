"""Rastreamento por clipe e categoria por voto majoritário — T-08.

Comportamento em `.spec/features/contagem-veiculos/spec.md`:

- AC-007.3 — o estado do rastreador é reiniciado a cada clipe e nenhum id de
  rastreio é reaproveitado entre clipes.

Implementa SUP-018 (ByteTrack da `supervision`) e SUP-023 (a categoria do
rastreio é a classe mais frequente entre os frames em que aquele id foi
detectado, e não a do frame do cruzamento, para reduzir troca de classe por
oclusão momentânea).

Reiniciar é literal: existe **um `Rastreador` por clipe**, criado por
`rastreador_para_o_clipe`. Reaproveitar a instância entre clipes
reintroduziria a continuidade de identidade de veículo, que está em Fora de
escopo — a única ponte entre clipes é a janela de deduplicação de US-007.

Os ids expostos para fora são os compostos de D-9, `<minuto>:<id>`, montados
por `counting.events.id_de_rastreio_composto`. É isso que faz "nenhum id de
rastreio é reaproveitado entre clipes" ser verdade e verificável: o ByteTrack
reinicia a numeração a cada clipe, então sem o prefixo o id 7 do minuto 3 e o
id 7 do minuto 4 seriam o mesmo id.

O ByteTrack entra por fábrica injetável (D-8), para que o teste possa dirigir
trajetórias sintéticas sem detector real.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np
import supervision as sv

from .config import Categoria, categoria_da_classe_coco
from .events import id_de_rastreio_composto

CHAVE_DO_ID_DE_RASTREIO = "id_de_rastreio"
"""Nome do campo com o id composto dentro de `Detections.data`.

O `tracker_id` do `supervision` é inteiro e continua sendo o do ByteTrack,
porque é ele que o ByteTrack devolve. O id da spec — o composto, que é
o que vai para o evento — viaja ao lado, no `data`.
"""


class RastreadorDoSupervision(Protocol):
    """O contrato que este módulo usa do `ByteTrack` da `supervision` (D-8)."""

    def update_with_detections(self, detections: Any) -> Any: ...


def criar_bytetrack() -> RastreadorDoSupervision:
    """Constrói o `ByteTrack` real (SUP-018).

    É a fábrica padrão de `rastreador_para_o_clipe`. Uma instância nova por
    clipe é o próprio AC-007.3 — não existe caminho neste módulo que devolva
    um ByteTrack já usado.
    """
    return sv.ByteTrack()


_CLASSE_COCO_POR_CATEGORIA: dict[Categoria, int] = {
    categoria_da_classe_coco(classe): classe for classe in (2, 3, 5, 7)
}
"""Inverso do mapa de `config.py`, derivado dele para não repetir os números."""


@dataclass
class _HistoricoDaCategoria:
    """Quantas vezes cada categoria foi vista no rastreio, e com que confiança.

    Guardar o histórico inteiro é exigência de SUP-023: a categoria só pode ser
    decidida no fim, quando o cruzamento acontece, porque é a classe mais
    frequente ao longo do rastreio — e no frame do cruzamento a classe pode ser
    justamente a errada por oclusão.
    """

    ocorrencias: dict[Categoria, int] = field(default_factory=dict)
    confianca_somada: dict[Categoria, float] = field(default_factory=dict)

    def registrar(self, categoria: Categoria, confianca: float) -> None:
        self.ocorrencias[categoria] = self.ocorrencias.get(categoria, 0) + 1
        self.confianca_somada[categoria] = (
            self.confianca_somada.get(categoria, 0.0) + confianca
        )

    @property
    def vencedora(self) -> Categoria:
        """A categoria mais frequente, com desempate determinístico.

        SUP-023 não define o desempate; ele é fixado aqui, e precisa ser
        determinístico por causa de AC-014.5 (mesma entrada, mesma saída):

        1. maior número de ocorrências;
        2. empate → maior confiança somada;
        3. empate também nisso → menor classe COCO.

        O terceiro critério é o que tira a decisão da ordem de inserção do
        dicionário, que dependeria da ordem em que os frames chegaram.
        """
        return min(
            self.ocorrencias,
            key=lambda categoria: (
                -self.ocorrencias[categoria],
                -self.confianca_somada[categoria],
                _CLASSE_COCO_POR_CATEGORIA[categoria],
            ),
        )

    def confianca_media_da(self, categoria: Categoria) -> float:
        """Média das confianças das detecções daquela categoria.

        É o campo `confianca` do evento (T-07): média da categoria
        **vencedora**, e não a confiança do frame do cruzamento, que variaria
        com o instante em que o veículo tocou a linha.
        """
        return self.confianca_somada[categoria] / self.ocorrencias[categoria]


class Rastreador:
    """O rastreador de **um** clipe: ids compostos e histórico de classe.

    Instanciado por `rastreador_para_o_clipe`, nunca reaproveitado entre
    clipes (AC-007.3).
    """

    def __init__(self, minuto: int, bytetrack: RastreadorDoSupervision) -> None:
        self._minuto = minuto
        self._bytetrack = bytetrack
        self._historico: dict[str, _HistoricoDaCategoria] = {}

    @property
    def minuto(self) -> int:
        """O minuto do clipe, que é o prefixo de todo id deste rastreador."""
        return self._minuto

    @property
    def ids_de_rastreio(self) -> tuple[str, ...]:
        """Os ids compostos vistos neste clipe, na ordem em que apareceram."""
        return tuple(self._historico)

    def atualizar(self, deteccoes: sv.Detections) -> sv.Detections:
        """Rastreia as detecções do frame e devolve as mesmas com id composto.

        Acumula o histórico de classe de cada id no caminho, porque SUP-023
        decide a categoria só no cruzamento e o dado precisa estar guardado
        quando isso acontecer.
        """
        rastreadas = self._bytetrack.update_with_detections(deteccoes)
        if len(rastreadas) == 0:
            return rastreadas

        ids = [
            id_de_rastreio_composto(self._minuto, int(id_do_bytetrack))
            for id_do_bytetrack in rastreadas.tracker_id
        ]

        for indice, id_de_rastreio in enumerate(ids):
            categoria = self._categoria_da_deteccao(rastreadas, indice)
            if categoria is None:
                # Só chega aqui quem o detector já deixou passar (AC-005.1); a
                # guarda existe para não inventar categoria caso chegue.
                continue
            confianca = float(rastreadas.confidence[indice])
            self._historico.setdefault(
                id_de_rastreio, _HistoricoDaCategoria()
            ).registrar(categoria, confianca)

        rastreadas.data[CHAVE_DO_ID_DE_RASTREIO] = np.array(ids)
        return rastreadas

    def categoria_do_rastreio(self, id_de_rastreio: str) -> Categoria | None:
        """A classe mais frequente daquele rastreio (SUP-023).

        Devolve `None` para id desconhecido — inclusive o id de outro clipe,
        que é o que torna AC-007.3 verificável de fora.
        """
        historico = self._historico.get(id_de_rastreio)
        return None if historico is None else historico.vencedora

    def confianca_do_rastreio(self, id_de_rastreio: str) -> float | None:
        """A média das confianças das detecções da categoria vencedora."""
        historico = self._historico.get(id_de_rastreio)
        if historico is None:
            return None
        return historico.confianca_media_da(historico.vencedora)

    @staticmethod
    def _categoria_da_deteccao(
        deteccoes: sv.Detections, indice: int
    ) -> Categoria | None:
        """Lê a categoria da detecção, preferindo a já traduzida pelo detector."""
        categorias = deteccoes.data.get("categoria")
        if categorias is not None:
            return Categoria(str(categorias[indice]))
        return categoria_da_classe_coco(int(deteccoes.class_id[indice]))


def rastreador_para_o_clipe(
    minuto: int,
    fabrica_de_bytetrack: Callable[[], RastreadorDoSupervision] = criar_bytetrack,
) -> Rastreador:
    """Cria o rastreador **daquele** clipe, com estado zerado (AC-007.3).

    A fábrica é injetável (D-8) para que o teste dirija trajetórias sintéticas
    sem detector nem ByteTrack real.
    """
    return Rastreador(minuto, fabrica_de_bytetrack())

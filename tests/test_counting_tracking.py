"""Rastreamento por clipe e categoria por voto majoritário — T-08.

Critérios cobertos, de `.spec/features/contagem-veiculos/spec.md`:

- AC-007.3 — o estado do rastreador é reiniciado a cada clipe e nenhum id de
  rastreio é reaproveitado entre clipes. Reiniciar é literal: reaproveitar a
  instância entre clipes reintroduziria a continuidade de identidade que está
  em Fora de escopo.

Implementa SUP-018 (ByteTrack da `supervision`) e SUP-023 (a categoria do
rastreio é a classe mais frequente ao longo do rastreio, não a do frame do
cruzamento), além de D-9 (id composto `<minuto>:<id do ByteTrack>`).

O ByteTrack entra por fábrica injetável (D-8): estes testes dirigem
trajetórias sintéticas com um dublê e nenhum deles carrega o `.onnx` real nem
o rastreador de verdade.
"""

import numpy as np
import pytest
import supervision as sv

from auto_counter.counting.config import Categoria
from auto_counter.counting.tracking import rastreador_para_o_clipe

CLASSE_COCO_POR_CATEGORIA = {
    Categoria.CARRO: 2,
    Categoria.MOTO: 3,
    Categoria.ONIBUS: 5,
    Categoria.CAMINHAO: 7,
}


def deteccoes(*categorias_e_confiancas):
    """Monta as `sv.Detections` de um frame, no formato que o detector entrega.

    Cada argumento é `(categoria, confianca)`. A caixa em si não importa para
    esta tarefa — quem lê geometria é o cruzamento de T-09 —, mas precisa
    existir e ser distinta por detecção para que o dublê do ByteTrack tenha o
    que numerar.
    """
    caixas = np.array(
        [[10.0 * i, 20.0, 10.0 * i + 8.0, 40.0] for i, _ in enumerate(categorias_e_confiancas)],
        dtype=np.float32,
    ).reshape(-1, 4)
    classes = np.array(
        [CLASSE_COCO_POR_CATEGORIA[categoria] for categoria, _ in categorias_e_confiancas],
        dtype=int,
    )
    return sv.Detections(
        xyxy=caixas,
        confidence=np.array([confianca for _, confianca in categorias_e_confiancas], dtype=np.float32),
        class_id=classes,
        data={
            "classe_coco": classes,
            "categoria": np.array([categoria.value for categoria, _ in categorias_e_confiancas]),
        },
    )


class ByteTrackDuble:
    """Dublê do `ByteTrack` da `supervision` (D-8).

    Atribui os ids que o teste ditar, na ordem das detecções do frame, e conta
    quantas instâncias foram criadas — é assim que AC-007.3 fica verificável
    sem depender do estado interno do rastreador real.
    """

    instancias_criadas = 0

    def __init__(self, ids_por_frame):
        ByteTrackDuble.instancias_criadas += 1
        self._ids_por_frame = list(ids_por_frame)
        self._frame = 0

    def update_with_detections(self, deteccoes_do_frame):
        ids = self._ids_por_frame[self._frame]
        self._frame += 1
        resultado = sv.Detections(
            xyxy=deteccoes_do_frame.xyxy,
            confidence=deteccoes_do_frame.confidence,
            class_id=deteccoes_do_frame.class_id,
            tracker_id=np.array(ids, dtype=int),
            data=dict(deteccoes_do_frame.data),
        )
        return resultado


def fabrica_de(ids_por_frame):
    """Fábrica injetável que devolve um dublê novo a cada chamada."""
    return lambda: ByteTrackDuble(ids_por_frame)


def test_AC_007_3_estado_do_rastreador_e_reiniciado_a_cada_clipe():
    """Cada clipe recebe uma instância nova, e nada do clipe anterior sobra.

    O rastreador do minuto 4 não sabe responder pela categoria de um rastreio
    do minuto 3: se soubesse, o estado teria atravessado o corte.
    """
    ByteTrackDuble.instancias_criadas = 0
    fabrica = fabrica_de([[7]])

    do_minuto_3 = rastreador_para_o_clipe(3, fabrica_de_bytetrack=fabrica)
    do_minuto_3.atualizar(deteccoes((Categoria.CARRO, 0.9)))

    do_minuto_4 = rastreador_para_o_clipe(4, fabrica_de_bytetrack=fabrica)

    assert ByteTrackDuble.instancias_criadas == 2
    assert do_minuto_3 is not do_minuto_4
    assert do_minuto_3.categoria_do_rastreio("3:7") is Categoria.CARRO
    assert do_minuto_4.categoria_do_rastreio("3:7") is None


def test_AC_007_3_nenhum_id_de_rastreio_e_reaproveitado_entre_clipes():
    """O id 7 do minuto 3 e o id 7 do minuto 4 são ids diferentes (D-9)."""
    fabrica = fabrica_de([[7]])

    do_minuto_3 = rastreador_para_o_clipe(3, fabrica_de_bytetrack=fabrica)
    rastreados_no_3 = do_minuto_3.atualizar(deteccoes((Categoria.CARRO, 0.9)))

    do_minuto_4 = rastreador_para_o_clipe(4, fabrica_de_bytetrack=fabrica)
    rastreados_no_4 = do_minuto_4.atualizar(deteccoes((Categoria.MOTO, 0.8)))

    ids_do_3 = list(rastreados_no_3.data["id_de_rastreio"])
    ids_do_4 = list(rastreados_no_4.data["id_de_rastreio"])

    assert ids_do_3 == ["3:7"]
    assert ids_do_4 == ["4:7"]
    assert set(ids_do_3).isdisjoint(ids_do_4)
    assert do_minuto_3.ids_de_rastreio == ("3:7",)
    assert do_minuto_4.ids_de_rastreio == ("4:7",)


def test_categoria_do_rastreio_e_a_classe_mais_frequente_e_nao_a_do_ultimo_frame():
    """SUP-023: vence a classe mais frequente ao longo do rastreio.

    O rastreio 11 é visto como carro em três frames e como caminhão no último
    — a troca de classe por oclusão momentânea que SUP-023 quer neutralizar.
    A confiança devolvida é a média das detecções da categoria vencedora.
    """
    fabrica = fabrica_de([[11], [11], [11], [11]])
    rastreador = rastreador_para_o_clipe(2, fabrica_de_bytetrack=fabrica)

    rastreador.atualizar(deteccoes((Categoria.CARRO, 0.8)))
    rastreador.atualizar(deteccoes((Categoria.CARRO, 0.6)))
    rastreador.atualizar(deteccoes((Categoria.CARRO, 0.7)))
    rastreador.atualizar(deteccoes((Categoria.CAMINHAO, 0.99)))

    assert rastreador.categoria_do_rastreio("2:11") is Categoria.CARRO
    # `approx` porque a confiança trafega como float32 dentro das `Detections`.
    assert rastreador.confianca_do_rastreio("2:11") == pytest.approx(0.7)


def test_desempate_de_categoria_e_deterministico_entre_execucoes():
    """Empate na contagem → maior confiança somada; empate nisso → menor classe COCO.

    O desempate é fixado em T-08 porque SUP-023 não o define, e precisa ser
    determinístico por causa de AC-014.5. Duas execuções idênticas dão o mesmo
    resultado, e a ordem em que as detecções chegaram não muda o vencedor.
    """
    # Empate 2×2 desfeito pela confiança somada: ônibus (1,8) > caminhão (1,0).
    def executar():
        fabrica = fabrica_de([[4], [4], [4], [4]])
        rastreador = rastreador_para_o_clipe(9, fabrica_de_bytetrack=fabrica)
        rastreador.atualizar(deteccoes((Categoria.CAMINHAO, 0.5)))
        rastreador.atualizar(deteccoes((Categoria.ONIBUS, 0.9)))
        rastreador.atualizar(deteccoes((Categoria.CAMINHAO, 0.5)))
        rastreador.atualizar(deteccoes((Categoria.ONIBUS, 0.9)))
        return rastreador.categoria_do_rastreio("9:4")

    assert executar() is Categoria.ONIBUS
    assert executar() is executar()

    # Empate também na confiança somada: vence a de menor classe COCO —
    # carro (2) sobre moto (3) —, e a ordem de chegada não interfere.
    fabrica = fabrica_de([[1], [1]])
    numa_ordem = rastreador_para_o_clipe(9, fabrica_de_bytetrack=fabrica)
    numa_ordem.atualizar(deteccoes((Categoria.MOTO, 0.5)))
    numa_ordem.atualizar(deteccoes((Categoria.CARRO, 0.5)))

    na_outra = rastreador_para_o_clipe(9, fabrica_de_bytetrack=fabrica)
    na_outra.atualizar(deteccoes((Categoria.CARRO, 0.5)))
    na_outra.atualizar(deteccoes((Categoria.MOTO, 0.5)))

    assert numa_ordem.categoria_do_rastreio("9:1") is Categoria.CARRO
    assert na_outra.categoria_do_rastreio("9:1") is Categoria.CARRO

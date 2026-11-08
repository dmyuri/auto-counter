"""Cruzamento da linha de contagem com sentido — T-09.

Critérios cobertos, de `.spec/features/contagem-veiculos/spec.md`:

- AC-006.1 — a trajetória que passa de um lado da linha para o outro registra
  exatamente um evento com timestamp, categoria, sentido e id de rastreio;
- AC-006.2 — quem se aproxima da linha sem atravessar não registra nada;
- AC-006.3 — cada sentido recebe o rótulo configurado para aquela câmera, e o
  mapeamento é ancorado na normal de SUP-003: inverter a ordem dos pontos da
  linha inverte a normal e, com ela, os dois rótulos;
- AC-006.4 — ida e volta dentro do mesmo clipe gera dois eventos, um por
  sentido;
- AC-006.6 — no máximo um evento por par (id de rastreio, sentido) dentro do
  clipe.

As trajetórias são fabricadas ponto a ponto e passam pelo rastreador de T-08
com o dublê de ByteTrack (D-8): nenhum teste aqui carrega o `.onnx`, abre vídeo
ou instancia o rastreador real.

A linha dos testes é vertical, de `(100, 0)` a `(100, 200)`. Nessa ordem a
normal de SUP-003 — `(dx, dy) -> (-dy, dx)` normalizada — é `(-1, 0)`, ou seja,
aponta para a **esquerda**. Logo o veículo que anda da direita para a esquerda
cruza no sentido da normal e recebe `sentido_a`. Isso não é leitura da
documentação da `supervision`: é o que os dois testes de AC-006.3 fixam.
"""

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import supervision as sv

from auto_counter.cameras.geometry import normal_da_linha
from auto_counter.cameras.model import Camera, Linha, Ponto
from auto_counter.cameras.registry import carregar_registro
from auto_counter.counting.config import Categoria
from auto_counter.counting.crossing import AvaliadorDeCruzamento
from auto_counter.counting.tracking import rastreador_para_o_clipe

MINUTO = 3
FPS = 30.0
INICIO_DO_CLIPE = datetime(2026, 5, 4, 12, 30, 0, tzinfo=timezone.utc)

CLASSE_COCO_POR_CATEGORIA = {
    Categoria.CARRO: 2,
    Categoria.MOTO: 3,
    Categoria.ONIBUS: 5,
    Categoria.CAMINHAO: 7,
}


def camera(p1=(100, 0), p2=(100, 200)) -> Camera:
    """A câmera do teste, com rótulos de sentido próprios dela (AC-001.1).

    Os rótulos não são genéricos de propósito: se o código fixar "entrada" e
    "saída" — ou reaproveitar os de outra câmera —, estes testes acusam.
    """
    return Camera(
        resolucao={"largura": 1280, "altura": 720},
        id="000013",
        nome="Praça Renascença",
        sentido_a="CENTRO",
        sentido_b="ICARAI",
        linha=Linha(p1=Ponto(x=p1[0], y=p1[1]), p2=Ponto(x=p2[0], y=p2[1])),
    )


def deteccao_em(x: float, y: float, categoria: Categoria, confianca: float):
    """Uma detecção cujo **centro da base** da caixa é `(x, y)` (SUP-018).

    A caixa tem 10 px de largura e 20 de altura, com a base em `y`: é o ponto
    de contato com o solo que o avaliador tem de usar.
    """
    return (
        [x - 5.0, y - 20.0, x + 5.0, y],
        CLASSE_COCO_POR_CATEGORIA[categoria],
        categoria,
        confianca,
    )


def frame(*deteccoes) -> sv.Detections:
    """Monta as `sv.Detections` de um frame no formato que o detector entrega."""
    return sv.Detections(
        xyxy=np.array([caixa for caixa, _, _, _ in deteccoes], dtype=np.float32),
        confidence=np.array(
            [confianca for _, _, _, confianca in deteccoes], dtype=np.float32
        ),
        class_id=np.array([classe for _, classe, _, _ in deteccoes], dtype=int),
        data={
            "categoria": np.array([categoria.value for _, _, categoria, _ in deteccoes])
        },
    )


class ByteTrackDuble:
    """Dublê do `ByteTrack` (D-8): devolve os ids que o teste ditar."""

    def __init__(self, ids_por_frame):
        self._ids_por_frame = list(ids_por_frame)
        self._frame = 0

    def update_with_detections(self, deteccoes_do_frame):
        ids = self._ids_por_frame[self._frame]
        self._frame += 1
        if len(deteccoes_do_frame) == 0:
            return deteccoes_do_frame
        return sv.Detections(
            xyxy=deteccoes_do_frame.xyxy,
            confidence=deteccoes_do_frame.confidence,
            class_id=deteccoes_do_frame.class_id,
            tracker_id=np.array(ids, dtype=int),
            data=dict(deteccoes_do_frame.data),
        )


def eventos_da_trajetoria(
    posicoes,
    *,
    camera_do_teste=None,
    categoria=Categoria.CARRO,
    confianca=0.9,
    id_do_bytetrack=7,
):
    """Roda um veículo só pelas posições dadas e devolve os eventos gerados.

    Cada posição é o ponto de contato com o solo em um frame analisado. `None` é
    um frame em que o veículo não foi detectado.
    """
    quadros = [
        sv.Detections.empty()
        if posicao is None
        else frame(deteccao_em(*posicao, categoria, confianca))
        for posicao in posicoes
    ]
    ids_por_frame = [[] if posicao is None else [id_do_bytetrack] for posicao in posicoes]

    rastreador = rastreador_para_o_clipe(MINUTO, lambda: ByteTrackDuble(ids_por_frame))
    avaliador = AvaliadorDeCruzamento(
        camera=camera_do_teste or camera(),
        rastreador=rastreador,
        inicio_do_clipe=INICIO_DO_CLIPE,
        fps=FPS,
    )

    eventos = []
    for indice, quadro in enumerate(quadros):
        rastreadas = rastreador.atualizar(quadro)
        eventos.extend(avaliador.avaliar(rastreadas, indice_do_frame=indice))
    return eventos


def test_AC_006_1_trajetoria_que_atravessa_a_linha_gera_exatamente_um_evento_completo():
    """Um veículo que passa de um lado ao outro vira um evento, e só um.

    O evento carrega os quatro campos que AC-006.1 exige: timestamp (pelo
    início do clipe e o índice do frame, T-06), categoria (voto de SUP-023,
    T-08), sentido e id de rastreio (o composto de D-9).
    """
    eventos = eventos_da_trajetoria(
        [(140, 100), (120, 100), (80, 100), (60, 100)],
        categoria=Categoria.ONIBUS,
        id_do_bytetrack=7,
    )

    assert len(eventos) == 1
    evento = eventos[0]
    assert evento.categoria is Categoria.ONIBUS
    assert evento.id_de_rastreio == f"{MINUTO}:7"
    assert evento.sentido in {"CENTRO", "ICARAI"}
    assert evento.minuto == MINUTO
    # O cruzamento é visto no frame 2, que a 30 fps ainda está no segundo 0.
    assert evento.indice_do_frame == 2
    assert evento.timestamp == INICIO_DO_CLIPE
    # A linha vai de y=0 a y=200 e o veículo a cruza em y=100: meio da linha.
    assert evento.posicao_na_linha == 0.5


def test_AC_006_2_veiculo_que_se_aproxima_sem_atravessar_nao_gera_evento():
    """Chegar perto não é cruzar: sem tolerância de proximidade (T-09)."""
    eventos = eventos_da_trajetoria([(160, 100), (140, 100), (120, 100), (101, 100)])

    assert eventos == []


def test_AC_006_3_sentidos_opostos_recebem_os_rotulos_configurados_para_a_camera():
    """Dois veículos em direções opostas recebem rótulos diferentes da câmera.

    O da direita para a esquerda anda no sentido da normal `(-1, 0)` de
    SUP-003, e por isso recebe `sentido_a`; o oposto recebe `sentido_b`.
    """
    para_a_esquerda = eventos_da_trajetoria([(140, 100), (60, 100)], id_do_bytetrack=1)
    para_a_direita = eventos_da_trajetoria([(60, 140), (140, 140)], id_do_bytetrack=2)

    assert [evento.sentido for evento in para_a_esquerda] == ["CENTRO"]
    assert [evento.sentido for evento in para_a_direita] == ["ICARAI"]


def test_AC_006_3_inverter_a_ordem_dos_pontos_da_linha_troca_os_dois_rotulos():
    """O sentido sai da normal, não de uma convenção de lado do código.

    Invertendo `p1` e `p2` a normal de SUP-003 inverte, e a **mesma**
    trajetória passa a receber o outro rótulo. É esta a âncora do mapeamento.
    """
    invertida = camera(p1=(100, 200), p2=(100, 0))

    eventos = eventos_da_trajetoria([(140, 100), (60, 100)], camera_do_teste=invertida)

    assert [evento.sentido for evento in eventos] == ["ICARAI"]


def test_AC_006_4_ida_e_volta_no_mesmo_clipe_gera_dois_eventos_um_por_sentido():
    """Cruzar e voltar são dois cruzamentos, em sentidos diferentes."""
    eventos = eventos_da_trajetoria([(140, 100), (60, 100), (140, 100)])

    assert [evento.sentido for evento in eventos] == ["CENTRO", "ICARAI"]


def test_AC_006_6_mesmo_rastreio_cruzando_duas_vezes_no_mesmo_sentido_gera_um_evento():
    """O terceiro cruzamento repete o sentido do primeiro e é descartado.

    Ida, volta e ida de novo: três cruzamentos, dois pares (id, sentido).
    """
    eventos = eventos_da_trajetoria([(140, 100), (60, 100), (140, 100), (60, 100)])

    assert [evento.sentido for evento in eventos] == ["CENTRO", "ICARAI"]


def test_AC_006_6_oscilacao_de_fila_sobre_a_linha_nao_infla_a_contagem():
    """Veículo parado oscilando sobre a linha conta no máximo uma vez por sentido.

    É o caso de Q-004: sem AC-006.6 esta trajetória geraria sete eventos.
    """
    oscilacao = [(102, 100), (98, 100)] * 4

    eventos = eventos_da_trajetoria(oscilacao)

    assert len(eventos) == 2
    assert {evento.sentido for evento in eventos} == {"CENTRO", "ICARAI"}


def eventos_com_outro_veiculo_em_cena(posicoes):
    """Como `eventos_da_trajetoria`, com um segundo veículo parado em cena.

    O veículo 7 segue `posicoes` (com `None` nos frames em que não é detectado);
    o veículo 8 fica parado longe da linha em todos os frames. É o caso real: a
    moto some atrás de um carro enquanto o resto do trânsito continua detectado.
    """
    parado = deteccao_em(180, 50, Categoria.CARRO, 0.9)
    quadros, ids_por_frame = [], []
    for posicao in posicoes:
        if posicao is None:
            quadros.append(frame(parado))
            ids_por_frame.append([8])
        else:
            quadros.append(frame(deteccao_em(*posicao, Categoria.MOTO, 0.9), parado))
            ids_por_frame.append([7, 8])

    rastreador = rastreador_para_o_clipe(MINUTO, lambda: ByteTrackDuble(ids_por_frame))
    avaliador = AvaliadorDeCruzamento(
        camera=camera(),
        rastreador=rastreador,
        inicio_do_clipe=INICIO_DO_CLIPE,
        fps=FPS,
    )
    eventos = []
    for indice, quadro in enumerate(quadros):
        rastreadas = rastreador.atualizar(quadro)
        eventos.extend(avaliador.avaliar(rastreadas, indice_do_frame=indice))
    return eventos


def test_AC_006_1_veiculo_que_some_por_alguns_frames_e_reaparece_do_outro_lado_gera_um_evento():
    """Detecção intermitente não apaga o cruzamento (SUP-018).

    Moto atrás de um carro, ou com confiança oscilando, some da detecção por
    alguns frames enquanto o resto do trânsito segue detectado, e reaparece já
    do outro lado da linha. A troca de lado entre a última posição conhecida e
    a atual é um cruzamento, por mais frames que a trilha tenha ficado sem
    detecção dentro do clipe.
    """
    eventos = eventos_com_outro_veiculo_em_cena(
        [(140, 100), (120, 100), None, None, None, None, (80, 100), (60, 100)]
    )

    assert [(evento.sentido, evento.categoria) for evento in eventos] == [
        ("CENTRO", Categoria.MOTO)
    ]
    assert eventos[0].indice_do_frame == 6


def test_AC_006_2_veiculo_que_some_e_reaparece_do_mesmo_lado_nao_gera_evento():
    """Sumir e voltar sem trocar de lado não é cruzamento."""
    eventos = eventos_com_outro_veiculo_em_cena(
        [(140, 100), (120, 100), None, None, None, (110, 100), (105, 100)]
    )

    assert eventos == []


def test_AC_006_2_atravessar_o_prolongamento_da_linha_fora_do_segmento_nao_gera_evento():
    """A linha é o segmento entre `p1` e `p2`, não a reta inteira.

    Ela vai de y=0 a y=200; quem passa de um lado ao outro em y=300 está fora
    da faixa perpendicular ao segmento e não cruzou a linha de contagem.
    """
    eventos = eventos_da_trajetoria([(140, 300), (120, 300), (80, 300), (60, 300)])

    assert eventos == []


def test_AC_032_5_cruzamentos_na_linha_da_000012_recebem_os_rotulos_dela():
    """Os rótulos vêm da câmera da sessão, na linha calibrada da 000012.

    As trajetórias são derivadas da linha lida do registro (não há coordenada
    fixa): atravessam o ponto médio, uma a favor da normal de SUP-003 e outra
    contra. A 000012 usa os mesmos textos da 000013 por decisão do autor, então
    o teste repete a prova com rótulos de fixture, que só podem vir da câmera.
    """
    diretorio = Path(__file__).resolve().parents[1] / "config" / "cameras"
    por_id = {c.id: c for c in carregar_registro(diretorio).cameras}
    camera_000012 = por_id["000012"]

    linha = camera_000012.linha
    meio = ((linha.p1.x + linha.p2.x) / 2, (linha.p1.y + linha.p2.y) / 2)
    nx, ny = normal_da_linha(linha)

    def ponto(distancia):
        return (meio[0] + nx * distancia, meio[1] + ny * distancia)

    a_favor = [ponto(-60), ponto(-20), ponto(20), ponto(60)]
    contra = list(reversed(a_favor))

    com_rotulos_da_000012 = camera_000012
    com_rotulos_de_fixture = camera_000012.model_copy(
        update={"sentido_a": "FIXTURE-A", "sentido_b": "FIXTURE-B"}
    )
    for camera_do_teste, rotulo_a, rotulo_b in (
        (
            com_rotulos_da_000012,
            camera_000012.sentido_a,
            camera_000012.sentido_b,
        ),
        (com_rotulos_de_fixture, "FIXTURE-A", "FIXTURE-B"),
    ):
        eventos_a = eventos_da_trajetoria(
            a_favor, camera_do_teste=camera_do_teste, id_do_bytetrack=1
        )
        eventos_b = eventos_da_trajetoria(
            contra, camera_do_teste=camera_do_teste, id_do_bytetrack=2
        )

        assert [e.sentido for e in eventos_a] == [rotulo_a]
        assert [e.sentido for e in eventos_b] == [rotulo_b]

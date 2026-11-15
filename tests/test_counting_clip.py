"""Processamento de um clipe — T-11.

Critérios cobertos, de `.spec/features/contagem-veiculos/spec.md`:

- AC-005.3 — só os frames da taxa de amostragem declarada chegam ao detector,
  e os demais não passam por inferência, do começo ao fim do clipe;
- AC-006.1 — o veículo cuja trajetória atravessa a linha produz exatamente um
  evento, com timestamp, categoria, sentido e id de rastreio;
- AC-006.5 — o timestamp do evento é o Last-Modified do clipe somado ao
  deslocamento do frame do cruzamento, com resolução de 1 segundo;
- AC-007.3 — dois clipes processados em sequência usam rastreadores
  independentes, e nenhum id de rastreio é reaproveitado entre eles.

E, de `interface-sessao`, AC-012.5: o pedido de parada interrompe o clipe em
análise, e não só o clipe seguinte (SUP-108).

Mais o caminho de D-4: clipe ausente ou ilegível devolve resultado com motivo,
sem exceção.

O vídeo é sintético, escrito no próprio teste com `cv2.VideoWriter`, e o
detector é um dublê que devolve trajetórias fabricadas em função da ordem dos
frames analisados (D-8). Nenhum teste aqui carrega o `.onnx`. Se o codec `mp4v`
não existir na máquina, o teste **falha** — `audit.py` trata teste pulado igual
a teste que falhou, então não há `skip` condicional.

A linha é a mesma dos testes de T-09: vertical, de `(100, 0)` a `(100, 200)`.
A normal de SUP-003 aponta para a esquerda, então o veículo que anda da direita
para a esquerda recebe `sentido_a`.
"""

import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import cv2
import numpy as np
import pytest
import supervision as sv

from auto_counter.cameras.model import Camera, Linha, Ponto
from auto_counter.counting.clip import processar_clipe
from auto_counter.counting.config import Categoria, ConfiguracaoDoProcessamento
from auto_counter.counting.sampling import MOTIVO_NAO_ABRE, FrameAmostrado
from auto_counter.counting.session import ProcessamentoCancelado

LARGURA = 128
ALTURA = 48
LARGURA_DA_MARCA = 3
"""Colunas da faixa que identifica o frame. Três cabem 42 frames em 128 px."""
FPS = 30.0
INICIO_DO_CLIPE = datetime(2026, 5, 4, 12, 30, 0, tzinfo=timezone.utc)
MINUTO = 3

CLASSE_COCO_POR_CATEGORIA = {
    Categoria.CARRO: 2,
    Categoria.MOTO: 3,
    Categoria.ONIBUS: 5,
    Categoria.CAMINHAO: 7,
}


def camera() -> Camera:
    """A câmera do teste, com rótulos de sentido próprios dela (AC-001.1)."""
    return Camera(
        resolucao={"largura": 1280, "altura": 720},
        id="000013",
        nome="Praça Renascença",
        sentido_a="CENTRO",
        sentido_b="ICARAI",
        linha=Linha(p1=Ponto(x=100, y=0), p2=Ponto(x=100, y=200)),
    )


def _quadro_marcado(indice: int) -> np.ndarray:
    """Frame preto com uma faixa branca na coluna que codifica `indice`.

    A marca é **posicional**, e não um tom de cinza uniforme, porque o `mp4v` é
    um codec com perdas: o cinza volta da decodificação alterado, mas a coluna
    da faixa sobrevive. É isso que deixa o teste afirmar **quais** frames
    chegaram ao detector, e não apenas quantos — o que AC-005.3 exige.
    """
    imagem = np.zeros((ALTURA, LARGURA, 3), dtype=np.uint8)
    inicio = indice * LARGURA_DA_MARCA
    imagem[:, inicio : inicio + LARGURA_DA_MARCA] = 255
    return imagem


def _indice_do_quadro(imagem: np.ndarray) -> int:
    """Lê de volta o índice codificado na faixa branca do frame."""
    brilho_por_coluna = imagem.mean(axis=(0, 2))
    centro = int(np.argmax(brilho_por_coluna))
    return round((centro - (LARGURA_DA_MARCA - 1) / 2) / LARGURA_DA_MARCA)


def escreve_video(caminho: Path, quadros: int) -> Path:
    """MP4 válido e curto, com uma marca posicional própria por frame."""
    escritor = cv2.VideoWriter(
        str(caminho), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (LARGURA, ALTURA)
    )
    assert escritor.isOpened(), (
        "o codec mp4v não está disponível nesta máquina e a fixture de vídeo "
        "válido não pôde ser gerada"
    )
    try:
        for indice in range(quadros):
            escritor.write(_quadro_marcado(indice))
    finally:
        escritor.release()
    assert caminho.exists() and caminho.stat().st_size > 0
    return caminho


class DetectorDuble:
    """Dublê do detector (D-8): trajetória fabricada e registro do que recebeu.

    `posicoes_por_chamada` é o ponto de contato com o solo do veículo em cada
    frame **analisado**, na ordem em que eles chegam. Depois que a lista acaba,
    o dublê devolve frame vazio — o clipe continua, sem ninguém em cena.

    `indices_recebidos` guarda o índice codificado em cada frame entregue, que
    é o instrumento de AC-005.3.
    """

    def __init__(self, posicoes_por_chamada, categoria=Categoria.CARRO, confianca=0.9):
        self._posicoes = list(posicoes_por_chamada)
        self._categoria = categoria
        self._confianca = confianca
        self.indices_recebidos: list[int] = []

    def detectar(self, frame: np.ndarray) -> sv.Detections:
        self.indices_recebidos.append(_indice_do_quadro(frame))
        indice = len(self.indices_recebidos) - 1
        if indice >= len(self._posicoes) or self._posicoes[indice] is None:
            return sv.Detections.empty()
        x, y = self._posicoes[indice]
        return sv.Detections(
            xyxy=np.array([[x - 5.0, y - 20.0, x + 5.0, y]], dtype=np.float32),
            confidence=np.array([self._confianca], dtype=np.float32),
            class_id=np.array([CLASSE_COCO_POR_CATEGORIA[self._categoria]], dtype=int),
            data={"categoria": np.array([self._categoria.value])},
        )


class ByteTrackDuble:
    """Dublê do `ByteTrack` (D-8): id fixo para o único veículo em cena.

    Uma instância por clipe, como o real (AC-007.3) — a fábrica é chamada
    dentro de `processar_clipe`, e é isso que o teste de AC-007.3 verifica ao
    processar dois clipes com o mesmo `id_do_bytetrack` e exigir ids distintos.
    """

    def __init__(self, id_do_bytetrack: int = 7):
        self._id = id_do_bytetrack

    def update_with_detections(self, deteccoes):
        if len(deteccoes) == 0:
            return deteccoes
        return sv.Detections(
            xyxy=deteccoes.xyxy,
            confidence=deteccoes.confidence,
            class_id=deteccoes.class_id,
            tracker_id=np.array([self._id] * len(deteccoes), dtype=int),
            data=dict(deteccoes.data),
        )


def processa(
    caminho: Path,
    detector: DetectorDuble,
    *,
    minuto: int = MINUTO,
    amostragem: int = 3,
    id_do_bytetrack: int = 7,
    inicio_do_clipe: datetime = INICIO_DO_CLIPE,
    ao_gerar_evento=None,
    parada=None,
):
    """Roda `processar_clipe` com os dublês do teste."""
    return processar_clipe(
        caminho,
        camera=camera(),
        minuto=minuto,
        inicio_do_clipe=inicio_do_clipe,
        detector=detector,
        config=ConfiguracaoDoProcessamento(amostragem=amostragem),
        fabrica_de_bytetrack=lambda: ByteTrackDuble(id_do_bytetrack),
        **({} if ao_gerar_evento is None else {"ao_gerar_evento": ao_gerar_evento}),
        **({} if parada is None else {"parada": parada}),
    )


def test_AC_005_3_apenas_os_frames_amostrados_chegam_ao_detector_no_clipe_inteiro(
    tmp_path,
):
    """Com amostragem 3, o detector vê os frames 0, 3, 6... e mais nenhum.

    O total é `ceil(31 / 3)`: 31 quadros não é múltiplo de 3 de propósito, para
    que o último bloco fique incompleto. A identidade é conferida pela marca de
    cada frame, então o teste prova **quais** frames passaram por inferência,
    que é o que AC-005.3 pede.
    """
    quadros = 31
    amostragem = 3
    caminho = escreve_video(tmp_path / "clipe.mp4", quadros)
    detector = DetectorDuble([])

    resultado = processa(caminho, detector, amostragem=amostragem)

    assert len(detector.indices_recebidos) == math.ceil(quadros / amostragem)
    assert detector.indices_recebidos == list(range(0, quadros, amostragem))
    assert resultado.motivo is None


def test_AC_006_1_clipe_com_um_veiculo_atravessando_produz_um_evento_completo(tmp_path):
    """Um veículo cruzando a linha no clipe inteiro vira um evento, e só um.

    O evento carrega os quatro campos de AC-006.1: timestamp, categoria (voto
    de SUP-023), sentido (rótulo da câmera, AC-006.3) e id de rastreio (o
    composto de D-9).
    """
    caminho = escreve_video(tmp_path / "clipe.mp4", 31)
    detector = DetectorDuble(
        [(140, 100), (120, 100), (80, 100), (60, 100)],
        categoria=Categoria.ONIBUS,
    )

    resultado = processa(caminho, detector)

    assert resultado.motivo is None
    assert len(resultado.eventos) == 1
    evento = resultado.eventos[0]
    assert evento.categoria is Categoria.ONIBUS
    assert evento.sentido == "CENTRO"
    assert evento.id_de_rastreio == f"{MINUTO}:7"
    assert evento.minuto == MINUTO
    assert evento.timestamp.tzinfo is not None


def test_AC_006_5_timestamp_do_evento_usa_o_last_modified_do_clipe_e_o_frame_do_cruzamento(
    tmp_path,
):
    """O instante do evento é o início do clipe mais o deslocamento do frame.

    O veículo fica parado à direita da linha durante o primeiro segundo e só
    atravessa no décimo segundo frame analisado, que com amostragem 3 é o frame
    33 do clipe — deslocamento de 1 s a 30 fps.
    """
    caminho = escreve_video(tmp_path / "clipe.mp4", 40)
    # Frames analisados: 0, 3, ..., 39. O cruzamento cai entre o analisado de
    # índice 30 e o de índice 33, ou seja, é visto no frame 33.
    posicoes = [(140, 100)] * 11 + [(60, 100)] * 3
    detector = DetectorDuble(posicoes)

    resultado = processa(caminho, detector)

    assert len(resultado.eventos) == 1
    evento = resultado.eventos[0]
    assert evento.indice_do_frame == 33
    assert evento.timestamp == INICIO_DO_CLIPE + timedelta(seconds=1)


def test_AC_007_3_dois_clipes_processados_em_sequencia_usam_rastreadores_independentes(
    tmp_path,
):
    """Nenhum id de rastreio atravessa a emenda, mesmo com o mesmo id interno.

    Os dois clipes rodam com o mesmo `id_do_bytetrack`, que é o que o ByteTrack
    real faz ao reiniciar a numeração. Os ids expostos precisam ser distintos
    (D-9), e o histórico de categoria de um clipe não pode vazar para o outro.
    """
    primeiro = escreve_video(tmp_path / "clipe-3.mp4", 31)
    segundo = escreve_video(tmp_path / "clipe-4.mp4", 31)
    trajetoria = [(140, 100), (120, 100), (80, 100), (60, 100)]

    resultado_do_primeiro = processa(
        primeiro,
        DetectorDuble(trajetoria, categoria=Categoria.ONIBUS),
        minuto=3,
        id_do_bytetrack=7,
    )
    resultado_do_segundo = processa(
        segundo,
        DetectorDuble(trajetoria, categoria=Categoria.MOTO),
        minuto=4,
        id_do_bytetrack=7,
        inicio_do_clipe=INICIO_DO_CLIPE + timedelta(minutes=1),
    )

    ids_do_primeiro = {e.id_de_rastreio for e in resultado_do_primeiro.eventos}
    ids_do_segundo = {e.id_de_rastreio for e in resultado_do_segundo.eventos}
    assert ids_do_primeiro == {"3:7"}
    assert ids_do_segundo == {"4:7"}
    assert ids_do_primeiro.isdisjoint(ids_do_segundo)
    # O voto de categoria também é por clipe: o segundo não herda o do primeiro.
    assert resultado_do_primeiro.eventos[0].categoria is Categoria.ONIBUS
    assert resultado_do_segundo.eventos[0].categoria is Categoria.MOTO


def test_clipe_ausente_ou_ilegivel_devolve_resultado_com_motivo_e_sem_excecao(tmp_path):
    """D-4: nem arquivo que não existe nem arquivo corrompido derrubam a execução.

    Os dois devolvem resultado sem eventos e com o motivo preenchido, que é o
    que T-12 transforma em minuto sem dado. `fps` e duração ficam sem valor
    útil: não há clipe de onde lê-los, e a emenda de T-10 trata o minuto como
    não adjacente.
    """
    ausente = processa(tmp_path / "nao-existe.mp4", DetectorDuble([]))
    assert ausente.eventos == ()
    assert ausente.motivo

    corrompido_no_disco = tmp_path / "corrompido.mp4"
    corrompido_no_disco.write_bytes(b"isto nao e um mp4")
    corrompido = processa(corrompido_no_disco, DetectorDuble([]))
    assert corrompido.eventos == ()
    assert corrompido.motivo


# Ida e volta sobre a linha: dois cruzamentos, em sentidos e frames diferentes.
DOIS_CRUZAMENTOS = [(140, 100), (60, 100), (60, 100), (140, 100), (140, 100)]


def test_AC_016_2_gancho_recebe_cada_evento_na_ordem_e_antes_do_fim_do_clipe(tmp_path):
    """O evento sai do clipe no momento em que é gerado, não só no resultado.

    O gancho anota quantos frames o detector já tinha recebido quando cada
    evento chegou: tem de ser menos que o total do clipe.
    """
    caminho = escreve_video(tmp_path / "clipe.mp4", 31)
    detector = DetectorDuble(DOIS_CRUZAMENTOS)
    chegadas: list[tuple[object, float, int]] = []

    def gancho(evento, fps):
        chegadas.append((evento, fps, len(detector.indices_recebidos)))

    resultado = processa(caminho, detector, ao_gerar_evento=gancho)

    assert len(resultado.eventos) == 2
    assert [e for e, _, _ in chegadas] == list(resultado.eventos)
    assert all(fps == resultado.fps for _, fps, _ in chegadas)
    total_analisado = len(detector.indices_recebidos)
    assert all(vistos < total_analisado for _, _, vistos in chegadas)
    assert chegadas[0][2] < chegadas[1][2]


def test_AC_016_2_sem_gancho_o_resultado_do_clipe_e_identico(tmp_path):
    caminho = escreve_video(tmp_path / "clipe.mp4", 31)

    sem = processa(caminho, DetectorDuble(DOIS_CRUZAMENTOS))
    com = processa(
        caminho,
        DetectorDuble(DOIS_CRUZAMENTOS),
        ao_gerar_evento=lambda evento, fps: None,
    )

    assert sem == com


class AmostragemQueFalhaNoMeio:
    """Dublê de `AmostragemDoClipe`: entrega alguns frames e então falha.

    Preenche `motivo` ao fim, como o `except` de `sampling.py`.
    """

    def __init__(self, quadros: int):
        self._quadros = quadros
        self.fps: float | None = FPS
        self.total_de_frames = 0
        self.motivo: str | None = None

    def __iter__(self):
        for indice in range(self._quadros):
            self.total_de_frames = indice + 1
            yield FrameAmostrado(indice=indice, imagem=_quadro_marcado(indice))
        self.motivo = MOTIVO_NAO_ABRE


def test_AC_016_8_clipe_que_falha_no_meio_chama_o_gancho_e_devolve_sem_eventos(
    tmp_path, monkeypatch
):
    """O gancho já foi chamado quando a leitura falha; o resultado, não tem eventos.

    Quem desconta o minuto é a sessão (D-4); o clipe só mantém o contrato.
    """
    monkeypatch.setattr(
        "auto_counter.counting.clip.frames_amostrados",
        lambda caminho, amostragem: AmostragemQueFalhaNoMeio(6),
    )
    detector = DetectorDuble([(140, 100), (60, 100), (60, 100)])
    recebidos = []

    resultado = processa(
        tmp_path / "qualquer.mp4",
        detector,
        ao_gerar_evento=lambda evento, fps: recebidos.append(evento),
    )

    assert len(recebidos) == 1
    assert resultado.eventos == ()
    assert resultado.motivo == MOTIVO_NAO_ABRE


class ParadaPedidaDepoisDeNFrames:
    """A parada de AC-012.5 chegando durante a análise do clipe.

    Fica desligada até o detector ter recebido `frames` frames, que é o que
    acontece quando o usuário clica com o clipe já em andamento.
    """

    def __init__(self, detector: DetectorDuble, frames: int) -> None:
        self._detector = detector
        self._frames = frames

    def foi_pedida(self) -> bool:
        return len(self._detector.indices_recebidos) >= self._frames


class ParadaNunca:
    def foi_pedida(self) -> bool:
        return False


def test_AC_012_5_parada_pedida_no_meio_do_clipe_interrompe_antes_do_fim(tmp_path):
    """31 quadros com amostragem 3 são 11 frames analisados; a parada chega após 2.

    O detector não pode receber o terceiro: o clipe é interrompido no meio, sem
    esperar o fim dele.
    """
    caminho = escreve_video(tmp_path / "clipe.mp4", 31)
    detector = DetectorDuble([])
    parada = ParadaPedidaDepoisDeNFrames(detector, frames=2)

    with pytest.raises(ProcessamentoCancelado) as cancelamento:
        processa(caminho, detector, parada=parada)

    assert detector.indices_recebidos == [0, 3]
    assert str(MINUTO) in str(cancelamento.value)


def test_sem_parada_o_clipe_se_comporta_como_antes(tmp_path):
    caminho = escreve_video(tmp_path / "clipe.mp4", 31)

    sem = processa(caminho, DetectorDuble(DOIS_CRUZAMENTOS))
    com = processa(caminho, DetectorDuble(DOIS_CRUZAMENTOS), parada=ParadaNunca())

    assert sem == com

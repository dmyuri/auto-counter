"""Testes da contagem automática de um clipe de referência.

Comportamento definido em `.spec/features/validacao-acuracia/spec.md`:
AC-014.1 e AC-014.5. Vídeo sintético escrito por `cv2.VideoWriter`, com
detector e ByteTrack dublês: nenhum teste aqui carrega o `.onnx` nem lê o
`tests/ground_truth/` real. Se o codec `mp4v` não existir na máquina, o teste
falha, porque o `audit.py` trata teste pulado igual a teste que falhou.

A linha é vertical, de `(100, 0)` a `(100, 200)`: quem anda da direita para a
esquerda recebe `sentido_a`.
"""

import hashlib
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import cv2
import numpy as np
import pytest
import supervision as sv

from auto_counter.cameras.model import Camera, Linha, Ponto
from auto_counter.capture.manifest import diretorio_da_sessao, id_da_sessao
from auto_counter.counting.config import Categoria, ConfiguracaoDoProcessamento
from auto_counter.storage.connection import conectar
from auto_counter.storage.events import ler_eventos
from auto_counter.storage.sessions import ler_sessao
from auto_counter.validation.automatic import (
    ClipeDeReferenciaIlegivelError,
    contar_clipe,
)
from auto_counter.validation.model import ClipeDeReferencia, Condicao

LARGURA = 128
ALTURA = 48
FPS = 30.0
AMOSTRAGEM = 3
ID_CAMERA = "000013"
VERSAO_DO_MODELO = "yolo11n.onnx@0123456789ab"
LAST_MODIFIED = datetime(2026, 9, 8, 20, 15, 0, tzinfo=timezone.utc)

CLASSE_COCO_POR_CATEGORIA = {
    Categoria.CARRO: 2,
    Categoria.MOTO: 3,
    Categoria.ONIBUS: 5,
    Categoria.CAMINHAO: 7,
}

DIREITA = (110.0, 40.0)
ESQUERDA = (90.0, 40.0)
CRUZA_PARA_A_ESQUERDA = (DIREITA, ESQUERDA)


def camera() -> Camera:
    return Camera(
        id=ID_CAMERA,
        nome="Praça Renascença",
        sentido_a="Icaraí",
        sentido_b="Centro",
        linha=Linha(p1=Ponto(x=100, y=0), p2=Ponto(x=100, y=200)),
    )


class DetectorDuble:
    """Roteiro de posições e categorias, consumido na ordem dos frames analisados."""

    def __init__(self, roteiro, confianca: float = 0.9):
        self._roteiro = list(roteiro)
        self._confianca = confianca
        self.chamadas = 0

    def detectar(self, frame: np.ndarray) -> sv.Detections:
        indice = self.chamadas
        self.chamadas += 1
        if indice >= len(self._roteiro) or self._roteiro[indice] is None:
            return sv.Detections.empty()
        posicao, categoria = self._roteiro[indice]
        x, y = posicao
        return sv.Detections(
            xyxy=np.array([[x - 5.0, y - 20.0, x + 5.0, y]], dtype=np.float32),
            confidence=np.array([self._confianca], dtype=np.float32),
            class_id=np.array([CLASSE_COCO_POR_CATEGORIA[categoria]], dtype=int),
            data={"categoria": np.array([categoria.value])},
        )


class ByteTrackDuble:
    """Id fixo para o único veículo em cena, igual em todos os clipes."""

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


def cruzamento(categoria: Categoria = Categoria.CARRO):
    return [(posicao, categoria) for posicao in CRUZA_PARA_A_ESQUERDA]


def escreve_video(caminho: Path, quadros: int = 6) -> Path:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    escritor = cv2.VideoWriter(
        str(caminho), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (LARGURA, ALTURA)
    )
    assert escritor.isOpened(), (
        "o codec mp4v não está disponível nesta máquina e a fixture de vídeo "
        "válido não pôde ser gerada"
    )
    try:
        for _ in range(quadros):
            escritor.write(np.zeros((ALTURA, LARGURA, 3), dtype=np.uint8))
    finally:
        escritor.release()
    assert caminho.stat().st_size > 0
    return caminho


def clipe_de_referencia(
    raiz: Path,
    condicao: Condicao = Condicao.PICO,
    *,
    last_modified: datetime = LAST_MODIFIED,
    quadros: int = 6,
    video_valido: bool = True,
) -> ClipeDeReferencia:
    caminho_video = raiz / "clipes" / f"{condicao.value}.mp4"
    if video_valido:
        escreve_video(caminho_video, quadros)
    else:
        caminho_video.parent.mkdir(parents=True, exist_ok=True)
        caminho_video.write_bytes(b"isto nao e um mp4")
    return ClipeDeReferencia(
        condicao=condicao,
        id_camera=ID_CAMERA,
        last_modified=last_modified,
        etag='"65f1a2-1e8480"',
        caminho_csv=raiz / f"{condicao.value}.csv",
        caminho_video=caminho_video,
    )


def conta(clipe, detector, dir_trabalho: Path):
    return contar_clipe(
        clipe,
        camera=camera(),
        detector=detector,
        config=ConfiguracaoDoProcessamento(amostragem=AMOSTRAGEM),
        versao_do_modelo=VERSAO_DO_MODELO,
        dir_trabalho=dir_trabalho,
        fabrica_de_bytetrack=ByteTrackDuble,
    )


def _sha256(caminho: Path) -> str:
    return hashlib.sha256(caminho.read_bytes()).hexdigest()


def test_AC_014_1_a_contagem_automatica_e_a_dos_eventos_gravados_no_banco(tmp_path):
    clipe = clipe_de_referencia(tmp_path / "gt")
    dir_trabalho = tmp_path / "trabalho"

    contagem = conta(clipe, DetectorDuble(cruzamento(Categoria.MOTO)), dir_trabalho)

    id_sessao = id_da_sessao(ID_CAMERA, LAST_MODIFIED)
    assert contagem.id_sessao == id_sessao
    with conectar(dir_trabalho) as conexao:
        assert ler_sessao(conexao, id_sessao) is not None
        gravados = ler_eventos(conexao, id_sessao)

    assert len(gravados) == 1
    assert len(contagem.veiculos) == 1
    veiculo = contagem.veiculos[0]
    assert veiculo.id_de_rastreio == gravados[0].id_de_rastreio
    assert veiculo.sentido == gravados[0].sentido == camera().sentido_a
    assert veiculo.categoria is Categoria.MOTO
    assert contagem.sha256_do_video == _sha256(clipe.caminho_video)


def test_AC_014_1_o_instante_automatico_e_o_deslocamento_desde_o_last_modified(
    tmp_path,
):
    # 150 quadros a 30 fps, amostragem 3: o cruzamento nos frames analisados 30 e
    # 31 acontece nos quadros 90 e 93, ou seja, a 3 s do início do clipe
    clipe = clipe_de_referencia(tmp_path / "gt", quadros=150)
    roteiro = [None] * 30 + cruzamento()

    contagem = conta(clipe, DetectorDuble(roteiro), tmp_path / "trabalho")

    assert len(contagem.veiculos) == 1
    instante = contagem.veiculos[0].instante_s
    assert isinstance(instante, Decimal)
    assert instante == Decimal(3)


def test_AC_014_5_contar_um_clipe_nao_escreve_nada_no_diretorio_do_ground_truth(
    tmp_path,
):
    raiz = tmp_path / "gt"
    clipe = clipe_de_referencia(raiz)
    (raiz / "pico.csv").write_text("instante_s,categoria,sentido\n", encoding="utf-8")

    def retrato():
        return {
            str(caminho.relative_to(raiz)): (
                caminho.stat().st_mtime_ns,
                _sha256(caminho),
            )
            for caminho in sorted(raiz.rglob("*"))
            if caminho.is_file()
        }

    antes = retrato()
    conta(clipe, DetectorDuble(cruzamento()), tmp_path / "trabalho")

    assert retrato() == antes
    assert sorted(p.name for p in raiz.rglob("*")) == sorted(
        ["clipes", "pico.mp4", "pico.csv"]
    )


def test_AC_014_5_contar_um_clipe_nao_toca_o_banco_do_diretorio_de_dados_real(
    tmp_path, monkeypatch
):
    dados_reais = tmp_path / "dados_reais"
    dados_reais.mkdir()
    monkeypatch.setenv("AUTO_COUNTER_DATA_DIR", str(dados_reais))
    clipe = clipe_de_referencia(tmp_path / "gt")

    conta(clipe, DetectorDuble(cruzamento()), tmp_path / "trabalho")

    assert os.environ["AUTO_COUNTER_DATA_DIR"] == str(dados_reais)
    assert list(dados_reais.iterdir()) == []


def test_cada_clipe_vira_uma_sessao_propria_sem_emenda_com_outro(tmp_path):
    # dois minutos consecutivos, com um cruzamento no fim de um e outro no início
    # do seguinte: numa sessão única a emenda os contaria uma vez só
    raiz = tmp_path / "gt"
    primeiro = clipe_de_referencia(raiz, Condicao.PICO, last_modified=LAST_MODIFIED)
    segundo = clipe_de_referencia(
        raiz,
        Condicao.FORA_PICO,
        last_modified=LAST_MODIFIED + timedelta(minutes=1),
    )
    dir_trabalho = tmp_path / "trabalho"
    # um único detector atravessa os dois clipes, como a sessão real faria
    detector = DetectorDuble(cruzamento() + cruzamento())

    c1 = conta(primeiro, detector, dir_trabalho)
    c2 = conta(segundo, detector, dir_trabalho)

    assert c1.id_sessao != c2.id_sessao
    assert len(c1.veiculos) == 1
    assert len(c2.veiculos) == 1
    assert diretorio_da_sessao(dir_trabalho, c1.id_sessao).is_dir()
    assert diretorio_da_sessao(dir_trabalho, c2.id_sessao).is_dir()
    with conectar(dir_trabalho) as conexao:
        assert len(ler_eventos(conexao, c1.id_sessao)) == 1
        assert len(ler_eventos(conexao, c2.id_sessao)) == 1


def test_clipe_que_nao_processa_vira_erro_de_clipe_ilegivel_com_condicao_e_motivo(
    tmp_path,
):
    clipe = clipe_de_referencia(tmp_path / "gt", Condicao.NOTURNO, video_valido=False)

    with pytest.raises(ClipeDeReferenciaIlegivelError) as erro:
        conta(clipe, DetectorDuble([]), tmp_path / "trabalho")

    assert erro.value.condicao is Condicao.NOTURNO
    assert erro.value.motivo
    assert "noturno" in str(erro.value)
    assert erro.value.motivo in str(erro.value)
    # o vídeo de referência continua no disco: nada o apaga
    assert clipe.caminho_video.read_bytes() == b"isto nao e um mp4"


def test_clipe_de_outra_camera_e_recusado_em_vez_de_reaproveitar_a_calibracao(tmp_path):
    clipe = clipe_de_referencia(tmp_path / "gt")
    outra = ClipeDeReferencia(
        condicao=clipe.condicao,
        id_camera="000099",
        last_modified=clipe.last_modified,
        etag=clipe.etag,
        caminho_csv=clipe.caminho_csv,
        caminho_video=clipe.caminho_video,
    )

    with pytest.raises(ValueError) as erro:
        conta(outra, DetectorDuble([]), tmp_path / "trabalho")

    assert "000099" in str(erro.value)
    assert ID_CAMERA in str(erro.value)

"""Obtenção do primeiro frame legível do clipe da câmera — T-07.

Critério coberto, de `.spec/features/configuracao-camera/spec.md`: AC-002.1,
na parte que diz de onde vem o frame do preview — SUP-005 define que é o
primeiro frame legível de um clipe baixado na hora pelo próprio comando, e
SUP-006 que a leitura é do OpenCV sobre um MP4 progressivo, sem FFmpeg.

Nenhum teste aqui toca o servidor da NitTrans: o download é servido por um
dublê de transporte HTTP, e o clipe é um MP4 mínimo gerado na hora pelo
próprio OpenCV. A base URL vem de `monkeypatch`, nunca do `.env` real.

Falha de rede, HTTP de erro e arquivo que não abre como vídeo têm de virar
erro tratado com mensagem, nunca exceção crua escapando para o usuário
(`CLAUDE.md`). Retry não é desta feature: é de `captura-clipes` (AC-004.1).
"""

import tempfile

import cv2
import httpx
import numpy as np
import pytest

from auto_counter.cameras.frame import FrameIndisponivelError, primeiro_frame
from auto_counter.cameras.model import Camera
from auto_counter.cameras.url import VARIAVEL_BASE_URL

LARGURA_DO_CLIPE = 64
ALTURA_DO_CLIPE = 48
BASE_URL_DE_TESTE = "https://exemplo.invalido/videos"


@pytest.fixture
def camera_000013() -> Camera:
    """A câmera do MVP, com id string de zeros à esquerda (SUP-001)."""
    return Camera(
        resolucao={"largura": 64, "altura": 48},
        id="000013",
        nome="Local de teste",
        sentido_a="sentido A",
        sentido_b="sentido B",
        linha={"p1": {"x": 10, "y": 24}, "p2": {"x": 54, "y": 24}},
    )


@pytest.fixture
def base_url_configurada(monkeypatch):
    monkeypatch.setenv(VARIAVEL_BASE_URL, BASE_URL_DE_TESTE)


@pytest.fixture
def temporarios_em(tmp_path, monkeypatch):
    """Manda os arquivos temporários para `tmp_path`, para poder conferi-los.

    O clipe baixado tem de ser apagado ao final, inclusive no caminho de erro;
    isolar o diretório temporário é o que torna isso observável.
    """
    destino = tmp_path / "temporarios"
    destino.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(destino))
    return destino


@pytest.fixture(scope="session")
def bytes_do_clipe(tmp_path_factory) -> bytes:
    """MP4 mínimo de 5 frames, escrito e lido pelo próprio OpenCV (SUP-006).

    O primeiro frame é preto e cada frame seguinte é mais claro, para que o
    teste consiga afirmar que o frame devolvido é mesmo o primeiro.
    """
    caminho = tmp_path_factory.mktemp("clipe") / "last_video.mp4"
    escritor = cv2.VideoWriter(
        str(caminho),
        cv2.VideoWriter_fourcc(*"mp4v"),
        30,
        (LARGURA_DO_CLIPE, ALTURA_DO_CLIPE),
    )
    assert escritor.isOpened(), "OpenCV não conseguiu escrever o MP4 de fixture"
    for indice in range(5):
        escritor.write(
            np.full(
                (ALTURA_DO_CLIPE, LARGURA_DO_CLIPE, 3), indice * 50, dtype=np.uint8
            )
        )
    escritor.release()
    return caminho.read_bytes()


def cliente_que_responde(resposta) -> httpx.Client:
    """Cliente HTTP dublê: `resposta` é uma `httpx.Response` ou uma exceção."""
    pedidos = []

    def responder(pedido: httpx.Request) -> httpx.Response:
        pedidos.append(pedido)
        if isinstance(resposta, Exception):
            raise resposta
        return resposta

    cliente = httpx.Client(transport=httpx.MockTransport(responder))
    cliente.pedidos = pedidos
    return cliente


def test_AC_002_1_primeiro_frame_legivel_e_devolvido_com_as_dimensoes_do_video(
    camera_000013, base_url_configurada, bytes_do_clipe, temporarios_em
):
    cliente = cliente_que_responde(httpx.Response(200, content=bytes_do_clipe))

    resultado = primeiro_frame(camera_000013, cliente=cliente)

    # As dimensões saem do vídeo, não de constante no código (SUP-007).
    assert (resultado.largura, resultado.altura) == (LARGURA_DO_CLIPE, ALTURA_DO_CLIPE)
    assert resultado.imagem.shape == (ALTURA_DO_CLIPE, LARGURA_DO_CLIPE, 3)
    # É o primeiro frame do clipe (o preto), não um frame qualquer.
    assert int(resultado.imagem.mean()) < 25

    # GET único na URL derivada do id (AC-001.4), e nada sobra no temporário.
    assert [pedido.method for pedido in cliente.pedidos] == ["GET"]
    assert str(cliente.pedidos[0].url) == f"{BASE_URL_DE_TESTE}/000013/last_video.mp4"
    assert list(temporarios_em.iterdir()) == []


@pytest.mark.parametrize(
    "resposta",
    [
        httpx.Response(404),
        httpx.Response(500),
        httpx.ConnectError("sem rota para o host"),
        httpx.ReadTimeout("estourou o tempo de leitura"),
    ],
)
def test_AC_002_1_falha_de_download_vira_erro_tratado_e_nao_excecao_crua(
    camera_000013, base_url_configurada, temporarios_em, resposta
):
    cliente = cliente_que_responde(resposta)

    with pytest.raises(FrameIndisponivelError) as erro:
        primeiro_frame(camera_000013, cliente=cliente)

    mensagem = str(erro.value)
    assert "000013" in mensagem
    assert mensagem.strip() != ""
    # O temporário do caminho de erro também é apagado.
    assert list(temporarios_em.iterdir()) == []


def test_AC_002_1_arquivo_que_nao_abre_como_video_vira_erro_tratado(
    camera_000013, base_url_configurada, temporarios_em
):
    cliente = cliente_que_responde(
        httpx.Response(200, content=b"isto nao e um mp4, e texto puro")
    )

    with pytest.raises(FrameIndisponivelError) as erro:
        primeiro_frame(camera_000013, cliente=cliente)

    assert "000013" in str(erro.value)
    assert list(temporarios_em.iterdir()) == []


def test_AC_002_1_video_sem_frame_legivel_vira_erro_tratado(
    camera_000013, base_url_configurada, temporarios_em, bytes_do_clipe
):
    # MP4 legítimo no cabeçalho mas truncado: abre como vídeo e não entrega
    # frame nenhum. É o caso "clipe corrompido" que não pode derrubar a
    # execução com exceção crua (`CLAUDE.md`).
    cliente = cliente_que_responde(
        httpx.Response(200, content=bytes_do_clipe[: len(bytes_do_clipe) // 3])
    )

    with pytest.raises(FrameIndisponivelError):
        primeiro_frame(camera_000013, cliente=cliente)

    assert list(temporarios_em.iterdir()) == []


def test_AC_002_1_base_url_ausente_falha_antes_de_qualquer_requisicao(
    camera_000013, monkeypatch, temporarios_em
):
    # AC-001.5 continua valendo aqui: sem a variável, nem chega a baixar.
    monkeypatch.delenv(VARIAVEL_BASE_URL, raising=False)
    cliente = cliente_que_responde(httpx.Response(200, content=b""))

    with pytest.raises(Exception):
        primeiro_frame(camera_000013, cliente=cliente)

    assert cliente.pedidos == []
    assert list(temporarios_em.iterdir()) == []

"""Obtenção do primeiro frame legível do clipe de uma câmera.

Comportamento em `.spec/features/configuracao-camera/spec.md`: AC-002.1, na
parte que define a origem do frame do preview. SUP-005 diz que o frame é o
primeiro frame legível de um clipe baixado na hora pelo próprio comando, e
SUP-006 que a leitura é do OpenCV sobre um MP4 progressivo obtido por HTTP —
FFmpeg não é dependência deste projeto.

As dimensões voltam junto com o frame porque é delas que a validação de
limites da linha precisa (AC-002.2), e elas são lidas do vídeo da própria
câmera, nunca fixadas em código (SUP-007).

Tudo o que pode dar errado no caminho — rede, HTTP de erro, arquivo que não
abre como vídeo, clipe sem frame legível — vira `FrameIndisponivelError` com
mensagem dizendo o que falhou, em vez de exceção crua chegando ao usuário
(`CLAUDE.md`). **Não há retry aqui**: retry é da feature `captura-clipes`
(AC-004.1) e antecipá-lo mudaria o comportamento de uma spec pela outra.

O download é um GET único para arquivo temporário, e o temporário é apagado ao
final inclusive quando a leitura falha.
"""

import os
import tempfile
from dataclasses import dataclass

import cv2
import httpx
import numpy as np

from auto_counter.cameras.model import Camera
from auto_counter.cameras.url import url_do_clipe

TEMPO_LIMITE_PADRAO = 60.0
"""Segundos para o GET do clipe, quando o chamador não traz o próprio cliente.

Os clipes medidos na câmera do MVP têm ~32 MB; o limite é folgado de propósito
para que uma rede lenta não vire falha de download.
"""

MAXIMO_DE_FRAMES_TENTADOS = 30
"""Quantos frames tentar antes de desistir de achar um legível.

"Primeiro frame legível" (SUP-005) admite que os primeiros venham quebrados,
mas um clipe que não entrega nada em 1 segundo de vídeo está corrompido, e
insistir até o fim de um clipe de 59,93 s só adiaria o mesmo erro.
"""


class FrameIndisponivelError(Exception):
    """Não foi possível obter um frame do clipe da câmera (AC-002.1).

    Um único tipo para os quatro modos de falha — rede, HTTP de erro, arquivo
    que não abre como vídeo e clipe sem frame legível — porque, para quem
    chama, o desfecho é o mesmo: não há frame. Qual dos quatro foi está na
    mensagem, que sempre cita a câmera.
    """


@dataclass(frozen=True)
class FrameDaCamera:
    """Um frame do clipe e as dimensões reais do vídeo de onde ele saiu."""

    imagem: np.ndarray
    largura: int
    altura: int


def _baixa_clipe(camera: Camera, url: str, cliente: httpx.Client | None) -> str:
    """GET único do clipe para um arquivo temporário. Devolve o caminho."""
    proprio = cliente is None
    cliente = cliente or httpx.Client(timeout=TEMPO_LIMITE_PADRAO)
    descritor, caminho = tempfile.mkstemp(prefix=f"clipe_{camera.id}_", suffix=".mp4")
    try:
        with os.fdopen(descritor, "wb") as arquivo:
            resposta = cliente.get(url, follow_redirects=True)
            resposta.raise_for_status()
            arquivo.write(resposta.content)
    except httpx.HTTPStatusError as erro:
        os.unlink(caminho)
        raise FrameIndisponivelError(
            f"câmera {camera.id}: o servidor respondeu "
            f"{erro.response.status_code} ao baixar o clipe"
        ) from erro
    except httpx.HTTPError as erro:
        os.unlink(caminho)
        raise FrameIndisponivelError(
            f"câmera {camera.id}: falha de rede ao baixar o clipe ({erro})"
        ) from erro
    except OSError as erro:
        os.unlink(caminho)
        raise FrameIndisponivelError(
            f"câmera {camera.id}: falha ao gravar o clipe baixado ({erro})"
        ) from erro
    finally:
        if proprio:
            cliente.close()
    return caminho


def _le_primeiro_frame(camera: Camera, caminho: str) -> FrameDaCamera:
    """Primeiro frame legível do arquivo, com as dimensões do próprio frame."""
    captura = cv2.VideoCapture(caminho)
    try:
        if not captura.isOpened():
            raise FrameIndisponivelError(
                f"câmera {camera.id}: o arquivo baixado não abre como vídeo"
            )
        for _ in range(MAXIMO_DE_FRAMES_TENTADOS):
            lido, imagem = captura.read()
            if lido and imagem is not None and imagem.size:
                altura, largura = imagem.shape[:2]
                return FrameDaCamera(imagem=imagem, largura=largura, altura=altura)
        raise FrameIndisponivelError(
            f"câmera {camera.id}: o clipe abriu como vídeo mas não entregou "
            f"nenhum frame legível nos primeiros {MAXIMO_DE_FRAMES_TENTADOS} frames"
        )
    finally:
        captura.release()


def primeiro_frame(
    camera: Camera, *, cliente: httpx.Client | None = None
) -> FrameDaCamera:
    """Baixa o clipe da câmera e devolve o primeiro frame legível.

    A URL é a montada a partir do id (AC-001.4); sem `AUTO_COUNTER_BASE_URL` a
    falha acontece aqui, antes de qualquer requisição (AC-001.5).

    `cliente` existe para o teste injetar um transporte dublê: nenhum teste
    deste projeto toca o servidor da NitTrans. Quando é o chamador que traz o
    cliente, é ele quem o fecha.
    """
    url = url_do_clipe(camera)
    caminho = _baixa_clipe(camera, url, cliente)
    try:
        return _le_primeiro_frame(camera, caminho)
    finally:
        try:
            os.unlink(caminho)
        except OSError:
            pass

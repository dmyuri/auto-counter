"""Validação de que o clipe baixado é vídeo legível, e descarte do que não é.

Comportamento definido em `.spec/features/captura-clipes/spec.md`: AC-004.3,
com a definição de "vídeo legível" vindo de SUP-011 — o arquivo abre no OpenCV
**e** o primeiro e o último frame são decodificáveis.

Esse é o critério inteiro. Não há duração mínima, tamanho em bytes ou contagem
de frames esperada: SUP-011 define o que é legível, e acrescentar condição aqui
seria alterar a spec durante a implementação (`CLAUDE.md`).

Nenhum erro do OpenCV escapa: arquivo truncado, container inválido ou ponteiro
nulo viram `False`, porque quem chama (o laço de captura, T-07) precisa marcar
o minuto como não capturado e seguir, não tratar exceção. A captura é liberada
em `finally`.

Marcar o minuto como não capturado é de T-07; aqui a decisão é só sobre o
arquivo.
"""

from pathlib import Path

import cv2


def _primeiro_frame_decodifica(captura: "cv2.VideoCapture") -> bool:
    """Lê o frame inicial do arquivo já aberto."""
    lido, imagem = captura.read()
    return bool(lido) and imagem is not None and bool(imagem.size)


def _ultimo_frame_decodifica(captura: "cv2.VideoCapture") -> bool:
    """Lê o último frame do arquivo já aberto.

    Caminho preferido: posicionar em `CAP_PROP_FRAME_COUNT - 1` e ler. Alguns
    containers — inclusive MP4 truncado, que é justamente o caso de AC-004.3 —
    não têm índice confiável e o seek não leva a lugar nenhum; então o caminho
    alternativo é ler sequencialmente até o fim e usar o último frame obtido.

    Arquivo que não entrega nenhum frame não é legível, pelos dois caminhos.
    """
    total = int(captura.get(cv2.CAP_PROP_FRAME_COUNT))
    if total > 0 and captura.set(cv2.CAP_PROP_POS_FRAMES, total - 1):
        lido, imagem = captura.read()
        if lido and imagem is not None and imagem.size:
            return True

    # Caminho sequencial: o seek não funcionou neste arquivo.
    ultimo_valido = False
    while True:
        lido, imagem = captura.read()
        if not lido or imagem is None or not imagem.size:
            break
        ultimo_valido = True
    return ultimo_valido


def e_legivel(caminho: Path | str) -> bool:
    """Diz se o arquivo é vídeo legível no sentido de SUP-011.

    Devolve `False` — nunca levanta — para qualquer arquivo que não abra no
    OpenCV, que não entregue o primeiro frame, ou que não entregue o último.
    """
    captura = None
    try:
        captura = cv2.VideoCapture(str(caminho))
        if not captura.isOpened():
            return False
        if not _primeiro_frame_decodifica(captura):
            return False
        # O primeiro frame já foi consumido; reposiciona para que o caminho
        # sequencial do último frame percorra o arquivo inteiro.
        captura.set(cv2.CAP_PROP_POS_FRAMES, 0)
        return _ultimo_frame_decodifica(captura)
    except (cv2.error, OSError, ValueError):
        return False
    finally:
        if captura is not None:
            try:
                captura.release()
            except cv2.error:
                pass


def descartar(caminho: Path | str) -> None:
    """Apaga o clipe ilegível do diretório da sessão (AC-004.3).

    Um `.mp4` inválido não pode ficar no diretório fingindo ser material
    capturado. Arquivo que já sumiu não é erro: o descarte pode ser chamado
    mais de uma vez no mesmo caminho.
    """
    try:
        Path(caminho).unlink()
    except (FileNotFoundError, IsADirectoryError, PermissionError, OSError):
        pass

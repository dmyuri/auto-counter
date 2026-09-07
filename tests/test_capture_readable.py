"""Validação de que o clipe baixado é vídeo legível — T-05.

Critério coberto, de `.spec/features/captura-clipes/spec.md`:

- AC-004.3 — um clipe baixado cujo conteúdo não abre como vídeo legível é
  descartado, o minuto é marcado como não capturado e a execução continua, sem
  exceção não tratada escapando para o usuário.

"Vídeo legível" é o que SUP-011 define e nada além disso: o arquivo abre no
OpenCV **e** o primeiro e o último frame são decodificáveis. Nenhum teste daqui
exige duração mínima, tamanho em bytes ou contagem de frames — inventar
critério seria mudar a spec durante a implementação (`CLAUDE.md`).

A marcação do minuto como não capturado é do laço de captura (T-07); o que se
prova aqui é a decisão sobre o arquivo e o descarte dele.

As fixtures são geradas no próprio teste, em diretório temporário: nenhum vídeo
entra no repositório e nenhum teste baixa nada. Se o codec `mp4v` não existir na
máquina, o teste **falha** — `audit.py` trata teste pulado igual a teste que
falhou, então não há `skip` condicional aqui.
"""

from pathlib import Path

import cv2
import numpy as np

from auto_counter.capture.readable import descartar, e_legivel

LARGURA = 320
ALTURA = 240
QUADROS = 30
"""Um segundo a 30 fps: o menor clipe que ainda tem primeiro e último frame
distintos, que é o que SUP-011 manda decodificar."""

BYTES_PRESERVADOS_NO_FIM = 2000
"""Cauda do arquivo que a corrupção não toca, para o `moov` do MP4 sobreviver.

O índice do MP4 fica no fim do arquivo: sem ele o vídeo não abre e o teste
provaria o caso do arquivo ilegível, não o do último frame indecodificável."""


def _escreve_video(caminho: Path) -> Path:
    """MP4 válido e curto, escrito com `cv2.VideoWriter` no codec `mp4v`."""
    escritor = cv2.VideoWriter(
        str(caminho), cv2.VideoWriter_fourcc(*"mp4v"), 30.0, (LARGURA, ALTURA)
    )
    assert escritor.isOpened(), (
        "o codec mp4v não está disponível nesta máquina e a fixture de vídeo "
        "válido não pôde ser gerada"
    )
    try:
        for indice in range(QUADROS):
            quadro = np.full((ALTURA, LARGURA, 3), indice * 8, dtype=np.uint8)
            escritor.write(quadro)
    finally:
        escritor.release()
    assert caminho.exists() and caminho.stat().st_size > 0
    return caminho


def test_AC_004_3_arquivo_que_nao_abre_como_video_e_considerado_ilegivel(tmp_path):
    lixo = tmp_path / "minuto-01.mp4"
    lixo.write_bytes(b"isto nao e um container de video" * 64)

    assert e_legivel(lixo) is False


def test_AC_004_3_video_truncado_com_ultimo_frame_indecodificavel_e_ilegivel(tmp_path):
    # Cortar o fim do arquivo levaria junto o `moov` do MP4 e o vídeo nem
    # abriria — seria o mesmo caminho do teste anterior. Para exercitar de fato
    # o último frame, o corte é no meio: o `moov` e o começo do `mdat` ficam
    # intactos, e o miolo dos dados de vídeo vira zeros.
    inteiro = _escreve_video(tmp_path / "inteiro.mp4")
    bytes_do_video = bytearray(inteiro.read_bytes())
    inicio_do_corte = len(bytes_do_video) // 2
    fim_do_corte = len(bytes_do_video) - BYTES_PRESERVADOS_NO_FIM
    assert inicio_do_corte < fim_do_corte
    for posicao in range(inicio_do_corte, fim_do_corte):
        bytes_do_video[posicao] = 0
    truncado = tmp_path / "minuto-02.mp4"
    truncado.write_bytes(bytes(bytes_do_video))

    # O arquivo continua abrindo e entregando o primeiro frame: o que falta é o
    # último, que é o outro lado da definição de SUP-011.
    captura = cv2.VideoCapture(str(truncado))
    try:
        assert captura.isOpened()
        primeiro_lido, _ = captura.read()
        assert primeiro_lido
    finally:
        captura.release()

    assert e_legivel(truncado) is False


def test_AC_004_3_video_integro_e_considerado_legivel(tmp_path):
    valido = _escreve_video(tmp_path / "minuto-03.mp4")

    assert e_legivel(valido) is True


def test_AC_004_3_clipe_ilegivel_e_descartado_do_diretorio_da_sessao(tmp_path):
    dir_sessao = tmp_path / "sessions" / "000013-20260907T120000Z"
    dir_sessao.mkdir(parents=True)
    ilegivel = dir_sessao / "minuto-04.mp4"
    ilegivel.write_bytes(b"\x00\x01\x02\x03" * 128)

    assert e_legivel(ilegivel) is False
    descartar(ilegivel)

    assert not ilegivel.exists()
    # O diretório da sessão sobrevive: o descarte é do arquivo, não da sessão.
    assert dir_sessao.is_dir()
    # Descartar de novo o que já sumiu não é erro.
    descartar(ilegivel)


def test_AC_004_3_falha_de_leitura_nao_escapa_como_excecao_nao_tratada(
    tmp_path, monkeypatch
):
    valido = _escreve_video(tmp_path / "minuto-05.mp4")

    class CapturaQueExplode:
        """Dublê do OpenCV falhando no meio da leitura, como um container
        inválido faz: o erro vira `False`, nunca exceção para o usuário."""

        def __init__(self, *_args, **_kwargs):
            self.liberada = False

        def isOpened(self):
            return True

        def get(self, _propriedade):
            raise cv2.error("ponteiro nulo ao consultar a contagem de frames")

        def read(self):
            raise cv2.error("falha ao decodificar o frame")

        def release(self):
            self.liberada = True

    monkeypatch.setattr(cv2, "VideoCapture", CapturaQueExplode)

    assert e_legivel(valido) is False

"""Contagem de um vídeo enviado — T-06 de `processamento-upload`.

Critérios cobertos, de `.spec/features/processamento-upload/spec.md`:

- AC-028.4 — os eventos usam a linha e os rótulos da câmera, com o limiar de
  confiança da sessão ao vivo;
- AC-028.5 — ⌊D × min(F, 10)⌋ frames analisados, com tolerância de 1;
- AC-028.6 — um cruzamento na virada do minuto gera um único evento, porque o
  rastreador não é reiniciado dentro do vídeo;
- AC-028.8 — o evento fica no minuto do seu deslocamento dentro do vídeo;
- AC-028.9 — a falha no minuto m mantém os anteriores e marca m em diante.

Mais SUP-091, SUP-100 e D-3, D-4, D-5 e D-12 do `_tasks.md`.

Os vídeos são escritos em `tmp_path` com `cv2.VideoWriter`; detector e ByteTrack
são dublês (D-8). Nenhum teste carrega o `.onnx`.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import cv2
import numpy as np
import pytest

from auto_counter.counting.config import Categoria, ConfiguracaoDoProcessamento
from auto_counter.counting.detector import Detector
from auto_counter.counting.sampling import (
    MOTIVO_NAO_ABRE,
    AmostragemDoClipe,
    FrameAmostrado,
)
from auto_counter.counting.session import ProcessamentoCancelado
from auto_counter.counting.video import processar_video
from tests.test_counting_detector import SessaoDuble, saida_bruta
from tests.test_counting_session import (
    DIREITA,
    ESQUERDA,
    ByteTrackDuble,
    DetectorDuble,
    ParadaDuble,
    camera,
    roteiro_do_clipe,
)

T0 = datetime(2026, 11, 7, 14, 30, 0, tzinfo=timezone.utc)


def escreve_video(caminho: Path, *, fps: float, quadros: int, lado=None) -> Path:
    largura, altura = lado if lado else (128, 48)
    escritor = cv2.VideoWriter(
        str(caminho), cv2.VideoWriter_fourcc(*"mp4v"), fps, (largura, altura)
    )
    assert escritor.isOpened(), (
        "o codec mp4v não está disponível nesta máquina e a fixture de vídeo "
        "válido não pôde ser gerada"
    )
    try:
        for _ in range(quadros):
            escritor.write(np.zeros((altura, largura, 3), dtype=np.uint8))
    finally:
        escritor.release()
    assert caminho.exists() and caminho.stat().st_size > 0
    return caminho


def cruza_no_frame(frame: int, total: int, sentido=(DIREITA, ESQUERDA)):
    """Roteiro de um veículo que muda de lado no frame `frame`."""
    antes, depois = sentido
    return roteiro_do_clipe([antes] * frame + [depois] * (total - frame))


def conta(caminho, *, detector, minutos=1, minuto_inicial=1, posicao=1, **ganchos):
    return processar_video(
        caminho,
        camera=camera(),
        posicao=posicao,
        nome=f"video-{posicao}.mp4",
        minuto_inicial=minuto_inicial,
        minutos=minutos,
        inicio_da_linha_do_tempo=T0,
        detector=detector,
        config=ConfiguracaoDoProcessamento(),
        fabrica_de_bytetrack=ByteTrackDuble,
        **ganchos,
    )


class Registro:
    """Anota a ordem em que os ganchos de D-12 são chamados."""

    def __init__(self):
        self.chamadas = []

    def iniciar(self, minuto):
        self.chamadas.append(("iniciar", minuto))

    def descartar(self, minuto):
        self.chamadas.append(("descartar", minuto))

    def resolver(self, minuto, com_dado):
        self.chamadas.append(("resolver", minuto, com_dado))

    def aceitar(self, evento):
        self.chamadas.append(("aceitar", evento.minuto))

    def ganchos(self):
        return {
            "ao_iniciar_minuto": self.iniciar,
            "ao_descartar_minuto": self.descartar,
            "ao_resolver_minuto": self.resolver,
        }


class AmostragemQueFalhaNoMeio(AmostragemDoClipe):
    """Entrega os frames até `ate` (inclusive) a 10 fps e então falha."""

    ate = 700

    def __iter__(self):
        self.fps = 10.0
        for indice in range(0, self.ate + 1):
            self.total_de_frames = indice + 1
            yield FrameAmostrado(
                indice=indice, imagem=np.zeros((48, 128, 3), dtype=np.uint8)
            )
        self.motivo = MOTIVO_NAO_ABRE


def com_amostragem_que_falha(monkeypatch, ate):
    class Falha(AmostragemQueFalhaNoMeio):
        pass

    Falha.ate = ate
    monkeypatch.setattr(
        "auto_counter.counting.video.frames_amostrados_por_taxa",
        lambda caminho, taxa: Falha(caminho, 1),
    )


def test_AC_028_4_evento_usa_a_linha_e_os_rotulos_da_camera(tmp_path):
    caminho = escreve_video(tmp_path / "v.mp4", fps=10, quadros=20)

    da_direita = conta(
        caminho, detector=DetectorDuble(cruza_no_frame(5, 20, (DIREITA, ESQUERDA)))
    )
    da_esquerda = conta(
        caminho, detector=DetectorDuble(cruza_no_frame(5, 20, (ESQUERDA, DIREITA)))
    )

    [a] = da_direita.eventos
    [b] = da_esquerda.eventos
    assert a.sentido == camera().sentido_a == "CENTRO"
    assert b.sentido == camera().sentido_b == "ICARAI"
    assert a.categoria is Categoria.CARRO


def test_AC_028_4_deteccao_abaixo_do_limiar_nao_gera_evento(tmp_path):
    """O detector real, com o limiar padrão da sessão ao vivo (SUP-016)."""
    caminho = escreve_video(
        tmp_path / "v.mp4", fps=10, quadros=6, lado=(640, 640)
    )

    def sessao(confianca):
        saidas = [
            saida_bruta([(110, 30, 10, 20, 2, confianca)]),
            saida_bruta([(110, 30, 10, 20, 2, confianca)]),
            saida_bruta([(110, 30, 10, 20, 2, confianca)]),
            saida_bruta([(90, 30, 10, 20, 2, confianca)]),
            saida_bruta([(90, 30, 10, 20, 2, confianca)]),
            saida_bruta([(90, 30, 10, 20, 2, confianca)]),
        ]

        class Roteirizada(SessaoDuble):
            def __init__(self):
                super().__init__(saidas[0])
                self.n = 0

            def run(self, nomes, entradas):
                saida = saidas[min(self.n, len(saidas) - 1)]
                self.n += 1
                return [saida]

        return Roteirizada()

    config = ConfiguracaoDoProcessamento()
    acima = conta(caminho, detector=Detector(sessao(0.9), config))
    abaixo = conta(caminho, detector=Detector(sessao(0.2), config))

    assert len(acima.eventos) == 1
    assert abaixo.eventos == ()


def test_AC_028_5_detector_chamado_floor_D_vezes_min_F_10_mais_ou_menos_1(tmp_path):
    caminho = escreve_video(tmp_path / "v.mp4", fps=30, quadros=180)
    detector = DetectorDuble([])

    resultado = conta(caminho, detector=detector)

    assert abs(detector.chamadas - 60) <= 1
    assert resultado.frames_analisados == detector.chamadas


def test_AC_028_6_veiculo_cruzando_na_virada_do_minuto_gera_um_evento(tmp_path):
    caminho = escreve_video(tmp_path / "v.mp4", fps=10, quadros=620)

    resultado = conta(
        caminho, detector=DetectorDuble(cruza_no_frame(600, 620)), minutos=2
    )

    [evento] = resultado.eventos
    assert evento.minuto == 2
    assert evento.deslocamento_segundos == 60
    assert resultado.minutos_com_dado == (1, 2)
    assert resultado.falhou is False


def test_AC_028_6_ids_de_rastreio_tem_o_prefixo_do_minuto_inicial_do_video(tmp_path):
    caminho = escreve_video(tmp_path / "v.mp4", fps=10, quadros=20)

    resultado = conta(
        caminho, detector=DetectorDuble(cruza_no_frame(5, 20)), minuto_inicial=4
    )

    [evento] = resultado.eventos
    assert evento.id_de_rastreio == "4:7"


def test_AC_028_8_evento_fica_no_minuto_do_seu_deslocamento(tmp_path):
    caminho = escreve_video(tmp_path / "v.mp4", fps=10, quadros=800)

    resultado = conta(
        caminho,
        detector=DetectorDuble(cruza_no_frame(750, 800)),
        minutos=2,
        minuto_inicial=4,
    )

    [evento] = resultado.eventos
    assert evento.minuto == 5
    assert evento.video == 1
    assert evento.deslocamento_segundos == 75
    assert resultado.minutos_com_dado == (4, 5)


def test_D_3_evento_alem_do_ultimo_minuto_fica_no_ultimo(tmp_path):
    caminho = escreve_video(tmp_path / "v.mp4", fps=10, quadros=650)

    # O vídeo foi declarado com 1 minuto, mas tem 65 s: o cruzamento em 62 s
    # fica no último minuto declarado.
    resultado = conta(
        caminho, detector=DetectorDuble(cruza_no_frame(620, 650)), minutos=1
    )

    [evento] = resultado.eventos
    assert evento.minuto == 1
    assert evento.deslocamento_segundos == 62
    assert resultado.falhou is False


def test_SUP_100_timestamp_e_deslocamento_do_evento(tmp_path):
    caminho = escreve_video(tmp_path / "v.mp4", fps=10, quadros=200)

    resultado = conta(
        caminho, detector=DetectorDuble(cruza_no_frame(124, 200)), minuto_inicial=3
    )

    [evento] = resultado.eventos
    assert evento.deslocamento_segundos == 12
    assert evento.timestamp == T0 + timedelta(seconds=120 + 12)


def test_AC_028_9_falha_no_minuto_m_mantem_os_anteriores_e_marca_m_em_diante(
    tmp_path, monkeypatch
):
    com_amostragem_que_falha(monkeypatch, ate=700)
    # Um cruzamento no minuto 1 (frame 100) e outro, de volta, no minuto 2
    # (frame 650), que precisa sair junto com o minuto que falhou.
    roteiro = roteiro_do_clipe(
        [DIREITA] * 100 + [ESQUERDA] * 550 + [DIREITA] * 51
    )

    resultado = conta(
        tmp_path / "nao-importa.mp4", detector=DetectorDuble(roteiro), minutos=3
    )

    assert resultado.falhou is True
    assert [e.deslocamento_segundos for e in resultado.eventos] == [10]
    assert resultado.minutos_com_dado == (1,)
    assert [m.minuto for m in resultado.minutos_sem_dado] == [2, 3]
    assert all(
        m.motivo == f"{MOTIVO_NAO_ABRE} (vídeo 1: video-1.mp4)"
        for m in resultado.minutos_sem_dado
    )
    assert resultado.leu_algum_frame is True


def test_AC_028_9_descarte_so_do_minuto_m(tmp_path, monkeypatch):
    com_amostragem_que_falha(monkeypatch, ate=700)
    registro = Registro()

    conta(
        tmp_path / "nao-importa.mp4",
        detector=DetectorDuble([]),
        minutos=3,
        **registro.ganchos(),
    )

    assert registro.chamadas == [
        ("iniciar", 1),
        ("resolver", 1, True),
        ("iniciar", 2),
        ("descartar", 2),
        ("resolver", 2, False),
        ("resolver", 3, False),
    ]


def test_D_4_video_que_termina_cedo_falha_no_minuto_seguinte_ao_ultimo_frame(
    tmp_path,
):
    caminho = escreve_video(tmp_path / "v.mp4", fps=10, quadros=600)
    registro = Registro()

    resultado = conta(
        caminho, detector=DetectorDuble([]), minutos=2, **registro.ganchos()
    )

    assert resultado.falhou is True
    assert resultado.minutos_com_dado == (1,)
    assert [m.minuto for m in resultado.minutos_sem_dado] == [2]
    assert registro.chamadas == [
        ("iniciar", 1),
        ("resolver", 1, True),
        ("descartar", 2),
        ("resolver", 2, False),
    ]


def test_D_4_video_ilegivel_falha_no_minuto_1_sem_ler_frame(tmp_path):
    caminho = tmp_path / "quebrado.mp4"
    caminho.write_bytes(b"isto nao e um video")
    registro = Registro()

    resultado = conta(
        caminho, detector=DetectorDuble([]), minutos=2, **registro.ganchos()
    )

    assert resultado.falhou is True
    assert resultado.leu_algum_frame is False
    assert resultado.eventos == ()
    assert resultado.minutos_com_dado == ()
    assert [m.minuto for m in resultado.minutos_sem_dado] == [1, 2]
    assert "vídeo 1: video-1.mp4" in resultado.minutos_sem_dado[0].motivo
    assert registro.chamadas == [
        ("descartar", 1),
        ("resolver", 1, False),
        ("resolver", 2, False),
    ]


def test_D_12_parada_pedida_antes_de_um_minuto_levanta_processamento_cancelado(
    tmp_path,
):
    caminho = escreve_video(tmp_path / "v.mp4", fps=10, quadros=20)
    parada = ParadaDuble()
    parada.pedida = True

    with pytest.raises(ProcessamentoCancelado) as erro:
        conta(
            caminho,
            detector=DetectorDuble([]),
            posicao=3,
            parada=parada,
        )

    assert erro.value.video == 3


def test_fim_normal_dentro_do_ultimo_minuto_nao_e_falha(tmp_path):
    caminho = escreve_video(tmp_path / "v.mp4", fps=10, quadros=700)

    resultado = conta(caminho, detector=DetectorDuble([]), minutos=2)

    assert resultado.falhou is False
    assert resultado.minutos_com_dado == (1, 2)
    assert resultado.minutos_sem_dado == ()

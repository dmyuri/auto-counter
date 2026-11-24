"""Detector: inferência ONNX com filtro de classe e de confiança — T-04.

Critérios cobertos, de `.spec/features/contagem-veiculos/spec.md`:

- AC-005.1 — só carro, moto, ônibus e caminhão sobrevivem; qualquer outra
  classe do modelo (pessoa, bicicleta, semáforo e demais) é descartada **antes**
  do rastreamento, isto é, antes de sair do detector;
- AC-005.2 — detecção com confiança abaixo do limiar configurado não é entregue
  ao rastreador.

A sessão de inferência entra por parâmetro (D-8): estes testes usam uma sessão
dublê que devolve saída bruta fabricada, e nenhum deles carrega o `.onnx` real
— que não está no repositório.
"""

import numpy as np
import pytest
import supervision as sv

from auto_counter.counting.config import Categoria, ConfiguracaoDoProcessamento
from auto_counter.counting.detector import Detector

CLASSES_COCO = 80
"""O vocabulário do YOLO11n. A saída bruta tem 4 + 80 linhas."""


class SessaoDuble:
    """Dublê do `onnxruntime.InferenceSession` (D-8).

    Devolve a saída bruta fabricada que o teste montou e guarda a entrada
    recebida, para que o teste do letterbox confira o que foi enviado ao
    modelo.
    """

    def __init__(self, saida_bruta: np.ndarray) -> None:
        self._saida_bruta = saida_bruta
        self.entrada_recebida: np.ndarray | None = None

    def get_inputs(self):
        class _Entrada:
            name = "images"

        return [_Entrada()]

    def get_outputs(self):
        class _Saida:
            name = "output0"

        return [_Saida()]

    def run(self, nomes_de_saida, entradas):
        (self.entrada_recebida,) = entradas.values()
        return [self._saida_bruta]


def saida_bruta(caixas):
    """Monta a saída `(1, 84, N)` do YOLO11n a partir de `(cx, cy, w, h, classe, confianca)`.

    As coordenadas estão no espaço da entrada de 640×640, que é onde o modelo
    fala; devolvê-las ao espaço do frame original é trabalho do detector.
    """
    bruta = np.zeros((1, 4 + CLASSES_COCO, len(caixas)), dtype=np.float32)
    for coluna, (cx, cy, largura, altura, classe, confianca) in enumerate(caixas):
        bruta[0, 0, coluna] = cx
        bruta[0, 1, coluna] = cy
        bruta[0, 2, coluna] = largura
        bruta[0, 3, coluna] = altura
        bruta[0, 4 + classe, coluna] = confianca
    return bruta


def frame_preto(largura=640, altura=640):
    """Frame BGR do OpenCV. O conteúdo não importa: quem detecta é o dublê."""
    return np.zeros((altura, largura, 3), dtype=np.uint8)


def test_AC_005_1_deteccoes_de_pessoa_e_bicicleta_sao_descartadas_antes_do_rastreamento():
    # Pessoa (0), bicicleta (1) e semáforo (9) com confiança alta: o que as
    # descarta é a classe, não o limiar.
    sessao = SessaoDuble(
        saida_bruta(
            [
                (100, 100, 40, 40, 0, 0.95),
                (200, 200, 40, 40, 1, 0.90),
                (300, 300, 40, 40, 9, 0.99),
                (400, 400, 40, 40, 2, 0.80),
            ]
        )
    )
    detector = Detector(sessao, ConfiguracaoDoProcessamento())

    deteccoes = detector.detectar(frame_preto())

    assert len(deteccoes) == 1
    assert list(deteccoes.data["categoria"]) == [Categoria.CARRO.value]
    assert list(deteccoes.data["classe_coco"]) == [2]


def test_AC_005_1_apenas_carro_moto_onibus_e_caminhao_chegam_ao_rastreador():
    sessao = SessaoDuble(
        saida_bruta(
            [
                (60, 60, 20, 20, 2, 0.90),
                (160, 160, 20, 20, 3, 0.88),
                (260, 260, 20, 20, 5, 0.86),
                (360, 360, 20, 20, 7, 0.84),
                (460, 460, 20, 20, 0, 0.99),
                (560, 560, 20, 20, 11, 0.99),
            ]
        )
    )
    detector = Detector(sessao, ConfiguracaoDoProcessamento())

    deteccoes = detector.detectar(frame_preto())

    assert isinstance(deteccoes, sv.Detections)
    assert sorted(deteccoes.data["categoria"]) == sorted(
        [
            Categoria.CARRO.value,
            Categoria.MOTO.value,
            Categoria.ONIBUS.value,
            Categoria.CAMINHAO.value,
        ]
    )
    # A classe COCO original acompanha a categoria traduzida: SUP-023 precisa
    # do histórico por rastreio e AC-008.2 persiste a confiança.
    assert sorted(deteccoes.data["classe_coco"]) == [2, 3, 5, 7]
    assert deteccoes.confidence is not None


def test_AC_005_2_deteccao_abaixo_do_limiar_nao_e_entregue_ao_rastreador():
    configuracao = ConfiguracaoDoProcessamento()
    sessao = SessaoDuble(
        saida_bruta(
            [
                (100, 100, 30, 30, 2, configuracao.limiar_de_confianca - 0.01),
                (300, 300, 30, 30, 7, 0.90),
            ]
        )
    )
    detector = Detector(sessao, configuracao)

    deteccoes = detector.detectar(frame_preto())

    assert len(deteccoes) == 1
    assert list(deteccoes.data["classe_coco"]) == [7]


def test_AC_005_2_deteccao_exatamente_no_limiar_e_mantida():
    configuracao = ConfiguracaoDoProcessamento()
    sessao = SessaoDuble(
        saida_bruta([(100, 100, 30, 30, 2, configuracao.limiar_de_confianca)])
    )
    detector = Detector(sessao, configuracao)

    deteccoes = detector.detectar(frame_preto())

    # "abaixo do limiar" (AC-005.2) exclui o próprio limiar: o corte é
    # estritamente menor, senão o valor declarado na spec seria inalcançável.
    assert len(deteccoes) == 1
    assert list(deteccoes.data["classe_coco"]) == [2]


def test_AC_005_1_coordenadas_voltam_ao_frame_original_apos_o_letterbox():
    # Frame 1280×720: o letterbox escala por 0,5 e sobra faixa preta em cima e
    # embaixo. Uma caixa no centro da entrada de 640 tem que voltar ao centro
    # do frame de 1280×720.
    largura, altura = 1280, 720
    escala = 640 / largura  # 0,5 — o lado maior é quem manda
    preenchimento_vertical = (640 - altura * escala) / 2  # 140

    caixa_original = (640.0, 360.0, 200.0, 100.0)  # cx, cy, w, h no frame
    cx = caixa_original[0] * escala
    cy = caixa_original[1] * escala + preenchimento_vertical
    sessao = SessaoDuble(
        saida_bruta(
            [
                (
                    cx,
                    cy,
                    caixa_original[2] * escala,
                    caixa_original[3] * escala,
                    2,
                    0.90,
                )
            ]
        )
    )
    detector = Detector(sessao, ConfiguracaoDoProcessamento())

    deteccoes = detector.detectar(frame_preto(largura, altura))

    assert len(deteccoes) == 1
    esperado = np.array([[540.0, 310.0, 740.0, 410.0]])  # xyxy no frame original
    assert deteccoes.xyxy == pytest.approx(esperado, abs=1.0)

    # E a entrada enviada ao modelo é NCHW de 640×640 (SUP-015).
    assert sessao.entrada_recebida.shape == (1, 3, 640, 640)
    assert sessao.entrada_recebida.dtype == np.float32
    assert sessao.entrada_recebida.max() <= 1.0

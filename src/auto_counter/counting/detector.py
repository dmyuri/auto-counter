"""Detector: inferência ONNX com filtro de classe e de confiança — T-04.

Comportamento definido em `.spec/features/contagem-veiculos/spec.md`: AC-005.1
(só carro, moto, ônibus e caminhão sobrevivem) e AC-005.2 (detecção abaixo do
limiar não é entregue ao rastreador). Implementa SUP-015: YOLO11n em ONNX
Runtime na CPU, com entrada de 640×640.

Os dois filtros acontecem **aqui**, antes de qualquer coisa sair do detector,
porque os dois critérios exigem literalmente que o descarte seja anterior ao
rastreamento.

A sessão de inferência entra por parâmetro (D-8): quem constrói o
`onnxruntime.InferenceSession` é o chamador, e é por isso que a suíte rápida
roda sem o `.onnx` no disco.
"""

from typing import Any, Protocol

import cv2
import numpy as np
import supervision as sv

from .config import ConfiguracaoDoProcessamento, categoria_da_classe_coco

LIMIAR_DE_NMS = 0.45
"""IoU acima do qual duas caixas da mesma classe são a mesma detecção."""

NUMERO_DE_THREADS = 4
"""Núcleos da máquina de referência (AC-005.4).

Explícito na construção da sessão real porque o orçamento de 100 ms por frame
não pode depender do palpite do runtime sobre a máquina.
"""

_COORDENADAS_DA_CAIXA = 4
"""As quatro primeiras linhas da saída bruta são `cx, cy, w, h`."""

_CINZA_DO_LETTERBOX = 114
"""Cinza convencional do preenchimento do YOLO, para não inventar borda preta."""


class SessaoDeInferencia(Protocol):
    """O contrato que o detector usa do `onnxruntime.InferenceSession` (D-8)."""

    def get_inputs(self) -> list[Any]: ...

    def run(self, nomes_de_saida: Any, entradas: dict[str, Any]) -> list[Any]: ...


def criar_sessao(caminho_do_modelo, numero_de_threads: int = NUMERO_DE_THREADS):
    """Constrói a sessão real do ONNX Runtime na CPU (SUP-015).

    `onnxruntime` é importado aqui dentro pelo mesmo motivo de `model.py`: os
    testes que dublam a sessão não precisam do runtime carregado para rodar.
    """
    import onnxruntime

    opcoes = onnxruntime.SessionOptions()
    opcoes.intra_op_num_threads = numero_de_threads
    opcoes.inter_op_num_threads = numero_de_threads
    return onnxruntime.InferenceSession(
        str(caminho_do_modelo),
        sess_options=opcoes,
        providers=["CPUExecutionProvider"],
    )


class Detector:
    """Roda a inferência de um frame e devolve só o que a spec deixa passar."""

    def __init__(
        self,
        sessao: SessaoDeInferencia,
        configuracao: ConfiguracaoDoProcessamento,
    ) -> None:
        self._sessao = sessao
        self._configuracao = configuracao
        self._nome_da_entrada = sessao.get_inputs()[0].name

    def detectar(self, frame: np.ndarray) -> sv.Detections:
        """Detecta os veículos do frame BGR e devolve `supervision.Detections`.

        A saída é `sv.Detections` porque é o que o ByteTrack consome (SUP-018). Cada detecção carrega a categoria traduzida e a classe COCO
        original: SUP-023 precisa do histórico por rastreio e AC-008.2
        persiste a confiança.
        """
        entrada, escala, preenchimento = self._preprocessar(frame)
        (bruta,) = self._sessao.run(None, {self._nome_da_entrada: entrada})
        return self._posprocessar(np.asarray(bruta), escala, preenchimento, frame.shape)

    def _preprocessar(
        self, frame: np.ndarray
    ) -> tuple[np.ndarray, float, tuple[float, float]]:
        """Letterbox para 640×640, BGR→RGB, normalização e layout NCHW."""
        lado = self._configuracao.tamanho_de_entrada
        altura, largura = frame.shape[:2]

        # Mantém a proporção: a escala é a do lado que estoura primeiro.
        escala = min(lado / largura, lado / altura)
        nova_largura = round(largura * escala)
        nova_altura = round(altura * escala)
        redimensionado = cv2.resize(frame, (nova_largura, nova_altura))

        # A sobra vira faixa cinza centrada, e é ela que o pós-processamento
        # desconta para voltar às coordenadas do frame original.
        preenchimento_x = (lado - nova_largura) / 2
        preenchimento_y = (lado - nova_altura) / 2
        emoldurado = np.full((lado, lado, 3), _CINZA_DO_LETTERBOX, dtype=np.uint8)
        topo = int(preenchimento_y)
        esquerda = int(preenchimento_x)
        emoldurado[topo : topo + nova_altura, esquerda : esquerda + nova_largura] = (
            redimensionado
        )

        rgb = cv2.cvtColor(emoldurado, cv2.COLOR_BGR2RGB)
        normalizado = rgb.astype(np.float32) / 255.0
        nchw = np.transpose(normalizado, (2, 0, 1))[np.newaxis, ...]
        return np.ascontiguousarray(nchw), escala, (preenchimento_x, preenchimento_y)

    def _posprocessar(
        self,
        bruta: np.ndarray,
        escala: float,
        preenchimento: tuple[float, float],
        forma_do_frame: tuple[int, ...],
    ) -> sv.Detections:
        """Desfaz o letterbox, aplica NMS e roda os dois filtros da spec."""
        # A saída do YOLO11n é (1, 4 + classes, caixas): sem objetness, a
        # confiança da caixa é o maior escore de classe.
        predicoes = bruta[0].T
        escores_por_classe = predicoes[:, _COORDENADAS_DA_CAIXA:]
        classes = escores_por_classe.argmax(axis=1)
        confiancas = escores_por_classe.max(axis=1)

        # AC-005.2 — abaixo do limiar não passa. O corte é estritamente menor
        # que o limiar: uma detecção exatamente no valor configurado não está
        # "abaixo" dele.
        acima_do_limiar = confiancas >= self._configuracao.limiar_de_confianca

        # AC-005.1 — classe fora das quatro não tem correspondência. Os dois
        # filtros são aplicados juntos, antes de qualquer entrega.
        e_veiculo = np.array(
            [categoria_da_classe_coco(int(classe)) is not None for classe in classes],
            dtype=bool,
        )

        mantidas = acima_do_limiar & e_veiculo
        if not mantidas.any():
            return sv.Detections.empty()

        caixas = self._para_xyxy_do_frame(
            predicoes[mantidas, :_COORDENADAS_DA_CAIXA],
            escala,
            preenchimento,
            forma_do_frame,
        )
        classes_mantidas = classes[mantidas].astype(int)
        categorias = np.array(
            [
                categoria_da_classe_coco(int(classe)).value
                for classe in classes_mantidas
            ]
        )

        deteccoes = sv.Detections(
            xyxy=caixas,
            confidence=confiancas[mantidas].astype(np.float32),
            class_id=classes_mantidas,
            data={
                "classe_coco": classes_mantidas,
                "categoria": categorias,
            },
        )
        return deteccoes.with_nms(threshold=LIMIAR_DE_NMS, class_agnostic=False)

    @staticmethod
    def _para_xyxy_do_frame(
        caixas: np.ndarray,
        escala: float,
        preenchimento: tuple[float, float],
        forma_do_frame: tuple[int, ...],
    ) -> np.ndarray:
        """Converte `cx, cy, w, h` da entrada de 640 para `xyxy` do frame."""
        preenchimento_x, preenchimento_y = preenchimento
        centro_x = (caixas[:, 0] - preenchimento_x) / escala
        centro_y = (caixas[:, 1] - preenchimento_y) / escala
        metade_largura = caixas[:, 2] / escala / 2
        metade_altura = caixas[:, 3] / escala / 2

        xyxy = np.stack(
            [
                centro_x - metade_largura,
                centro_y - metade_altura,
                centro_x + metade_largura,
                centro_y + metade_altura,
            ],
            axis=1,
        ).astype(np.float32)

        # Caixa que encosta na borda não pode sair do frame: o cruzamento usa
        # o centro da base da caixa (SUP-018), e um valor fora do quadro
        # deslocaria esse ponto.
        altura, largura = forma_do_frame[:2]
        xyxy[:, [0, 2]] = xyxy[:, [0, 2]].clip(0, largura)
        xyxy[:, [1, 3]] = xyxy[:, [1, 3]].clip(0, altura)
        return xyxy

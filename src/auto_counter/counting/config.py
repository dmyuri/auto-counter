"""Vocabulário de categorias e configuração do processamento.

Comportamento definido em `.spec/features/contagem-veiculos/spec.md`: AC-005.1
e AC-005.2, e os padrões normativos de SUP-015, SUP-016, SUP-017, SUP-019 e
AC-007.1.

São exatamente quatro categorias — as que o modelo pré-treinado entrega sem
retreino. Uma quinta é mudança de schema e exige migration nova (`CLAUDE.md`),
não acréscimo de um valor aqui.
"""

from dataclasses import dataclass
from enum import Enum


class Categoria(Enum):
    """As quatro categorias de veículo, e nenhuma outra.

    O valor de cada membro é o próprio nome porque é assim que ele aparece no
    `eventos.json`, no banco e no XLSX (§Contexto da spec): serializar a
    categoria é escrever `.value`, sem tabela de tradução no meio.
    """

    CARRO = "CARRO"
    MOTO = "MOTO"
    ONIBUS = "ONIBUS"
    CAMINHAO = "CAMINHAO"


# Mapa fechado das classes COCO do YOLO11n para as quatro categorias
# (AC-005.1). Só estas quatro têm correspondência; pessoa (0), bicicleta (1),
# semáforo (9) e todo o resto do vocabulário ficam deliberadamente de fora.
_CATEGORIA_POR_CLASSE_COCO: dict[int, Categoria] = {
    2: Categoria.CARRO,
    3: Categoria.MOTO,
    5: Categoria.ONIBUS,
    7: Categoria.CAMINHAO,
}


def categoria_da_classe_coco(classe: int) -> Categoria | None:
    """Traduz a classe COCO devolvida pelo modelo para a categoria da spec.

    Devolve `None` para qualquer classe fora das quatro. A tradução não levanta
    erro porque classe desconhecida é o caso normal — o modelo detecta pessoas
    e semáforos o tempo todo —, e quem descarta é o filtro do frame (T-04), que
    é onde AC-005.1 acontece.
    """
    return _CATEGORIA_POR_CLASSE_COCO.get(classe)


@dataclass(frozen=True)
class ConfiguracaoDoProcessamento:
    """Os parâmetros do processamento, com os padrões normativos da spec.

    Congelada porque é o objeto que T-07 grava junto dos eventos: AC-008.1
    exige que a amostragem e o limiar **usados** fiquem registrados na sessão, e
    um objeto mutável permitiria que o valor gravado não fosse o valor aplicado.
    """

    limiar_de_confianca: float = 0.35  # SUP-016
    amostragem: int = 3  # SUP-017: 1 frame a cada 3
    tamanho_de_entrada: int = 640  # SUP-015
    janela_de_emenda_em_segundos: float = 2.0  # AC-007.1
    tolerancia_da_assinatura: float = 0.10  # SUP-019: fração do comprimento
    frames_por_segundo: int = 10  # SUP-090 (processamento-upload)

    def __post_init__(self) -> None:
        """Recusa valor fora do domínio de cada campo.

        Isso é erro de programação do chamador, não configuração possível: um
        limiar de 1,4 nunca deixa passar detecção alguma e uma amostragem de 0
        não analisa frame nenhum. A mensagem cita o campo e o valor recebido
        para que o bug apareça onde foi cometido.
        """
        if not 0.0 <= self.limiar_de_confianca <= 1.0:
            raise ValueError(
                f"limiar_de_confianca precisa estar entre 0 e 1, e não "
                f"{self.limiar_de_confianca} (SUP-016)"
            )

        if self.amostragem < 1:
            raise ValueError(
                f"amostragem precisa ser um inteiro de pelo menos 1 frame, e "
                f"não {self.amostragem} (SUP-017)"
            )

        if self.frames_por_segundo < 1:
            raise ValueError(
                f"frames_por_segundo precisa ser um inteiro de pelo menos 1, e "
                f"não {self.frames_por_segundo} (SUP-090)"
            )

        if self.janela_de_emenda_em_segundos < 0:
            raise ValueError(
                f"janela_de_emenda_em_segundos não pode ser negativa, e não "
                f"{self.janela_de_emenda_em_segundos} (AC-007.1)"
            )

        if self.tolerancia_da_assinatura < 0:
            raise ValueError(
                f"tolerancia_da_assinatura não pode ser negativa, e não "
                f"{self.tolerancia_da_assinatura} (SUP-019)"
            )

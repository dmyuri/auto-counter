"""Modelo das câmeras cadastradas e da sua linha de contagem.

Comportamento em `.spec/features/configuracao-camera/spec.md`: AC-001.2 (campo
obrigatório ausente ou de tipo inválido), AC-002.3 (linha degenerada) e
AC-002.4 (câmera sem linha não existe como modelo válido).

Os erros daqui nomeiam o **campo**. Nomear o **arquivo** cabe ao registro, que
é quem conhece o caminho de onde os dados vieram.
"""

from typing import Any

from pydantic import BaseModel, StrictInt, StrictStr, field_validator, model_validator


class Ponto(BaseModel):
    """Coordenada de pixel absoluta do frame original da câmera (SUP-002).

    Não é normalizada: os valores são pixels do frame como a câmera entrega,
    cujas dimensões são lidas do próprio vídeo (SUP-007). Se estão dentro do
    frame é outra validação, feita quando essas dimensões são conhecidas.
    """

    x: StrictInt
    y: StrictInt


class Linha(BaseModel):
    """Linha de contagem de uma câmera, definida por dois pontos distintos."""

    p1: Ponto
    p2: Ponto

    @model_validator(mode="after")
    def _rejeita_linha_degenerada(self) -> "Linha":
        if self.p1 == self.p2:
            raise ValueError(
                "linha degenerada: p1 e p2 são o mesmo ponto "
                f"(x={self.p1.x}, y={self.p1.y}); a linha de contagem precisa "
                "de dois pontos distintos"
            )
        return self


class Camera(BaseModel):
    """Câmera cadastrada e calibrada.

    Todos os campos são obrigatórios, exceto `preview`, que é opcional por
    `layout-interface` (SUP-066) e nunca invalida a câmera. Em particular `linha` não tem valor
    padrão, não é herdada e não é inferida em lugar nenhum do código: câmera
    sem linha não vira objeto válido (AC-002.4).

    `id` é string e é assim que os zeros à esquerda sobrevivem (SUP-001). O
    tipo é estrito de propósito: um YAML com `id: 000013` sem aspas chega aqui
    como número e é rejeitado citando o campo, em vez de virar outro id em
    silêncio.
    """

    id: StrictStr
    nome: StrictStr
    sentido_a: StrictStr
    sentido_b: StrictStr
    linha: Linha
    preview: str | None = None
    """Caminho da imagem de prévia, relativo ao diretório de configuração.

    Valor que não seja texto vale como campo ausente (R-2). Se o arquivo abre é
    assunto de quem lê a imagem, não do modelo.
    """

    @field_validator("preview", mode="before")
    @classmethod
    def _preview_que_nao_e_texto_vale_como_ausente(cls, valor: Any) -> str | None:
        return valor if isinstance(valor, str) else None

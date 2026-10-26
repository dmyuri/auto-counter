"""Tipos do conjunto de referência da validação de acurácia."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path

from auto_counter.counting.config import Categoria


class Condicao(Enum):
    """Condição de tráfego de um clipe de referência.

    O valor é o nome-base dos arquivos do clipe (`<valor>.csv` e
    `clipes/<valor>.mp4`), como descrito no README. A ordem dos membros é a
    ordem de saída do conjunto.
    """

    PICO = "pico"
    FORA_PICO = "fora_pico"
    NOTURNO = "noturno"
    CHUVA = "chuva"

    @property
    def obrigatoria(self) -> bool:
        """Só a chuva é opcional: não se agenda e não pode reprovar (Q-008)."""
        return self is not Condicao.CHUVA


@dataclass(frozen=True)
class ClipeDeReferencia:
    condicao: Condicao
    id_camera: str
    last_modified: datetime
    etag: str
    caminho_csv: Path
    caminho_video: Path


@dataclass(frozen=True)
class ConjuntoDeReferencia:
    raiz: Path
    clipes: tuple[ClipeDeReferencia, ...]


@dataclass(frozen=True)
class VeiculoManual:
    """Uma linha do CSV de contagem manual (D-1)."""

    linha: int
    instante_s: Decimal
    categoria: Categoria
    sentido: str


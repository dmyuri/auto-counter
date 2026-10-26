"""Tipos do conjunto de referência da validação de acurácia."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from fractions import Fraction
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


@dataclass(frozen=True)
class VeiculoAutomatico:
    """Um evento gravado, levado para a referência temporal do clipe.

    `instante_s` é o deslocamento inteiro, em segundos, desde o Last-Modified
    do clipe (resolução de 1 s: AC-006.5 trunca o timestamp).
    """

    instante_s: Decimal
    categoria: Categoria
    sentido: str
    id_de_rastreio: str


@dataclass(frozen=True)
class Par:
    """Um veículo manual casado com um automático. `delta_s` = automático − manual."""

    manual: VeiculoManual
    automatico: VeiculoAutomatico
    delta_s: Decimal


@dataclass(frozen=True)
class Pareamento:
    pares: tuple[Par, ...]
    manuais_sem_par: tuple[VeiculoManual, ...]
    automaticos_sem_par: tuple[VeiculoAutomatico, ...]


@dataclass(frozen=True)
class ErroDoSentido:
    """Totais e erro de contagem de um sentido (AC-014.1).

    `erro` é a fração exata |automático − manual| / manual. `None` significa
    indefinido: manual 0 com automático > 0 (D-2).
    """

    sentido: str
    manual: int
    automatico: int
    erro: Fraction | None


@dataclass(frozen=True)
class AcertoDeCategoria:
    """Acerto de categoria sobre os pares do clipe (AC-014.2).

    `fracao` é `None` quando não há nenhum par (D-2).
    """

    pares: int
    acertos: int
    fracao: Fraction | None


@dataclass(frozen=True)
class MatrizDeConfusao:
    """Contagem por (categoria manual, categoria automática).

    Sempre 4x4, na ordem de `Categoria`: `linhas[i][j]` é o número de pares
    com a i-ésima categoria no manual e a j-ésima no automático.
    """

    linhas: tuple[tuple[int, ...], ...]

    def contagem(self, manual: Categoria, automatica: Categoria) -> int:
        categorias = list(Categoria)
        return self.linhas[categorias.index(manual)][categorias.index(automatica)]


@dataclass(frozen=True)
class MedicaoDoClipe:
    erros: tuple[ErroDoSentido, ...]
    acerto: AcertoDeCategoria
    matriz: MatrizDeConfusao
    pareamento: Pareamento


@dataclass(frozen=True)
class Violacao:
    """Um limite da meta violado por um clipe (AC-014.4).

    `valor` é a fração medida, ou `None` quando a métrica é indefinida (D-2).
    `numerador` e `denominador` são os números brutos: no erro de contagem,
    |automático − manual| e manual; no acerto, acertos e pares. Em erro
    indefinido (manual 0), `numerador` é o total automático.
    """

    condicao: Condicao
    metrica: str
    sentido: str | None
    valor: Fraction | None
    numerador: int
    denominador: int
    limite: int


@dataclass(frozen=True)
class VereditoDoClipe:
    condicao: Condicao
    passou: bool
    violacoes: tuple[Violacao, ...]


@dataclass(frozen=True)
class VereditoDoConjunto:
    """Veredito da meta. `violacoes` e `ausentes` só consideram condições
    obrigatórias; a chuva fica em `clipes` para o relatório, sem peso no
    veredito (Q-008).
    """

    passou: bool
    clipes: tuple[VereditoDoClipe, ...]
    violacoes: tuple[Violacao, ...]
    ausentes: tuple[Condicao, ...]

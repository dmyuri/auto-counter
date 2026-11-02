"""Câmeras e limites que o formulário da interface oferece — T-15.

Comportamento em `.spec/features/interface-sessao/spec.md`: AC-011.1 (a
interface lista exatamente as câmeras válidas do registro), AC-011.2 (duração
inteira de 1 a 15 minutos), AC-011.3 (registro sem câmera válida) e SUP-043
(padrão de 15 minutos).

A interface só importa `streamlit`, a biblioteca padrão, `dotenv` e este pacote
(SUP-038), então os limites e o diretório padrão do registro são reexportados
daqui: a regra continua sendo a de `captura-clipes` e `configuracao-camera`,
sem cópia.
"""

from dataclasses import dataclass
from pathlib import Path

from auto_counter.cameras.model import Camera
from auto_counter.cameras.registry import (
    DIRETORIO_PADRAO,
    DiretorioDeRegistroInvalidoError,
    IdDuplicadoError,
    carregar_registro,
)
from auto_counter.capture.duration import DURACAO_MAXIMA, DURACAO_MINIMA

DURACAO_PADRAO = DURACAO_MAXIMA
"""SUP-043: a duração é oferecida com padrão de 15 minutos."""

__all__ = [
    "DIRETORIO_PADRAO",
    "DURACAO_MAXIMA",
    "DURACAO_MINIMA",
    "DURACAO_PADRAO",
    "CamerasDisponiveis",
    "cameras_disponiveis",
]


@dataclass(frozen=True)
class CamerasDisponiveis:
    """As câmeras que a interface oferece e, se não houver, por quê.

    `rejeicoes` são os arquivos recusados (AC-001.2, AC-002.4): nenhum deles
    entra em `cameras`, e a interface pode mostrá-los para explicar a lista.
    """

    cameras: tuple[Camera, ...]
    motivo: str | None = None
    rejeicoes: tuple[str, ...] = ()


def cameras_disponiveis(config_dir: str | Path) -> CamerasDisponiveis:
    """Carrega o registro e devolve as câmeras válidas, sem nunca levantar.

    Id duplicado derruba o registro inteiro (AC-001.3) e diretório inválido não
    é registro vazio; nos dois casos a lista vem vazia e o `motivo` explica, para
    a interface tratá-los como AC-011.3.
    """
    try:
        registro = carregar_registro(config_dir)
    except (IdDuplicadoError, DiretorioDeRegistroInvalidoError) as falha:
        return CamerasDisponiveis(cameras=(), motivo=str(falha))

    rejeicoes = tuple(str(rejeicao) for rejeicao in registro.rejeicoes)
    motivo = None
    if not registro.cameras:
        motivo = (
            "nenhuma câmera válida no registro"
            if not rejeicoes
            else "nenhuma câmera válida no registro; arquivos recusados: "
            + "; ".join(rejeicoes)
        )
    return CamerasDisponiveis(
        cameras=tuple(registro.cameras), motivo=motivo, rejeicoes=rejeicoes
    )

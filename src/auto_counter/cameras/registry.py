"""Carregamento do registro versionado de câmeras.

Comportamento em `.spec/features/configuracao-camera/spec.md`: AC-001.1
(N arquivos válidos → N câmeras completas), AC-001.2 (arquivo inválido é
rejeitado citando arquivo e campo, e as demais câmeras seguem disponíveis),
AC-001.3 (id duplicado derruba o carregamento inteiro) e AC-002.4 (câmera sem
linha é rejeitada e nunca herda a linha de outra).

A assimetria entre AC-001.2 e AC-001.3 é da spec e é proposital: arquivo
inválido é rejeição **isolada**, id duplicado é falha do **registro inteiro**.

O contrato de retorno é `Registro`: as câmeras válidas mais a lista de
rejeições, para que o CLI (`camera list`) e a interface de sessão possam
mostrar o motivo de cada arquivo recusado em vez de apenas omiti-lo.

Este módulo só lê arquivos. Nada aqui cria ou edita YAML de câmera: a lista é
pré-definida e versionada, e alterá-la é tarefa de manutenção no repositório.
"""

from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import ValidationError

from auto_counter.cameras.model import Camera

DIRETORIO_PADRAO = Path("config/cameras")
"""Diretório do registro versionado, relativo à raiz do repositório."""


class DiretorioDeRegistroInvalidoError(Exception):
    """O caminho do registro não existe ou não é um diretório.

    Distinto de registro vazio de propósito: um `config/cameras/` ausente ou um
    diretório de trabalho errado não podem se disfarçar de "nenhuma câmera
    cadastrada".
    """


class IdDuplicadoError(Exception):
    """Dois arquivos declaram o mesmo id (AC-001.3).

    Derruba o carregamento inteiro: nenhuma câmera é disponibilizada, nem as
    que não têm relação com o id repetido.
    """


@dataclass(frozen=True)
class Rejeicao:
    """Um arquivo recusado, com o arquivo e o campo problemático (AC-001.2)."""

    arquivo: str
    motivo: str

    def __str__(self) -> str:
        return f"{self.arquivo}: {self.motivo}"


@dataclass(frozen=True)
class Registro:
    """O resultado de uma carga: o que entrou e o que foi recusado."""

    cameras: list[Camera]
    rejeicoes: list[Rejeicao]


def _motivo_da_validacao(erro: ValidationError) -> str:
    """Mensagem que nomeia o campo problemático, como pede AC-001.2."""
    partes = []
    for detalhe in erro.errors():
        campo = ".".join(str(parte) for parte in detalhe["loc"]) or "(raiz)"
        partes.append(f"campo '{campo}': {detalhe['msg']}")
    return "; ".join(partes)


def _carrega_arquivo(caminho: Path) -> Camera:
    """Lê um YAML de câmera. Erros viram ValueError com o campo citado."""
    try:
        conteudo = yaml.safe_load(caminho.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError, UnicodeDecodeError) as erro:
        raise ValueError(f"não foi possível ler o YAML: {erro}") from erro

    if not isinstance(conteudo, dict):
        raise ValueError(
            "o conteúdo não é um mapeamento de campos "
            f"(campos esperados: {', '.join(Camera.model_fields)})"
        )

    try:
        return Camera(**conteudo)
    except ValidationError as erro:
        raise ValueError(_motivo_da_validacao(erro)) from erro


def _falha_por_id_duplicado(por_id: dict[str, list[Path]]) -> None:
    """Levanta IdDuplicadoError citando os ids repetidos e seus arquivos."""
    duplicados = {
        id_: caminhos for id_, caminhos in por_id.items() if len(caminhos) > 1
    }
    if not duplicados:
        return

    detalhes = "; ".join(
        f"'{id_}' declarado em "
        + ", ".join(str(caminho) for caminho in sorted(caminhos))
        for id_, caminhos in sorted(duplicados.items())
    )
    raise IdDuplicadoError(
        f"id duplicado no registro: {detalhes}. Nenhuma câmera foi carregada."
    )


def carregar_registro(diretorio: Path | str = DIRETORIO_PADRAO) -> Registro:
    """Carrega as câmeras de um diretório de configuração.

    Devolve as câmeras válidas e as rejeições. Um arquivo inválido não derruba
    os demais (AC-001.2); um id declarado por mais de um arquivo derruba tudo
    (AC-001.3).
    """
    diretorio = Path(diretorio)
    if not diretorio.is_dir():
        raise DiretorioDeRegistroInvalidoError(
            f"diretório de câmeras inexistente ou inválido: {diretorio}"
        )

    cameras: list[Camera] = []
    rejeicoes: list[Rejeicao] = []
    por_id: dict[str, list[Path]] = {}

    for caminho in sorted(diretorio.glob("*.yaml")):
        try:
            camera = _carrega_arquivo(caminho)
        except ValueError as erro:
            rejeicoes.append(Rejeicao(arquivo=str(caminho), motivo=str(erro)))
            continue
        cameras.append(camera)
        por_id.setdefault(camera.id, []).append(caminho)

    _falha_por_id_duplicado(por_id)

    return Registro(cameras=cameras, rejeicoes=rejeicoes)

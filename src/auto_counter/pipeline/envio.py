"""Triagem, gravação e limpeza dos vídeos enviados pela interface.

Comportamento em `.spec/features/upload-videos/spec.md`: AC-027.1, AC-027.2 e
AC-027.10 (aceite por extensão e tamanho), SUP-082 (cada arquivo aceito é
gravado em `<data_dir>/envios/` assim que chega) e SUP-087 (limpeza dos
arquivos que não entraram em nenhuma sessão). Decisões de forma D-3 e D-4.

Nada aqui importa `streamlit`: a interface só chama estas funções (SUP-038).
"Remover" na tela não apaga o arquivo do disco; o descarte é
`apagar_envios_orfaos`, chamada ao iniciar a sessão de upload
(`processamento-upload`).
"""

import shutil
from collections.abc import Iterable
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

EXTENSOES_ACEITAS = (".mp4", ".mov", ".avi", ".mkv")
LIMITE_DE_BYTES = 1_000_000_000
"""Limite por arquivo, em bytes (AC-027.10). Exatamente este valor é aceito."""

PEDACO_DE_GRAVACAO = 1024 * 1024
"""Quanto se grava por vez (1 MiB), como `PEDACO_DE_LEITURA` de `capture/content.py`."""


def triar(nome: str, tamanho: int) -> str | None:
    """`None` se o arquivo é aceito; senão a mensagem de recusa.

    A extensão é conferida antes do tamanho (D-3).
    """
    if Path(nome).suffix.lower() not in EXTENSOES_ACEITAS:
        return (
            f"{nome}: extensão não aceita. "
            "Envie arquivos .mp4, .mov, .avi ou .mkv."
        )
    if tamanho > LIMITE_DE_BYTES:
        return f"{nome}: o arquivo passa do limite de 1 GB por arquivo."
    return None


def diretorio_de_envio(data_dir: Path) -> Path:
    """`<data_dir>/envios` (D-4)."""
    return Path(data_dir) / "envios"


def gravar_envio(data_dir: Path, nome: str, conteudo: BinaryIO) -> Path:
    """Grava o arquivo já triado em `envios/` e devolve o caminho absoluto.

    O nome em disco é `<uuid><extensão em minúsculas>`: o nome original fica só
    na lista, porque dois arquivos de mesmo nome podem coexistir (SUP-085).
    Não confere extensão nem tamanho; quem chama já triou.
    """
    diretorio = diretorio_de_envio(data_dir)
    diretorio.mkdir(parents=True, exist_ok=True)
    destino = diretorio / f"{uuid4().hex}{Path(nome).suffix.lower()}"
    with destino.open("wb") as saida:
        shutil.copyfileobj(conteudo, saida, PEDACO_DE_GRAVACAO)
    return destino.resolve()


def apagar_envios_orfaos(data_dir: Path, manter: Iterable[Path]) -> None:
    """Apaga tudo em `envios/` que não está em `manter` (SUP-087).

    Diretório ausente não é erro, nem arquivo que some durante a limpeza.
    Nunca toca fora de `envios/`.
    """
    diretorio = diretorio_de_envio(data_dir)
    if not diretorio.is_dir():
        return
    preservados = {Path(caminho).resolve() for caminho in manter}
    for arquivo in diretorio.iterdir():
        if arquivo.is_file() and arquivo.resolve() not in preservados:
            arquivo.unlink(missing_ok=True)

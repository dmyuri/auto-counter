"""Nomes de download, tamanho em MB e `.zip` dos clipes — download-clipes.

Comportamento em `.spec/features/download-clipes/spec.md`: SUP-077 (nome do
arquivo), D-3 (sufixo por minuto de relógio), D-5 (formato do tamanho em MB) e
a parte de `pipeline` da D-6 (o `.zip` em memória, sem recomprimir).

Funções puras: nada aqui importa `streamlit`, grava em disco ou abre o
`manifest.json` — só lê os bytes dos clipes que recebe.
"""

from __future__ import annotations

import zipfile
from collections.abc import Sequence
from datetime import datetime
from io import BytesIO
from pathlib import Path

from auto_counter.export.format import FUSO


def nomes_de_download(id_camera: str, instantes: Sequence[datetime]) -> tuple[str, ...]:
    """Um nome por instante, na ordem recebida, pela regra de SUP-077 e D-3.

    O primeiro instante de cada minuto de relógio (em horário de Brasília)
    fica sem sufixo; os seguintes no mesmo minuto recebem `_2`, `_3`...
    """
    contagem: dict[str, int] = {}
    nomes = []
    for instante in instantes:
        if instante.tzinfo is None:
            raise ValueError(
                f"instante sem fuso horário ({instante!r}); o nome do clipe "
                f"exige fuso explícito para converter para o horário de "
                f"Brasília"
            )
        local = instante.astimezone(FUSO)
        base = f"{id_camera}_{local:%Y%m%d}_{local:%H%M}"
        contagem[base] = contagem.get(base, 0) + 1
        ordem = contagem[base]
        sufixo = "" if ordem == 1 else f"_{ordem}"
        nomes.append(f"{base}{sufixo}.mp4")
    return tuple(nomes)


def formatar_megabytes(tamanho_em_bytes: int) -> str:
    """MB decimal (10⁶ bytes), uma casa, vírgula, meio para cima (D-5)."""
    decimos = (2 * tamanho_em_bytes + 100_000) // 200_000
    return f"{decimos // 10},{decimos % 10} MB"


def montar_zip(arquivos: Sequence[tuple[Path, str]]) -> bytes:
    """O `.zip` em memória, sem recomprimir (o `.mp4` já é comprimido), D-6.

    Um membro por par `(caminho, nome_no_zip)`, na ordem recebida, com o
    conteúdo lido do `caminho`.
    """
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_STORED) as zip_arquivo:
        for caminho, nome_no_zip in arquivos:
            zip_arquivo.writestr(nome_no_zip, Path(caminho).read_bytes())
    return buffer.getvalue()

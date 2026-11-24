"""Registro em disco da sessão de upload: o `upload.json`.

Definido em `.spec/features/processamento-upload/spec.md`: AC-028.8 (minutos
numerados em sequência através dos vídeos), AC-030.1 (dados por vídeo),
SUP-097 (arquivos da sessão) e, no `_tasks.md`, D-3 e D-7.

O `upload.json` fica em `<data_dir>/sessions/<id_sessao>/` e é o que identifica
uma sessão de upload no disco. Nada aqui importa `streamlit`, `pipeline` nem
`httpx`: `counting` e `storage` precisam lê-lo, como leem `capture.manifest`.
A escrita é atômica (temporário no mesmo diretório e `os.replace`), como em
`capture/manifest.py`.
"""

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

NOME_DO_REGISTRO = "upload.json"
VERSAO_DO_REGISTRO = 1


def numerar_minutos(
    duracoes_em_segundos: Sequence[int],
) -> tuple[tuple[int, int], ...]:
    """O par `(minuto_inicial, minuto_final)` de cada vídeo (AC-028.8, D-3).

    O vídeo ocupa `max(1, ⌈D/60⌉)` minutos, numerados a partir de 1 através dos
    vídeos, na ordem recebida.
    """
    faixas: list[tuple[int, int]] = []
    proximo = 1
    for duracao in duracoes_em_segundos:
        if duracao < 0:
            raise ValueError(f"duração negativa ({duracao} s) em AC-028.8")
        minutos = max(1, math.ceil(duracao / 60))
        faixas.append((proximo, proximo + minutos - 1))
        proximo += minutos
    return tuple(faixas)


def nome_do_arquivo_do_video(posicao: int, extensao: str) -> str:
    """`video-01.mp4`: a posição com dois dígitos e a extensão em minúsculas."""
    return f"video-{posicao:02d}{extensao.lower()}"


@dataclass(frozen=True)
class VideoDaSessaoDeUpload:
    """Um vídeo da sessão, com o que AC-030.1 manda guardar."""

    posicao: int
    nome_original: str
    arquivo: str
    duracao_segundos: int
    sha256: str
    minuto_inicial: int
    minuto_final: int

    def como_dicionario(self) -> dict:
        return {
            "posicao": self.posicao,
            "nome_original": self.nome_original,
            "arquivo": self.arquivo,
            "duracao_segundos": self.duracao_segundos,
            "sha256": self.sha256,
            "minuto_inicial": self.minuto_inicial,
            "minuto_final": self.minuto_final,
        }


@dataclass(frozen=True)
class RegistroDoUpload:
    """O conteúdo do `upload.json`.

    `duracao_minutos` (M) é sempre o `minuto_final` do último vídeo.
    """

    id_sessao: str
    id_camera: str
    duracao_minutos: int
    videos: tuple[VideoDaSessaoDeUpload, ...]

    def __post_init__(self) -> None:
        ultimo = self.videos[-1].minuto_final if self.videos else 0
        if self.duracao_minutos != ultimo:
            raise ValueError(
                f"duracao_minutos ({self.duracao_minutos}) precisa ser o "
                f"minuto_final do último vídeo ({ultimo}) em D-7"
            )

    def como_dicionario(self) -> dict:
        return {
            "versao": VERSAO_DO_REGISTRO,
            "id_sessao": self.id_sessao,
            "id_camera": self.id_camera,
            "duracao_minutos": self.duracao_minutos,
            "videos": [video.como_dicionario() for video in self.videos],
        }


def gravar(dir_sessao: str | Path, registro: RegistroDoUpload) -> Path:
    """Grava o `upload.json` de forma atômica e devolve o caminho."""
    dir_sessao = Path(dir_sessao)
    dir_sessao.mkdir(parents=True, exist_ok=True)
    caminho = dir_sessao / NOME_DO_REGISTRO
    temporario = caminho.with_name(f"{NOME_DO_REGISTRO}.tmp")
    try:
        temporario.write_text(
            json.dumps(registro.como_dicionario(), ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )
        os.replace(temporario, caminho)
    except OSError:
        temporario.unlink(missing_ok=True)
        raise
    return caminho


def ler(dir_sessao: str | Path) -> RegistroDoUpload:
    """Lê o `upload.json` do diretório da sessão."""
    dados = json.loads(
        (Path(dir_sessao) / NOME_DO_REGISTRO).read_text(encoding="utf-8")
    )
    return RegistroDoUpload(
        id_sessao=dados["id_sessao"],
        id_camera=dados["id_camera"],
        duracao_minutos=dados["duracao_minutos"],
        videos=tuple(VideoDaSessaoDeUpload(**video) for video in dados["videos"]),
    )


def e_sessao_de_upload(dir_sessao: str | Path) -> bool:
    """A presença do `upload.json` identifica a sessão de upload (D-7)."""
    return (Path(dir_sessao) / NOME_DO_REGISTRO).is_file()


def apagar_videos(dir_sessao: str | Path) -> int:
    """Apaga os arquivos listados no registro (AC-030.6) e devolve quantos.

    Nunca apaga o `upload.json`, o `eventos.json` nem o diretório.
    """
    dir_sessao = Path(dir_sessao)
    apagados = 0
    for video in ler(dir_sessao).videos:
        alvo = dir_sessao / video.arquivo
        try:
            alvo.unlink()
            apagados += 1
        except FileNotFoundError:
            pass
    return apagados

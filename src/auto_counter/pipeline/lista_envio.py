"""Avaliação da lista de envio, dos totais e do botão (regra pura).

Comportamento em `.spec/features/upload-videos/spec.md`: AC-027.3 a AC-027.9 e
AC-027.11, AC-026.2 (aviso da câmera), SUP-085 (duplicata) e as decisões R-3,
D-7, D-8 e D-9.

A avaliação é recalculada a cada execução do script a partir dos itens e da
câmera selecionada. Assim a troca de câmera (AC-027.6) e a remoção
(AC-027.8) não precisam de estado extra. O `Future` de cada item é lido só com
`done()` e `result()`, nunca se espera por ele. Nada aqui importa `streamlit`
(SUP-038).
"""

from __future__ import annotations

from collections.abc import Sequence
from concurrent.futures import Future
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from auto_counter.cameras.model import Camera
from auto_counter.pipeline.clipes import formatar_megabytes
from auto_counter.pipeline.leitura_video import LeituraDoVideo
from auto_counter.pipeline.progress import formatar_tempo

LIMITE_DE_DURACAO_SEGUNDOS = 900
"""15 min de duração somada (AC-027.11)."""


@dataclass(frozen=True)
class ItemDoEnvio:
    id: str
    nome: str
    tamanho: int
    caminho: Path
    leitura: Future[LeituraDoVideo]


class Situacao(Enum):
    LENDO = "lendo"
    VALIDO = "valido"
    INVALIDO = "invalido"


@dataclass(frozen=True)
class LinhaDoEnvio:
    id: str
    nome: str
    duracao: str | None
    tamanho: str
    situacao: Situacao
    motivo: str | None = None
    aviso: str | None = None


@dataclass(frozen=True)
class AvaliacaoDoEnvio:
    linhas: tuple[LinhaDoEnvio, ...]
    totais: str | None
    duracao_total: str | None
    aviso_do_limite: str | None
    texto_do_botao: str
    botao_disponivel: bool


def aviso_da_camera(camera: Camera) -> str:
    """O aviso de AC-026.2 (D-8)."""
    return f"Envie apenas vídeos gravados pela {camera.id} · {camera.nome}."


def _linha_invalida(item: ItemDoEnvio, leitura: LeituraDoVideo, motivo: str) -> LinhaDoEnvio:
    return LinhaDoEnvio(
        id=item.id,
        nome=item.nome,
        duracao=_duracao(leitura),
        tamanho=formatar_megabytes(item.tamanho),
        situacao=Situacao.INVALIDO,
        motivo=motivo,
    )


def _duracao(leitura: LeituraDoVideo) -> str | None:
    if leitura.duracao_segundos is None:
        return None
    return formatar_tempo(leitura.duracao_segundos)


def avaliar_envio(
    itens: Sequence[ItemDoEnvio],
    camera: Camera | None,
    *,
    outra_sessao_em_andamento: bool = False,
) -> AvaliacaoDoEnvio:
    """Avalia a lista na ordem recebida (D-7, D-8 e D-9)."""
    linhas: list[LinhaDoEnvio] = []
    validos: list[tuple[ItemDoEnvio, LeituraDoVideo]] = []
    primeiro_por_hash: dict[str, str] = {}
    lendo = False

    for item in itens:
        if not item.leitura.done():
            lendo = True
            linhas.append(
                LinhaDoEnvio(
                    id=item.id,
                    nome=item.nome,
                    duracao=None,
                    tamanho=formatar_megabytes(item.tamanho),
                    situacao=Situacao.LENDO,
                )
            )
            continue

        leitura = item.leitura.result()
        if not leitura.legivel:
            linhas.append(
                _linha_invalida(
                    item, leitura, "Inválido: o arquivo não abre como vídeo legível."
                )
            )
        elif camera is None:
            linhas.append(
                _linha_invalida(item, leitura, "Inválido: selecione a câmera dos vídeos.")
            )
        elif (leitura.largura, leitura.altura) != (
            camera.resolucao.largura,
            camera.resolucao.altura,
        ):
            linhas.append(
                _linha_invalida(
                    item,
                    leitura,
                    f"Inválido: resolução {leitura.largura}×{leitura.altura}, "
                    f"diferente da calibração da {camera.id} "
                    f"({camera.resolucao.largura}×{camera.resolucao.altura}).",
                )
            )
        else:
            anterior = primeiro_por_hash.get(leitura.sha256)
            if anterior is None:
                primeiro_por_hash[leitura.sha256] = item.nome
            validos.append((item, leitura))
            linhas.append(
                LinhaDoEnvio(
                    id=item.id,
                    nome=item.nome,
                    duracao=_duracao(leitura),
                    tamanho=formatar_megabytes(item.tamanho),
                    situacao=Situacao.VALIDO,
                    aviso=(
                        None
                        if anterior is None
                        else f"Duplicata de {anterior}: o conteúdo é idêntico."
                    ),
                )
            )

    quantidade = len(validos)
    segundos = sum(leitura.duracao_segundos or 0 for _, leitura in validos)
    acima_do_limite = segundos > LIMITE_DE_DURACAO_SEGUNDOS

    totais = duracao_total = None
    if quantidade:
        palavra = "vídeo" if quantidade == 1 else "vídeos"
        tamanho_total = formatar_megabytes(sum(item.tamanho for item, _ in validos))
        totais = f"{quantidade} {palavra} · {tamanho_total}"
        duracao_total = f"duração total {formatar_tempo(segundos)}"

    aviso_do_limite = (
        f"A duração somada ({formatar_tempo(segundos)}) passa do limite de 15 min."
        if acima_do_limite
        else None
    )

    if lendo:
        texto, disponivel = "Lendo vídeos…", False
    elif not quantidade:
        texto, disponivel = "Importe vídeos para iniciar", False
    else:
        texto = "Processar 1 vídeo" if quantidade == 1 else f"Processar {quantidade} vídeos"
        disponivel = not acima_do_limite and not outra_sessao_em_andamento

    return AvaliacaoDoEnvio(
        linhas=tuple(linhas),
        totais=totais,
        duracao_total=duracao_total,
        aviso_do_limite=aviso_do_limite,
        texto_do_botao=texto,
        botao_disponivel=disponivel,
    )

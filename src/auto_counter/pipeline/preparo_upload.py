"""Validação dos arquivos e preparo do diretório da sessão de upload.

Comportamento em `.spec/features/processamento-upload/spec.md`: AC-028.1 (só
vídeos válidos e dentro dos limites de AC-027.10 e AC-027.11), AC-030.7
(arquivo inválido é recusado antes de qualquer processamento, com mensagem que
nomeia o arquivo), SUP-087, SUP-097 e SUP-098, e as etapas (2), (5) e (6) de
D-13 do `_tasks.md`.

As regras são as de `upload-videos`, sem cópia: extensão e tamanho vêm de
`envio.triar`, e legibilidade, resolução, soma de 15 min e duplicata vêm de
`lista_envio.avaliar_envio`. Nada aqui importa `streamlit`.
"""

import shutil
from concurrent.futures import Future
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from auto_counter.cameras.model import Camera
from auto_counter.capture.manifest import diretorio_da_sessao
from auto_counter.pipeline.envio import (
    apagar_envios_orfaos,
    diretorio_de_envio,
    triar,
)
from auto_counter.pipeline.leitura_video import LeituraDoVideo, ler_video
from auto_counter.pipeline.lista_envio import ItemDoEnvio, Situacao, avaliar_envio
from auto_counter.upload.manifest import (
    RegistroDoUpload,
    VideoDaSessaoDeUpload,
    gravar,
    nome_do_arquivo_do_video,
    numerar_minutos,
)

PREFIXO_DE_INVALIDO = "Inválido: "


class ArquivoRecusadoError(ValueError):
    """Um arquivo que não pode entrar na sessão. A mensagem nomeia o arquivo."""

    def __init__(self, nome_original: str, motivo: str) -> None:
        self.nome_original = nome_original
        self.motivo = motivo
        super().__init__(f"{nome_original}: {motivo}")


@dataclass(frozen=True)
class ValidacaoDoUpload:
    """O que a validação rendeu: as leituras e os avisos de duplicata."""

    leituras: tuple[LeituraDoVideo, ...]
    avisos: tuple[str, ...]


def _tamanho_do_arquivo(caminho: Path) -> int:
    return Path(caminho).stat().st_size


def triar_arquivos(arquivos: Sequence[Path | str], nomes: Sequence[str]) -> None:
    """Existência, extensão e tamanho, na ordem; o primeiro recusado levanta."""
    for arquivo, nome in zip(arquivos, nomes):
        if not Path(arquivo).is_file():
            raise ArquivoRecusadoError(nome, "o arquivo não existe.")
        mensagem = triar(nome, _tamanho_do_arquivo(Path(arquivo)))
        if mensagem is not None:
            raise ArquivoRecusadoError(nome, mensagem.removeprefix(f"{nome}: "))


def validar_arquivos(
    arquivos: Sequence[Path | str], nomes: Sequence[str], camera: Camera
) -> ValidacaoDoUpload:
    """Lê cada arquivo e aplica as regras da lista de envio (SUP-098).

    Item inválido levanta com o motivo da linha, e a soma acima de 15 min
    levanta com o nome do último arquivo, o que passou do limite. A duplicata só
    gera aviso.
    """
    leituras: list[LeituraDoVideo] = []
    itens: list[ItemDoEnvio] = []
    for posicao, (arquivo, nome) in enumerate(zip(arquivos, nomes), start=1):
        lida = ler_video(arquivo)
        resolvida: Future[LeituraDoVideo] = Future()
        resolvida.set_result(lida)
        leituras.append(lida)
        itens.append(
            ItemDoEnvio(
                id=str(posicao),
                nome=nome,
                tamanho=_tamanho_do_arquivo(Path(arquivo)),
                caminho=Path(arquivo),
                leitura=resolvida,
            )
        )

    avaliacao = avaliar_envio(itens, camera)
    for linha in avaliacao.linhas:
        if linha.situacao is Situacao.INVALIDO:
            raise ArquivoRecusadoError(
                linha.nome, (linha.motivo or "").removeprefix(PREFIXO_DE_INVALIDO)
            )
    if avaliacao.aviso_do_limite is not None:
        raise ArquivoRecusadoError(nomes[-1], avaliacao.aviso_do_limite)

    return ValidacaoDoUpload(
        leituras=tuple(leituras),
        avisos=tuple(
            f"{linha.nome}: {linha.aviso}"
            for linha in avaliacao.linhas
            if linha.aviso is not None
        ),
    )


def _esta_em_envios(data_dir: Path, arquivo: Path) -> bool:
    return arquivo.resolve().parent == diretorio_de_envio(data_dir).resolve()


def preparar_sessao(
    data_dir: Path | str,
    *,
    id_sessao: str,
    camera: Camera,
    arquivos: Sequence[Path | str],
    nomes: Sequence[str],
    leituras: Sequence[LeituraDoVideo],
) -> RegistroDoUpload:
    """Monta `sessions/<id_sessao>/` com os vídeos e o `upload.json` (SUP-097).

    O que está em `envios/` é movido e o resto é copiado, porque o original do
    usuário nunca é tocado. Depois, o que sobrou em `envios/` é apagado
    (SUP-087). Falha no meio apaga o diretório da sessão criado e relevanta.
    """
    data_dir = Path(data_dir)
    dir_sessao = diretorio_da_sessao(data_dir, id_sessao)
    faixas = numerar_minutos([leitura.duracao_segundos or 0 for leitura in leituras])

    dir_sessao.mkdir(parents=True, exist_ok=False)
    try:
        videos: list[VideoDaSessaoDeUpload] = []
        for posicao, (arquivo, nome, lida, (inicial, final)) in enumerate(
            zip(arquivos, nomes, leituras, faixas), start=1
        ):
            arquivo = Path(arquivo)
            nome_no_disco = nome_do_arquivo_do_video(posicao, Path(nome).suffix)
            destino = dir_sessao / nome_no_disco
            if _esta_em_envios(data_dir, arquivo):
                shutil.move(str(arquivo), destino)
            else:
                shutil.copyfile(arquivo, destino)
            videos.append(
                VideoDaSessaoDeUpload(
                    posicao=posicao,
                    nome_original=nome,
                    arquivo=nome_no_disco,
                    duracao_segundos=lida.duracao_segundos or 0,
                    sha256=lida.sha256 or "",
                    minuto_inicial=inicial,
                    minuto_final=final,
                )
            )
        registro = RegistroDoUpload(
            id_sessao=id_sessao,
            id_camera=camera.id,
            duracao_minutos=faixas[-1][1],
            videos=tuple(videos),
        )
        gravar(dir_sessao, registro)
    except BaseException:
        shutil.rmtree(dir_sessao, ignore_errors=True)
        raise

    apagar_envios_orfaos(data_dir, manter=())
    return registro

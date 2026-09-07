"""Ponto de entrada da CLI `auto-counter`.

A raiz hospeda um subgrupo por área: `camera` é o da feature
`configuracao-camera`, com os comandos `list` e `preview`.

Comportamento em `.spec/features/configuracao-camera/spec.md`: AC-001.1 (a
listagem mostra exatamente as câmeras do registro, com id, nome e os dois
rótulos de sentido), AC-001.2 (as rejeições aparecem com arquivo e motivo, sem
derrubar as demais), AC-001.3 (id duplicado derruba o registro inteiro e o
comando sai com código diferente de zero), AC-001.5 (sem
`AUTO_COUNTER_BASE_URL` a montagem da URL falha com erro explícito), AC-002.1
(o preview grava o PNG com a linha e os rótulos) e AC-002.2 (linha fora do
frame não gera PNG).

Todo erro tratado das camadas de baixo vira aqui mensagem legível em stderr e
código de saída diferente de zero — nunca traceback (`CLAUDE.md`).
"""

import os
from pathlib import Path

import typer
from dotenv import load_dotenv

from auto_counter.cameras.frame import FrameIndisponivelError, primeiro_frame
from auto_counter.cameras.geometry import LinhaForaDoFrameError
from auto_counter.cameras.preview import gravar_preview
from auto_counter.cameras.registry import (
    DIRETORIO_PADRAO,
    DiretorioDeRegistroInvalidoError,
    IdDuplicadoError,
    Registro,
    carregar_registro,
)
from auto_counter.cameras.url import BaseUrlAusenteError

VARIAVEL_DATA_DIR = "AUTO_COUNTER_DATA_DIR"
"""Variável de ambiente com o diretório de dados das sessões."""

DATA_DIR_PADRAO = Path("data")
"""Diretório de dados usado quando a variável não está definida.

Não é segredo nem endereço de rede — é só onde os artefatos locais caem — e o
`.gitignore` já cobre `data/`, então nada gerado aqui escapa para o
repositório. A proibição de valor padrão embutido de AC-001.5 é sobre a base
URL, que continua vindo exclusivamente do ambiente.
"""

SUBDIRETORIO_DE_PREVIEWS = "previews"
"""Onde o PNG cai dentro do diretório de dados quando `--out` é omitido."""

app = typer.Typer(
    name="auto-counter",
    help="Contagem e classificação automática de veículos por visão computacional.",
    no_args_is_help=True,
)

camera_app = typer.Typer(
    name="camera",
    help="Câmeras cadastradas e calibração da linha de contagem.",
    no_args_is_help=True,
)

OPCAO_CONFIG_DIR = typer.Option(
    DIRETORIO_PADRAO,
    "--config-dir",
    help="Diretório do registro versionado de câmeras.",
)


@app.callback()
def raiz() -> None:
    """Carrega o `.env` antes de qualquer comando.

    `load_dotenv` não sobrescreve variável já definida no ambiente: quem
    exporta na sessão continua mandando.
    """
    load_dotenv()


@camera_app.callback()
def camera() -> None:
    """Câmeras cadastradas e calibração da linha de contagem."""


def _erro(mensagem: str) -> typer.Exit:
    """Escreve a mensagem em stderr e devolve a saída com código 1."""
    typer.secho(f"erro: {mensagem}", err=True, fg=typer.colors.RED)
    return typer.Exit(code=1)


def _carrega(config_dir: Path) -> Registro:
    """Carrega o registro, traduzindo as falhas em mensagem e código 1."""
    try:
        return carregar_registro(config_dir)
    except (IdDuplicadoError, DiretorioDeRegistroInvalidoError) as falha:
        raise _erro(str(falha)) from falha


def _caminho_padrao_do_preview(id_camera: str) -> Path:
    """`<data_dir>/previews/<id>.png` — o padrão quando `--out` é omitido."""
    data_dir = (os.environ.get(VARIAVEL_DATA_DIR) or "").strip()
    raiz = Path(data_dir) if data_dir else DATA_DIR_PADRAO
    return raiz / SUBDIRETORIO_DE_PREVIEWS / f"{id_camera}.png"


@camera_app.command("list")
def listar(config_dir: Path = OPCAO_CONFIG_DIR) -> None:
    """Lista as câmeras cadastradas e os arquivos recusados."""
    registro = _carrega(config_dir)

    if not registro.cameras:
        typer.echo("Nenhuma câmera cadastrada.")
    for camera_ in registro.cameras:
        typer.echo(
            f"{camera_.id}  {camera_.nome}  "
            f"[A: {camera_.sentido_a} | B: {camera_.sentido_b}]"
        )

    if registro.rejeicoes:
        typer.echo("")
        typer.echo("Arquivos recusados:")
        for rejeicao in registro.rejeicoes:
            typer.echo(f"  {rejeicao.arquivo}: {rejeicao.motivo}")


@camera_app.command("preview")
def preview(
    id_camera: str = typer.Argument(
        ..., metavar="ID", help="Id da câmera, como no registro (ex.: 000013)."
    ),
    out: Path | None = typer.Option(
        None,
        "--out",
        help=(
            "Caminho do PNG. Omitido, grava em "
            "<AUTO_COUNTER_DATA_DIR>/previews/<id>.png "
            f"(ou {DATA_DIR_PADRAO}/previews/<id>.png sem a variável)."
        ),
    ),
    config_dir: Path = OPCAO_CONFIG_DIR,
) -> None:
    """Grava o PNG de conferência da linha de contagem de uma câmera."""
    registro = _carrega(config_dir)

    escolhida = next((c for c in registro.cameras if c.id == id_camera), None)
    if escolhida is None:
        disponiveis = ", ".join(c.id for c in registro.cameras) or "nenhuma"
        raise _erro(
            f"câmera '{id_camera}' não está no registro {config_dir}. "
            f"Câmeras disponíveis: {disponiveis}."
        )

    destino = out or _caminho_padrao_do_preview(escolhida.id)

    try:
        frame = primeiro_frame(escolhida)
        gravado = gravar_preview(frame.imagem, escolhida, destino)
    except (BaseUrlAusenteError, FrameIndisponivelError, LinhaForaDoFrameError) as falha:
        raise _erro(str(falha)) from falha
    except OSError as falha:
        raise _erro(str(falha)) from falha

    typer.echo(f"PNG gravado em {gravado.caminho}")


app.add_typer(camera_app, name="camera")

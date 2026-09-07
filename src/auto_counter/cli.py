"""Ponto de entrada da CLI `auto-counter`.

A raiz hospeda um subgrupo por área: `camera` é o da feature
`configuracao-camera`, com os comandos `list` e `preview`; `session` é o da
feature `captura-clipes`, com o comando `capture` (D-1 do `_tasks.md`).

Comportamento em `.spec/features/configuracao-camera/spec.md`: AC-001.1 (a
listagem mostra exatamente as câmeras do registro, com id, nome e os dois
rótulos de sentido), AC-001.2 (as rejeições aparecem com arquivo e motivo, sem
derrubar as demais), AC-001.3 (id duplicado derruba o registro inteiro e o
comando sai com código diferente de zero), AC-001.5 (sem
`AUTO_COUNTER_BASE_URL` a montagem da URL falha com erro explícito), AC-002.1
(o preview grava o PNG com a linha e os rótulos) e AC-002.2 (linha fora do
frame não gera PNG).

De `.spec/features/captura-clipes/spec.md`: AC-003.3 (duração fora de 1..15
minutos é recusada antes de qualquer requisição), AC-003.5 (a opção de manter os
vídeos é explícita e vem desligada por padrão) e AC-003.6 (o Ctrl+C encerra a
sessão pela regra da duração real, e não mata o processo).

Todo erro tratado das camadas de baixo vira aqui mensagem legível em stderr e
código de saída diferente de zero — nunca traceback (`CLAUDE.md`).
"""

import os
import signal
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import typer
from dotenv import load_dotenv

from auto_counter.cameras.frame import FrameIndisponivelError, primeiro_frame
from auto_counter.cameras.geometry import LinhaForaDoFrameError
from auto_counter.cameras.model import Camera
from auto_counter.cameras.preview import gravar_preview
from auto_counter.cameras.registry import (
    DIRETORIO_PADRAO,
    DiretorioDeRegistroInvalidoError,
    IdDuplicadoError,
    Registro,
    carregar_registro,
)
from auto_counter.cameras.url import BaseUrlAusenteError
from auto_counter.capture.duration import (
    DURACAO_MAXIMA,
    DURACAO_MINIMA,
    DuracaoForaDoIntervaloError,
    validar_duracao,
)
from auto_counter.capture.session import ResultadoDaSessao, capturar

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

session_app = typer.Typer(
    name="session",
    help="Sessões de captura dos clipes de um minuto (D-1).",
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


@session_app.callback()
def session() -> None:
    """Sessões de captura dos clipes de um minuto."""


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


def _data_dir() -> Path:
    """Diretório de dados: `AUTO_COUNTER_DATA_DIR`, ou o padrão local."""
    valor = (os.environ.get(VARIAVEL_DATA_DIR) or "").strip()
    return Path(valor) if valor else DATA_DIR_PADRAO


def _caminho_padrao_do_preview(id_camera: str) -> Path:
    """`<data_dir>/previews/<id>.png` — o padrão quando `--out` é omitido."""
    return _data_dir() / SUBDIRETORIO_DE_PREVIEWS / f"{id_camera}.png"


def _camera_do_registro(registro: Registro, id_camera: str, config_dir: Path) -> Camera:
    """Resolve o id no registro, traduzindo a ausência em mensagem e código 1."""
    escolhida = next((c for c in registro.cameras if c.id == id_camera), None)
    if escolhida is None:
        disponiveis = ", ".join(c.id for c in registro.cameras) or "nenhuma"
        raise _erro(
            f"câmera '{id_camera}' não está no registro {config_dir}. "
            f"Câmeras disponíveis: {disponiveis}."
        )
    return escolhida


def _agora() -> datetime:
    """Relógio local em UTC, injetado no laço de captura (D-7).

    É atributo de módulo de propósito: o teste da CLI troca este nome por um
    relógio falso, porque uma sessão de 15 minutos com janela de 90 s não teria
    como ser dirigida em tempo real.
    """
    return datetime.now(timezone.utc)


def _dormir(segundos: float) -> None:
    """Espera de verdade entre as checagens, injetada no laço (D-7)."""
    time.sleep(segundos)


def _cliente_http() -> httpx.Client:
    """Cliente HTTP da sessão, construído **depois** da validação (AC-003.3).

    Também é atributo de módulo de propósito: o teste substitui esta função por
    um transporte dublê, e nenhum teste toca o servidor da NitTrans.
    """
    return httpx.Client(follow_redirects=True)


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
    escolhida = _camera_do_registro(registro, id_camera, config_dir)

    destino = out or _caminho_padrao_do_preview(escolhida.id)

    try:
        frame = primeiro_frame(escolhida)
        gravado = gravar_preview(frame.imagem, escolhida, destino)
    except (BaseUrlAusenteError, FrameIndisponivelError, LinhaForaDoFrameError) as falha:
        raise _erro(str(falha)) from falha
    except OSError as falha:
        raise _erro(str(falha)) from falha

    typer.echo(f"PNG gravado em {gravado.caminho}")


class ParadaPorCtrlC:
    """A parada explícita de AC-003.6 acionada pelo Ctrl+C do terminal.

    O sinal **não** mata a captura: ele marca que o usuário encerrou, e o laço
    (T-08) fecha a sessão pela regra da duração real, com os minutos já
    capturados preservados e o manifest fechado. É o mesmo gancho que o botão da
    interface vai acionar (AC-012.4 de `interface-sessao`).

    O segundo Ctrl+C aborta de verdade: o tratador se desinstala na primeira
    vez, então o seguinte volta a ser o comportamento padrão do Python — quem
    insiste está pedindo outra coisa.
    """

    def __init__(self) -> None:
        self._pedida = False

    def foi_pedida(self) -> bool:
        return self._pedida

    def pedir(self) -> None:
        self._pedida = True


def _imprime_resultado(resultado: ResultadoDaSessao) -> None:
    """Relatório final da sessão: o que foi pedido e o que realmente aconteceu."""
    perdidos = (
        ", ".join(str(item.minuto) for item in resultado.minutos_perdidos) or "nenhum"
    )
    encerramento = " (encerrada pelo usuário)" if resultado.encerrada_pelo_usuario else ""
    typer.echo(f"Sessão:           {resultado.id_sessao}")
    typer.echo(f"Duração pedida:   {resultado.duracao_pedida} min")
    typer.echo(f"Duração real:     {resultado.duracao_real} min{encerramento}")
    typer.echo(f"Status:           {resultado.status.value}")
    typer.echo(f"Minutos perdidos: {perdidos}")
    typer.echo(f"Início:           {resultado.inicio or '—'}")
    typer.echo(f"Fim:              {resultado.fim or '—'}")
    typer.echo(f"Clipes em:        {resultado.dir_sessao}")


@session_app.command("capture")
def capturar_sessao(
    id_camera: str = typer.Argument(
        ..., metavar="ID", help="Id da câmera, como no registro (ex.: 000013)."
    ),
    minutes: int = typer.Option(
        ...,
        "--minutes",
        help=f"Duração da captura, de {DURACAO_MINIMA} a {DURACAO_MAXIMA} minutos.",
    ),
    keep_clips: bool = typer.Option(
        False,
        "--keep-clips",
        help=(
            "Preserva os clipes no diretório da sessão. Desligado por padrão: "
            "sem ele, os vídeos são descartados no encerramento da sessão, "
            "depois do processamento."
        ),
    ),
    config_dir: Path = OPCAO_CONFIG_DIR,
) -> None:
    """Captura os clipes de um minuto da câmera durante a duração pedida.

    A ordem é obrigatória (AC-003.3): a duração é validada **antes** de resolver
    a câmera, montar a URL ou construir o cliente HTTP, para que uma duração
    fora de 1..15 saia com mensagem citando o limite e sem uma única requisição
    ao servidor.
    """
    try:
        duracao = validar_duracao(minutes)
    except DuracaoForaDoIntervaloError as falha:
        raise _erro(str(falha)) from falha

    registro = _carrega(config_dir)
    escolhida = _camera_do_registro(registro, id_camera, config_dir)

    parada = ParadaPorCtrlC()
    anterior = None

    def ao_receber_sigint(numero, quadro) -> None:  # pragma: no cover - via sinal
        if anterior is not None:
            # O segundo Ctrl+C aborta de verdade.
            signal.signal(signal.SIGINT, anterior)
        parada.pedir()
        typer.echo("")
        typer.echo("Encerrando a sessão a pedido do usuário...")

    try:
        anterior = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, ao_receber_sigint)
    except ValueError:
        # Fora da thread principal não há como instalar tratador; a captura
        # segue sem a parada por sinal, que é gancho de conveniência do CLI.
        anterior = None

    try:
        with _cliente_http() as cliente:
            resultado = capturar(
                escolhida,
                duracao,
                data_dir=_data_dir(),
                cliente=cliente,
                agora=_agora,
                dormir=_dormir,
                parada=parada,
                manter_videos=keep_clips,
            )
    except BaseUrlAusenteError as falha:
        raise _erro(str(falha)) from falha
    except OSError as falha:
        raise _erro(str(falha)) from falha
    except KeyboardInterrupt as falha:
        # Segundo Ctrl+C: aborto de verdade, e mesmo assim sem traceback.
        raise _erro(
            "captura abortada pelo usuário; os minutos já registrados estão no "
            "manifest da sessão"
        ) from falha
    finally:
        if anterior is not None:
            signal.signal(signal.SIGINT, anterior)

    _imprime_resultado(resultado)


app.add_typer(camera_app, name="camera")
app.add_typer(session_app, name="session")

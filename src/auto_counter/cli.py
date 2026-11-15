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

De `.spec/features/exportacao-xlsx/spec.md`: AC-010.1 (o comando `session
export` gera o XLSX no diretório de dados), AC-010.5 (sessão INVÁLIDA também
gera planilha, com o aviso) e AC-010.7 (a exportação lê apenas do banco).

De `.spec/features/interface-sessao/spec.md`: AC-011.4 (o comando `session run`
roda o pipeline completo até o XLSX sem iniciar a interface web), AC-013.1 e
AC-013.2 (a trava de sessão única recusa a segunda sessão, citando a câmera e o
horário da que está em curso, e ignora a trava órfã) e SUP-052 (a trava vale
para `session run`, `session capture` e `session process`; `session list` e
`session export` ficam livres).

De `.spec/features/interface-sessao/spec.md`: SUP-041 (o comando `ui` abre a
interface apenas em localhost, sem autenticação).

De `.spec/features/processamento-upload/spec.md`: AC-030.7 e SUP-098 (o comando
`session upload <id_camera> <arquivo>...` roda o pipeline completo até o XLSX
sem a interface web, recusa o arquivo inválido nomeando-o antes de qualquer
processamento, avisa a duplicata em `stderr` e pega a mesma trava de sessão
única), AC-030.2 (`session list`
mostra a origem de cada sessão, e o período da sessão de upload é marcado como
horário do processamento).

Todo erro tratado das camadas de baixo vira aqui mensagem legível em stderr e
código de saída diferente de zero — nunca traceback (`CLAUDE.md`).
"""

import signal
import subprocess
import sys
import time
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path

import httpx
import typer
from dotenv import load_dotenv

from auto_counter import ui as pacote_da_interface
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
from auto_counter.capture.manifest import NOME_DO_MANIFEST, diretorio_da_sessao
from auto_counter.capture.manifest import ler as ler_manifest
from auto_counter.capture.session import Parada, ResultadoDaSessao, capturar
from auto_counter.counting import model as modelo_de_deteccao
from auto_counter.counting.clip import DetectorDoClipe
from auto_counter.counting.config import ConfiguracaoDoProcessamento
from auto_counter.counting.detector import Detector, criar_sessao
from auto_counter.counting.model import (
    ModeloAusenteError,
    UltralyticsAusenteError,
    caminho_do_modelo,
)
from auto_counter.counting.session import (
    ResultadoDaContagem,
    SessaoSemClipes,
)
from auto_counter.export import (
    SessaoEmAndamentoError,
    SessaoNaoEncontradaError,
    SessaoNaoProcessadaError,
    exportar_sessao,
)
from auto_counter.export.format import linha_de_aviso
from auto_counter.pipeline.ambiente import (  # noqa: F401 (reexportados)
    DATA_DIR_PADRAO,
    VARIAVEL_DATA_DIR,
    data_dir_do_ambiente,
)
from auto_counter.pipeline.lock import OutraSessaoEmAndamentoError, adquirir_trava
from auto_counter.pipeline.preparo_upload import triar_arquivos
from auto_counter.pipeline.run import executar_sessao
from auto_counter.pipeline.upload import executar_upload
from auto_counter.counting.upload import processar_sessao_de_upload
from auto_counter.upload.manifest import NOME_DO_REGISTRO, apagar_videos
from auto_counter.upload.manifest import e_sessao_de_upload
from auto_counter.upload.manifest import ler as ler_registro_do_upload
from auto_counter.pipeline.state import Fase
from auto_counter.pipeline.stop import ParadaComposta, ParadaPorArquivo
from auto_counter.pipeline.processing import (
    PersistenciaFalhouError,
    conferir_modelo,
    persistir_e_descartar,
    processar,
)
from auto_counter.storage.connection import caminho_do_banco
from auto_counter.storage.connection import conectar as conectar_ao_banco
from auto_counter.storage.model import OrigemDaSessao
from auto_counter.storage.persist import persistir_sessao, persistir_sessao_de_upload
from auto_counter.storage.sessions import (
    PersistenciaDaCaptura,
    ler_sessao,
    listar_sessoes,
)

SUBDIRETORIO_DE_PREVIEWS = "previews"
"""Onde o PNG cai dentro do diretório de dados quando `--out` é omitido."""

TETO_DE_ENVIO_DO_STREAMLIT_EM_MB = 2048
"""Teto do `file_uploader` do Streamlit, em MB (R-2 de `upload-videos`).

O componente mantém o arquivo inteiro em memória e recusa, com a mensagem dele,
o que passar deste teto, antes de o app ver o arquivo. Com 2048 MB, todo arquivo
de 1 GB a ~2 GB chega ao app, que mostra a mensagem de AC-027.10. O limite de
1 GB **em bytes** é do app (`pipeline/envio.py`), não do Streamlit.
"""

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

model_app = typer.Typer(
    name="model",
    help="Preparação do modelo de detecção usado no processamento (D-6).",
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


@model_app.callback()
def model() -> None:
    """Preparação do modelo de detecção usado no processamento."""


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
    return data_dir_do_ambiente()


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


def _executar_ui(comando: list[str]) -> int:
    """Executa o servidor da interface e devolve o código de saída dele.

    Atributo de módulo de propósito, como `_cliente_http` e `_agora`: o teste
    troca este nome, e nenhum teste sobe o Streamlit de verdade.
    """
    return subprocess.call(comando)


def _trava(data_dir: Path, comando: str, camera_: Camera):
    """A trava de sessão única do comando (AC-013.1, AC-013.2, SUP-052).

    Contexto que o comando entra **antes** de qualquer requisição ou leitura de
    vídeo; a recusa sobe como `OutraSessaoEmAndamentoError`, que cada comando
    traduz em mensagem e código 1.
    """
    return adquirir_trava(
        data_dir,
        comando=comando,
        id_camera=camera_.id,
        nome_camera=camera_.nome,
        agora=_agora,
    )


def _cliente_http() -> httpx.Client:
    """Cliente HTTP da sessão, construído **depois** da validação (AC-003.3).

    Também é atributo de módulo de propósito: o teste substitui esta função por
    um transporte dublê, e nenhum teste toca o servidor da NitTrans.
    """
    return httpx.Client(follow_redirects=True)


def _detector(
    caminho_do_onnx: Path, config: ConfiguracaoDoProcessamento
) -> DetectorDoClipe:
    """Constrói o detector real a partir do `.onnx` (SUP-015).

    Também é atributo de módulo de propósito, como `_cliente_http` e `_agora`:
    o teste do comando troca este nome por um detector dublê (D-8), e nenhum
    teste desta suíte carrega o modelo de verdade.
    """
    return Detector(criar_sessao(caminho_do_onnx), config)


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

    data_dir = _data_dir()

    try:
        with ExitStack() as pilha:
            # Antes de qualquer requisição: a segunda sessão é recusada sem
            # tocar o servidor (AC-013.1).
            pilha.enter_context(_trava(data_dir, "capture", escolhida))
            cliente = pilha.enter_context(_cliente_http())

            # Falha ao abrir o banco não interrompe a captura (`CLAUDE.md`):
            # 15 minutos perdidos não se recuperam, e o manifest continua
            # sendo prova durável suficiente até o processamento regravar a
            # sessão (D-7 de `persistencia-resultados/_tasks.md`).
            conexao = None
            try:
                conexao = pilha.enter_context(conectar_ao_banco(data_dir))
            except Exception as falha_do_banco:  # noqa: BLE001
                typer.echo(
                    f"aviso: não foi possível abrir o banco em {data_dir}: "
                    f"{falha_do_banco}; a sessão será capturada sem "
                    f"persistência no banco",
                    err=True,
                )

            persistencia = (
                None
                if conexao is None
                else PersistenciaDaCaptura(conexao, camera=escolhida)
            )

            resultado = capturar(
                escolhida,
                duracao,
                data_dir=data_dir,
                cliente=cliente,
                agora=_agora,
                dormir=_dormir,
                parada=parada,
                manter_videos=keep_clips,
                persistencia=persistencia,
            )
    except OutraSessaoEmAndamentoError as falha:
        raise _erro(str(falha)) from falha
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


class _ParadaPorSinal:
    """O Ctrl+C como parada explícita, **uma por fase** do `session run`.

    A cada `nova()` instala um tratador de SIGINT e devolve uma parada nova,
    composta com o pedido por arquivo da interface. O primeiro Ctrl+C de cada
    fase é o encerramento explícito (AC-003.6 na captura, AC-012.5 no
    processamento); o tratador se desinstala nessa hora, então o segundo da
    mesma fase aborta de verdade, como em `session capture`.
    """

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._original = None
        self._instalado = False

    def nova(self) -> Parada:
        sinal = ParadaPorCtrlC()

        def ao_receber_sigint(numero, quadro) -> None:  # pragma: no cover - via sinal
            self._desinstalar()
            sinal.pedir()
            typer.echo("")
            typer.echo("Encerrando a sessão a pedido do usuário...")

        try:
            if self._original is None:
                self._original = signal.getsignal(signal.SIGINT)
            signal.signal(signal.SIGINT, ao_receber_sigint)
            self._instalado = True
        except ValueError:
            # Fora da thread principal não há como instalar tratador; a parada
            # por arquivo continua valendo.
            pass
        return ParadaComposta(sinal, ParadaPorArquivo(self._data_dir))

    def _desinstalar(self) -> None:
        if self._instalado and self._original is not None:
            signal.signal(signal.SIGINT, self._original)
        self._instalado = False

    def restaurar(self) -> None:
        self._desinstalar()


@session_app.command("run")
def executar_sessao_completa(
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
        help="Preserva os clipes no diretório da sessão. Desligado por padrão.",
    ),
    config_dir: Path = OPCAO_CONFIG_DIR,
) -> None:
    """Captura, processa e exporta uma sessão, da câmera ao XLSX (AC-011.4).

    É o mesmo comando que a interface dispara em segundo plano. Usa os padrões
    de processamento (sem `--threshold` nem `--sample-rate`) e não inicia a
    interface web. A ordem é a de `session capture`: a duração é validada antes
    de resolver a câmera, e a trava de sessão única é pega antes de qualquer
    requisição (AC-013.1).

    Ctrl+C na captura encerra a sessão pela regra da duração real, e os minutos
    já capturados seguem para o processamento (AC-003.6). Ctrl+C no
    processamento o cancela: nada é gravado e os vídeos ficam para
    `session process` (AC-012.5).
    """
    try:
        duracao = validar_duracao(minutes)
    except DuracaoForaDoIntervaloError as falha:
        raise _erro(str(falha)) from falha

    registro = _carrega(config_dir)
    escolhida = _camera_do_registro(registro, id_camera, config_dir)
    data_dir = _data_dir()
    sinal = _ParadaPorSinal(data_dir)

    try:
        with _trava(data_dir, "run", escolhida), ExitStack() as pilha:
            estado = executar_sessao(
                escolhida,
                duracao,
                data_dir=data_dir,
                cliente=pilha.enter_context(_cliente_http()),
                agora=_agora,
                dormir=_dormir,
                criar_detector=lambda caminho, config: _detector(caminho, config),
                criar_parada=sinal.nova,
                manter_videos=keep_clips,
            )
    except OutraSessaoEmAndamentoError as falha:
        raise _erro(str(falha)) from falha
    except KeyboardInterrupt as falha:
        raise _erro(
            "sessão abortada pelo usuário; os minutos já registrados estão no "
            "manifest da sessão"
        ) from falha
    except typer.Exit:
        raise
    except Exception as falha:  # noqa: BLE001 — nenhuma falha crua chega ao usuário
        raise _erro(str(falha) or type(falha).__name__) from falha
    finally:
        sinal.restaurar()

    typer.echo(f"Sessão:            {estado.id_sessao}")
    if estado.status is not None:
        typer.echo(f"Status:            {estado.status}")

    if estado.fase is Fase.CONCLUIDA:
        typer.echo(f"Planilha:          {estado.planilha}")
        with conectar_ao_banco(data_dir) as conexao:
            aviso = linha_de_aviso(ler_sessao(conexao, estado.id_sessao))
        if aviso is not None:
            typer.echo(aviso)
        return

    if estado.fase is Fase.PROCESSAMENTO_CANCELADO:
        typer.echo(estado.mensagem)
        return

    raise _erro(estado.mensagem or "a sessão terminou sem planilha")


@session_app.command("upload")
def enviar_videos(
    id_camera: str = typer.Argument(
        ..., metavar="ID", help="Id da câmera, como no registro (ex.: 000013)."
    ),
    arquivos: list[Path] = typer.Argument(
        ..., metavar="ARQUIVO...", help="Um ou mais vídeos a contar, na ordem."
    ),
    nome: list[str] | None = typer.Option(
        None,
        "--nome",
        hidden=True,
        help="Nome original de cada arquivo, na mesma ordem (só a interface usa).",
    ),
    config_dir: Path = OPCAO_CONFIG_DIR,
) -> None:
    """Conta vídeos enviados como uma sessão e exporta o XLSX (AC-030.7).

    É o mesmo comando que a interface dispara em segundo plano para a fonte
    "Fazer upload de vídeos". Usa os padrões de processamento (sem
    `--threshold`, `--sample-rate` nem `--keep-clips`: a cópia recebida é apagada
    ao fim da sessão concluída, SUP-097) e não inicia a interface web.

    A ordem é a de D-13: a câmera do registro e a triagem dos arquivos
    (existência, extensão e tamanho) vêm antes da trava de sessão única
    (AC-028.2); só depois entram a leitura de cada vídeo, a resolução da câmera
    e o limite de 15 min somados. Toda recusa nomeia o arquivo. Duplicata só
    avisa em `stderr`. Ctrl+C no processamento o cancela: nada é gravado e os
    vídeos ficam para `session process` (AC-029.1).
    """
    nomes = list(nome) if nome else [arquivo.name for arquivo in arquivos]
    if len(nomes) != len(arquivos):
        raise _erro(
            f"--nome foi dado {len(nomes)} vez(es) para {len(arquivos)} "
            "arquivo(s); passe um --nome por arquivo, na mesma ordem"
        )

    registro = _carrega(config_dir)
    escolhida = _camera_do_registro(registro, id_camera, config_dir)
    try:
        triar_arquivos(arquivos, nomes)
    except ValueError as falha:
        raise _erro(str(falha)) from falha

    data_dir = _data_dir()
    sinal = _ParadaPorSinal(data_dir)

    def avisar(mensagem: str) -> None:
        typer.secho(f"aviso: {mensagem}", err=True, fg=typer.colors.YELLOW)

    try:
        with _trava(data_dir, "upload", escolhida):
            estado = executar_upload(
                escolhida,
                arquivos,
                nomes,
                data_dir=data_dir,
                agora=_agora,
                criar_detector=lambda caminho, config: _detector(caminho, config),
                criar_parada=sinal.nova,
                ao_avisar=avisar,
            )
    except OutraSessaoEmAndamentoError as falha:
        raise _erro(str(falha)) from falha
    except KeyboardInterrupt as falha:
        raise _erro(
            "sessão abortada pelo usuário; os vídeos recebidos ficam em "
            "sessions/ para `session process`"
        ) from falha
    except typer.Exit:
        raise
    except Exception as falha:  # noqa: BLE001 — nenhuma falha crua chega ao usuário
        raise _erro(str(falha) or type(falha).__name__) from falha
    finally:
        sinal.restaurar()

    typer.echo(f"Sessão:            {estado.id_sessao}")
    if estado.status is not None:
        typer.echo(f"Status:            {estado.status}")

    if estado.fase is Fase.CONCLUIDA:
        typer.echo(f"Planilha:          {estado.planilha}")
        with conectar_ao_banco(data_dir) as conexao:
            aviso = linha_de_aviso(ler_sessao(conexao, estado.id_sessao))
        if aviso is not None:
            typer.echo(aviso)
        return

    if estado.fase is Fase.PROCESSAMENTO_CANCELADO:
        typer.echo(estado.mensagem)
        return

    raise _erro(estado.mensagem or "a sessão terminou sem planilha")


@app.command("ui")
def abrir_interface(
    port: int = typer.Option(8501, "--port", help="Porta local da interface."),
    config_dir: Path = OPCAO_CONFIG_DIR,
) -> None:
    """Abre a interface local da sessão no navegador (SUP-041).

    Escuta apenas em 127.0.0.1 e sem autenticação: o sistema é monousuário e roda
    na máquina de quem o usa. Fechar o navegador não encerra uma sessão em
    andamento, e este comando não pega a trava de sessão única — quem pega é a
    sessão, que roda num processo à parte.
    """
    script = Path(pacote_da_interface.__file__).parent / "app.py"
    comando = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(script),
        "--server.address",
        "127.0.0.1",
        "--server.port",
        str(port),
        "--browser.gatherUsageStats",
        "false",
        "--server.maxUploadSize",
        str(TETO_DE_ENVIO_DO_STREAMLIT_EM_MB),
        "--",
        "--config-dir",
        str(config_dir.resolve()),
    ]
    try:
        codigo = _executar_ui(comando)
    except KeyboardInterrupt:
        return
    except OSError as falha:
        raise _erro(f"não foi possível iniciar a interface: {falha}") from falha
    if codigo != 0:
        raise typer.Exit(code=codigo)


def _configuracao(threshold: float | None, sample_rate: int | None):
    """A configuração do processamento com o que a linha de comando mudou.

    Os padrões são os de T-02 (SUP-016 e SUP-017); `--threshold` e
    `--sample-rate` existem porque as duas suplementares dizem "configurável".
    O valor efetivamente usado é gravado no `eventos.json` (AC-008.1).
    """
    padrao = ConfiguracaoDoProcessamento()
    return ConfiguracaoDoProcessamento(
        limiar_de_confianca=(
            padrao.limiar_de_confianca if threshold is None else threshold
        ),
        amostragem=padrao.amostragem if sample_rate is None else sample_rate,
        tamanho_de_entrada=padrao.tamanho_de_entrada,
        janela_de_emenda_em_segundos=padrao.janela_de_emenda_em_segundos,
        tolerancia_da_assinatura=padrao.tolerancia_da_assinatura,
    )


def _contagem_por(eventos, atributo: str) -> str:
    """`RÓTULO: n` de cada valor presente, em ordem, ou `nenhum`."""
    totais: dict[str, int] = {}
    for evento in eventos:
        chave = getattr(evento, atributo)
        chave = chave.value if hasattr(chave, "value") else str(chave)
        totais[chave] = totais.get(chave, 0) + 1
    return ", ".join(f"{chave}: {totais[chave]}" for chave in sorted(totais)) or "nenhum"


def _imprime_contagem(
    resultado: ResultadoDaContagem,
    camera_: Camera,
    config: ConfiguracaoDoProcessamento,
    *,
    amostragem_por_fps: bool = False,
) -> None:
    """Relatório final do processamento: o que foi contado e com o quê.

    Na sessão de upload a amostragem é por frames por segundo de vídeo
    (SUP-090), e não 1 a cada N; `amostragem_por_fps` troca só essa linha.
    """
    registro = resultado.registro
    processados = ", ".join(str(m) for m in resultado.minutos_processados) or "nenhum"
    sem_dado = (
        ", ".join(
            f"{item.minuto} ({item.motivo})" for item in resultado.minutos_nao_processados
        )
        or "nenhum"
    )
    typer.echo(f"Sessão:            {registro.id_sessao}")
    typer.echo(f"Câmera:            {camera_.id}  {camera_.nome}")
    typer.echo(f"Minutos com dado:  {processados}")
    typer.echo(f"Minutos sem dado:  {sem_dado}")
    typer.echo(f"Total de eventos:  {len(resultado.eventos)}")
    typer.echo(f"Por sentido:       {_contagem_por(resultado.eventos, 'sentido')}")
    typer.echo(f"Por categoria:     {_contagem_por(resultado.eventos, 'categoria')}")
    typer.echo(f"Versão do modelo:  {registro.versao_do_modelo}")
    typer.echo(f"Limiar:            {config.limiar_de_confianca}")
    if amostragem_por_fps:
        typer.echo(
            f"Amostragem:        {config.frames_por_segundo} frames por segundo "
            "de vídeo"
        )
    else:
        typer.echo(f"Amostragem:        1 frame a cada {config.amostragem}")
    typer.echo(f"Eventos em:        {resultado.caminho}")


@session_app.command("process")
def processar_sessao_capturada(
    id_sessao: str = typer.Argument(
        ...,
        metavar="ID_SESSAO",
        help="Id da sessão, como no diretório de dados (ex.: 000013-...Z).",
    ),
    threshold: float | None = typer.Option(
        None,
        "--threshold",
        help=(
            "Limiar de confiança das detecções. Padrão: "
            f"{ConfiguracaoDoProcessamento().limiar_de_confianca} (SUP-016)."
        ),
    ),
    sample_rate: int | None = typer.Option(
        None,
        "--sample-rate",
        help=(
            "Analisa 1 frame a cada N. Padrão: "
            f"{ConfiguracaoDoProcessamento().amostragem} (SUP-017)."
        ),
    ),
    config_dir: Path = OPCAO_CONFIG_DIR,
) -> None:
    """Conta e classifica os veículos dos clipes de uma sessão já capturada.

    A câmera **não** é redigitada: vem do `id_camera` gravado no manifest, para
    que a linha de contagem usada seja a daquela câmera (`CLAUDE.md`).

    Terminado o processamento **com sucesso**, os vídeos da sessão são
    descartados, a menos que o manifest traga `manter_videos` (AC-003.5, D-5).
    Processamento que falha não apaga nada.

    Numa sessão de upload (`upload.json`, AC-029.3), todos os vídeos são
    contados desde o primeiro, com os padrões de processamento (por isso
    `--threshold` e `--sample-rate` são recusados), o resultado é gravado como o
    de uma sessão de upload concluída e os vídeos são apagados em seguida
    (AC-030.6). A planilha sai com `session export`.
    """
    data_dir = _data_dir()
    dir_sessao = diretorio_da_sessao(data_dir, id_sessao)
    # AC-029.3, D-14: a presença do `upload.json` identifica a sessão de upload.
    if e_sessao_de_upload(dir_sessao):
        _processar_upload_gravado(
            id_sessao, threshold, sample_rate, data_dir, dir_sessao, config_dir
        )
        return

    try:
        config = _configuracao(threshold, sample_rate)
    except ValueError as falha:
        raise _erro(str(falha)) from falha

    if not (dir_sessao / NOME_DO_MANIFEST).is_file():
        raise _erro(
            f"sessão '{id_sessao}' não encontrada: não há {NOME_DO_MANIFEST} "
            f"nem {NOME_DO_REGISTRO} em {dir_sessao}"
        )

    try:
        manifest = ler_manifest(dir_sessao)
    except (OSError, ValueError, KeyError) as falha:
        raise _erro(
            f"o {NOME_DO_MANIFEST} de {dir_sessao} não pôde ser lido: {falha}"
        ) from falha

    registro = _carrega(config_dir)
    escolhida = _camera_do_registro(registro, manifest.id_camera, config_dir)

    try:
        with _trava(data_dir, "process", escolhida):
            _processar_e_persistir(
                config, data_dir, dir_sessao, manifest.manter_videos, escolhida
            )
    except OutraSessaoEmAndamentoError as falha:
        raise _erro(str(falha)) from falha


def _processar_upload_gravado(
    id_sessao: str,
    threshold: float | None,
    sample_rate: int | None,
    data_dir: Path,
    dir_sessao: Path,
    config_dir: Path,
) -> None:
    """`session process` numa sessão de upload, em disco (D-14, AC-029.3)."""
    if threshold is not None or sample_rate is not None:
        raise _erro(
            "--threshold e --sample-rate não valem para uma sessão de upload: "
            "ela usa os padrões de processamento (AC-028.4, SUP-090)"
        )

    try:
        registro_do_upload = ler_registro_do_upload(dir_sessao)
    except (OSError, ValueError, KeyError) as falha:
        raise _erro(
            f"o {NOME_DO_REGISTRO} de {dir_sessao} não pôde ser lido: {falha}"
        ) from falha

    ausentes = [
        video.nome_original
        for video in registro_do_upload.videos
        if not (dir_sessao / video.arquivo).is_file()
    ]
    if ausentes:
        raise _erro(
            f"os vídeos da sessão '{id_sessao}' já foram apagados ou não estão "
            f"mais em {dir_sessao} ({', '.join(ausentes)}); não há o que "
            "reprocessar"
        )

    registro = _carrega(config_dir)
    escolhida = _camera_do_registro(registro, registro_do_upload.id_camera, config_dir)
    config = ConfiguracaoDoProcessamento()

    try:
        with _trava(data_dir, "process", escolhida):
            try:
                caminho_do_onnx, versao = conferir_modelo(data_dir)
            except (ModeloAusenteError, OSError) as falha:
                raise _erro(str(falha)) from falha

            inicio = _agora()
            try:
                resultado = processar_sessao_de_upload(
                    dir_sessao,
                    camera=escolhida,
                    detector=_detector(caminho_do_onnx, config),
                    config=config,
                    versao_do_modelo=versao,
                    inicio_do_processamento=inicio,
                )
            except (SessaoSemClipes, OSError) as falha:
                raise _erro(str(falha)) from falha
            fim = _agora()

            _imprime_contagem(resultado, escolhida, config, amostragem_por_fps=True)

            # A persistência vem antes do descarte (AC-030.6): falha no banco
            # preserva os vídeos e a sessão pode ser reprocessada.
            try:
                with conectar_ao_banco(data_dir) as conexao:
                    resumo = persistir_sessao_de_upload(
                        conexao, dir_sessao, camera=escolhida, inicio=inicio, fim=fim
                    )
            except Exception as falha:  # noqa: BLE001
                raise _erro(
                    f"não foi possível persistir a sessão no banco: {falha}; os "
                    "vídeos não foram apagados e esta sessão pode ser reprocessada"
                ) from falha
            apagados = apagar_videos(dir_sessao)
    except OutraSessaoEmAndamentoError as falha:
        raise _erro(str(falha)) from falha

    typer.echo(f"Banco:             {caminho_do_banco(data_dir)}")
    typer.echo(
        f"Persistido:        {resumo.eventos_gravados} evento(s), "
        f"{resumo.minutos_capturados} minuto(s) com dado, "
        f"{resumo.minutos_sem_dado} minuto(s) sem dado"
    )
    typer.echo(
        f"Vídeos:            {apagados} arquivo(s) de vídeo apagado(s); esta "
        "sessão não pode mais ser reprocessada"
    )


def _processar_e_persistir(
    config: ConfiguracaoDoProcessamento,
    data_dir: Path,
    dir_sessao: Path,
    manter_videos: bool,
    escolhida: Camera,
) -> None:
    """O corpo de `session process` que roda com a trava de sessão única."""
    # O modelo é conferido **antes** de abrir qualquer vídeo: descobrir que ele
    # falta depois de minutos de processamento seria desperdício puro.
    try:
        caminho_do_onnx, versao = conferir_modelo(data_dir)
    except ModeloAusenteError as falha:
        raise _erro(str(falha)) from falha
    except OSError as falha:
        raise _erro(str(falha)) from falha

    try:
        resultado = processar(
            dir_sessao,
            camera=escolhida,
            detector=_detector(caminho_do_onnx, config),
            config=config,
            versao_do_modelo=versao,
        )
    except SessaoSemClipes as falha:
        raise _erro(str(falha)) from falha
    except OSError as falha:
        raise _erro(str(falha)) from falha

    _imprime_contagem(resultado, escolhida, config)

    # D-3 de `persistencia-resultados/_tasks.md`: a persistência acontece
    # ANTES do descarte dos vídeos. Falha aqui aborta o comando e preserva os
    # clipes — invertido, uma falha de banco deixaria a sessão sem vídeo e
    # sem resultado, e o banco é a única coisa que sobrevive ao fim da sessão.
    try:
        persistido = persistir_e_descartar(
            data_dir,
            dir_sessao,
            camera=escolhida,
            manter_videos=manter_videos,
            persistir=persistir_sessao,
        )
    except PersistenciaFalhouError as falha:
        raise _erro(
            f"não foi possível persistir a sessão no banco: {falha}; os "
            f"vídeos não foram apagados e esta sessão pode ser reprocessada"
        ) from falha

    resumo = persistido.resumo
    typer.echo(f"Banco:             {persistido.banco}")
    typer.echo(
        f"Persistido:        {resumo.eventos_gravados} evento(s), "
        f"{resumo.minutos_capturados} minuto(s) com dado, "
        f"{resumo.minutos_sem_dado} minuto(s) sem dado"
    )

    # D-5: só depois do processamento e da persistência os vídeos vão embora
    # (a ordem é garantida por `persistir_e_descartar`).
    if persistido.videos_apagados is None:
        typer.echo("Clipes:            preservados (manter_videos na sessão)")
    else:
        typer.echo(
            f"Clipes:            {persistido.videos_apagados} arquivo(s) de "
            "vídeo apagado(s); esta sessão não pode mais ser reprocessada"
        )


@session_app.command("list")
def listar_sessoes_capturadas(
    limit: int | None = typer.Option(
        None,
        "--limit",
        help="Limita a quantidade de sessões listadas. Padrão: todas (SUP-029).",
    ),
) -> None:
    """Lista o histórico de sessões, da mais recente para a mais antiga.

    Lê apenas o banco (US-009): não toca em vídeo nem em rede, e por isso uma
    sessão cujos clipes já foram apagados continua aparecendo (AC-009.1).

    Nenhuma câmera é resolvida pelo registro — o id da câmera já está gravado
    na linha de cada sessão.

    Cada linha traz a origem da sessão, CAMERA ou UPLOAD (AC-030.2, feature
    `processamento-upload`). Na sessão de upload o período é o do
    processamento, e não o de gravação dos vídeos (Q-020), então ganha a marca
    "(horário do processamento)".

    A sessão cancelada pelo usuário na captura (AC-008.6) mostra a marca "·
    cancelada pelo usuário" depois do status, para não ser lida como sessão
    válida sem tráfego (AC-009.2).
    """
    data_dir = _data_dir()
    caminho = caminho_do_banco(data_dir)

    # O banco é criado na primeira conexão (SUP-024); uma listagem não deve
    # ter o efeito colateral de criar um banco vazio sozinha. Sem arquivo
    # ainda, o histórico é vazio por definição, sem precisar conectar.
    if not caminho.is_file():
        typer.echo(
            f"Nenhuma sessão foi gravada ainda. O banco seria criado em "
            f"{caminho}."
        )
        return

    try:
        with conectar_ao_banco(data_dir) as conexao:
            sessoes = listar_sessoes(conexao, limite=limit)
    except Exception as falha:  # noqa: BLE001 — nenhuma falha de banco crua
        raise _erro(f"não foi possível consultar o histórico: {falha}") from falha

    if not sessoes:
        typer.echo(f"Nenhuma sessão foi gravada ainda no banco em {caminho}.")
        return

    for item in sessoes:
        status_texto = "—" if item.status is None else item.status.value
        if item.cancelada_pelo_usuario:
            status_texto += " · cancelada pelo usuário"
        periodo = f"{item.inicio or '—'} .. {item.fim or '—'}"
        if item.origem is OrigemDaSessao.UPLOAD:
            periodo += " (horário do processamento)"
        typer.echo(
            f"{item.id_sessao}  {item.origem.value} {item.id_camera}  {periodo}  "
            f"{status_texto}  {item.total_de_eventos} veículo(s)"
        )


@session_app.command("export")
def exportar_sessao_gravada(
    id_sessao: str = typer.Argument(
        ...,
        metavar="ID_SESSAO",
        help="Id da sessão, como no histórico (ex.: 000013-...Z).",
    ),
) -> None:
    """Exporta o resultado de uma sessão processada em XLSX (US-010).

    Lê apenas o banco: não toca em vídeo nem em rede, e por isso funciona
    depois que os clipes foram apagados (AC-010.7). O arquivo cai no diretório
    de dados. Sessão INVÁLIDA também gera planilha, com o aviso nas abas e no
    nome do arquivo (AC-010.5).
    """
    data_dir = _data_dir()
    caminho_banco = caminho_do_banco(data_dir)

    # Foi pedida uma sessão específica, então banco ausente é erro — e a
    # exportação não pode criar um banco vazio só por ter sido chamada.
    if not caminho_banco.is_file():
        raise _erro(
            f"nenhuma sessão foi gravada ainda: o banco {caminho_banco} não existe"
        )

    try:
        with conectar_ao_banco(data_dir) as conexao:
            caminho = exportar_sessao(conexao, id_sessao, data_dir=data_dir)
            sessao = ler_sessao(conexao, id_sessao)
    except (
        SessaoNaoEncontradaError,
        SessaoEmAndamentoError,
        SessaoNaoProcessadaError,
    ) as falha:
        raise _erro(str(falha)) from falha
    except Exception as falha:  # noqa: BLE001 — nenhuma falha crua de banco ou disco
        raise _erro(f"não foi possível exportar a sessão '{id_sessao}': {falha}") from falha

    typer.echo(f"Planilha:          {caminho}")
    typer.echo(f"Status:            {sessao.status.value}")
    aviso = linha_de_aviso(sessao)
    if aviso is not None:
        typer.echo(aviso)


@model_app.command("export")
def exportar_modelo(
    out: Path | None = typer.Option(
        None,
        "--out",
        help=(
            "Caminho do .onnx. Omitido, grava em "
            "<AUTO_COUNTER_DATA_DIR>/models/yolo11n.onnx "
            f"(ou {DATA_DIR_PADRAO}/models/yolo11n.onnx sem a variável)."
        ),
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Reexporta mesmo que o arquivo já exista no destino.",
    ),
) -> None:
    """Baixa o YOLO11n e o exporta para ONNX com entrada 640×640 (SUP-015).

    É passo manual de preparação de máquina (D-2): o download e a exportação
    não cabem no orçamento de tempo de AC-005.4, então nunca acontecem na
    primeira execução do processamento.
    """
    destino = out or caminho_do_modelo(_data_dir())

    if destino.exists() and not force:
        # Reexportar é download de peso: o acidente não pode custar isso.
        typer.echo(
            f"O modelo já existe em {destino}; nada a fazer. "
            "Use --force para reexportar."
        )
        raise typer.Exit(code=0)

    try:
        gravado = modelo_de_deteccao.exportar(destino)
    except UltralyticsAusenteError as falha:
        raise _erro(str(falha)) from falha
    except OSError as falha:
        raise _erro(str(falha)) from falha

    typer.echo(f"Modelo exportado em {gravado}")
    typer.echo(f"Versão do modelo: {modelo_de_deteccao.versao_do_modelo(gravado)}")


app.add_typer(camera_app, name="camera")
app.add_typer(session_app, name="session")
app.add_typer(model_app, name="model")

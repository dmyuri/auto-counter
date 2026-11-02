"""Disparo da sessão em segundo plano — T-14.

Comportamento em `.spec/features/interface-sessao/spec.md`: AC-012.4 (a sessão
não depende da janela do navegador nem do servidor da interface), AC-013.1 (a
segunda sessão é recusada antes de disparar) e AC-011.2 (a duração é validada
antes de disparar).

A sessão roda como `python -m auto_counter session run ...`, num processo
**destacado** de quem o disparou: no Windows com `DETACHED_PROCESS` e
`CREATE_NEW_PROCESS_GROUP`, no POSIX com `start_new_session`. Assim, nem fechar
a aba nem derrubar o servidor da interface (Ctrl+C no terminal do `ui`)
encerram a sessão. Entrada fechada e saída num arquivo de log, com UTF-8
forçado, porque o processo destacado não tem console.

A trava de sessão única é pega pelo **filho**. Aqui ela só é consultada, para
recusar cedo e sem disparar nada; a corrida entre dois disparos simultâneos é
resolvida pela criação exclusiva da trava, e o segundo filho sai com código 1
sem tocar no estado da sessão em curso.
"""

import os
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from auto_counter.capture.duration import validar_duracao
from auto_counter.pipeline.ambiente import VARIAVEL_DATA_DIR
from auto_counter.pipeline.lock import OutraSessaoEmAndamentoError, ler_trava
from auto_counter.pipeline.progress import Situacao, ler_progresso
from auto_counter.pipeline.stop import consumir_pedido, pedir_parada

SUBDIRETORIO_DE_LOGS = "logs"
"""Onde o log do processo destacado cai dentro do diretório de dados."""

FORMATO_DO_CARIMBO = "%Y%m%dT%H%M%SZ"

LINHAS_DO_LOG_NA_MENSAGEM = 5
"""Quantas linhas do fim do log vão na mensagem quando o filho sai cedo."""


@dataclass
class SessaoDisparada:
    """O processo destacado e o arquivo onde ele escreve."""

    processo: subprocess.Popen
    log: Path
    id_camera: str
    data_dir: Path


def _opcoes_de_destacamento() -> dict:
    if sys.platform == "win32":
        return {
            "creationflags": subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NEW_PROCESS_GROUP
        }
    return {"start_new_session": True}


def iniciar_sessao(
    id_camera: str,
    minutos: int,
    *,
    data_dir: str | Path,
    config_dir: str | Path,
    popen: Callable[..., subprocess.Popen] = subprocess.Popen,
) -> SessaoDisparada:
    """Dispara `session run` num processo destacado e devolve o acesso a ele.

    Duração fora de 1..15 levanta `DuracaoForaDoIntervaloError` (AC-011.2) e
    sessão em curso levanta `OutraSessaoEmAndamentoError` (AC-013.1), nos dois
    casos antes de abrir log ou disparar qualquer coisa.

    Nunca passa `--keep-clips` (D-13): o usuário da interface faz três coisas, e
    manter vídeo não é uma delas.
    """
    duracao = validar_duracao(minutos)
    data_dir = Path(data_dir)

    em_curso = ler_trava(data_dir)
    if em_curso is not None:
        raise OutraSessaoEmAndamentoError(em_curso)

    # Um pedido de encerramento esquecido de uma sessão anterior não pode
    # encerrar a nova.
    consumir_pedido(data_dir)

    carimbo = datetime.now(timezone.utc).strftime(FORMATO_DO_CARIMBO)
    log = data_dir / SUBDIRETORIO_DE_LOGS / f"run-{carimbo}.log"
    log.parent.mkdir(parents=True, exist_ok=True)

    ambiente = dict(os.environ)
    ambiente[VARIAVEL_DATA_DIR] = str(data_dir)
    ambiente["PYTHONUTF8"] = "1"
    ambiente["PYTHONIOENCODING"] = "utf-8"

    comando = [
        sys.executable,
        "-m",
        "auto_counter",
        "session",
        "run",
        id_camera,
        "--minutes",
        str(duracao),
        "--config-dir",
        str(config_dir),
    ]
    with open(log, "wb") as saida:
        processo = popen(
            comando,
            env=ambiente,
            stdin=subprocess.DEVNULL,
            stdout=saida,
            stderr=subprocess.STDOUT,
            **_opcoes_de_destacamento(),
        )
    return SessaoDisparada(
        processo=processo, log=log, id_camera=id_camera, data_dir=data_dir
    )


def _fim_do_log(log: Path) -> str:
    try:
        texto = log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    linhas = [linha for linha in texto.splitlines() if linha.strip()]
    return "\n".join(linhas[-LINHAS_DO_LOG_NA_MENSAGEM:])


def aguardar_inicio(
    disparada: SessaoDisparada,
    *,
    limite: float = 5.0,
    intervalo: float = 0.1,
    dormir: Callable[[float], None] = time.sleep,
    relogio: Callable[[], float] = time.monotonic,
) -> str | None:
    """Espera a sessão assumir a trava. `None` é sucesso; texto é o motivo.

    A trava é reconhecida pela câmera e pelo comando, e não pelo PID do
    `Popen`: no Windows, o `python.exe` de um ambiente virtual é um
    redirecionador que inicia o interpretador de verdade como filho, então o PID
    gravado na trava não é o que o `Popen` devolve.

    Se o filho sair antes, devolve o fim do log (a recusa por trava, a falta do
    modelo, o erro de câmera). Se o limite passar sem trava nem saída, devolve
    um aviso: a sessão pode ainda estar subindo.
    """
    prazo = relogio() + limite
    while True:
        trava = ler_trava(disparada.data_dir)
        if (
            trava is not None
            and trava.comando == "run"
            and trava.id_camera == disparada.id_camera
        ):
            return None

        codigo = disparada.processo.poll()
        if codigo is not None:
            fim = _fim_do_log(disparada.log)
            return fim or f"o processo da sessão saiu com código {codigo}"

        if relogio() >= prazo:
            return (
                f"a sessão não confirmou o início em {limite:g} s; o log está em "
                f"{disparada.log}"
            )
        dormir(intervalo)


def encerrar_sessao(data_dir: str | Path) -> bool:
    """Pede o encerramento da sessão em curso. Devolve se o pedido foi feito.

    É a ação explícita de AC-012.4: só pede quando há uma sessão que a interface
    sabe encerrar (`EM_ANDAMENTO` com `pode_encerrar`). Fora disso, não faz nada
    — nem cria o arquivo de pedido, que valeria para a próxima sessão.
    """
    progresso = ler_progresso(data_dir)
    if (
        progresso.situacao is Situacao.EM_ANDAMENTO
        and progresso.andamento is not None
        and progresso.andamento.pode_encerrar
    ):
        pedir_parada(data_dir)
        return True
    return False

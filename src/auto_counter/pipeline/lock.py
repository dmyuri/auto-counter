"""Trava de sessão única — T-04.

Comportamento em `.spec/features/interface-sessao/spec.md`: AC-013.1 (a segunda
sessão é recusada com a câmera e o horário de início da que está em curso, sem
afetá-la), AC-013.2 (trava órfã é ignorada), SUP-039 (a trava é um arquivo com o
PID do processo no diretório de dados) e SUP-052 (vale para todo comando que
baixa ou processa vídeo).

O arquivo é `<data_dir>/sessao.lock`, em JSON. Duas decisões moram aqui:

- **Criação exclusiva e atômica, com o conteúdo completo.** O JSON é gravado
  num temporário no mesmo diretório e publicado com `os.link`, que falha se o
  destino já existe. Nunca `os.replace`, que sobrescreveria a trava de quem
  chegou primeiro, e nunca "cria vazio e depois escreve", que deixaria um
  leitor ver uma trava sem conteúdo.
- **Viva é `pid` existente com o mesmo horário de criação do processo.** Só o
  PID não basta: o sistema reaproveita PIDs, e SUP-039 chama de órfã a trava
  cujo PID "não corresponde a um processo vivo". A checagem nunca usa
  `os.kill(pid, 0)`, que no Windows **encerra** o processo.
"""

import json
import os
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import psutil

from auto_counter.export.format import para_brasilia

NOME_DA_TRAVA = "sessao.lock"
"""Nome do arquivo dentro do diretório de dados (SUP-039)."""

TOLERANCIA_DO_HORARIO_DO_PROCESSO = 1.0
"""Segundos de diferença aceitos entre o `create_time` gravado e o lido.

Os dois vêm do mesmo `psutil`, mas o valor passa por JSON e por arredondamento
do sistema; um PID reaproveitado difere em ordens de grandeza a mais.
"""

TENTATIVAS_DE_REMOCAO = 5
ESPERA_ENTRE_TENTATIVAS = 0.05
"""No Windows, remover um arquivo que um leitor tem aberto levanta
`PermissionError` por instantes; algumas tentativas curtas bastam."""


@dataclass(frozen=True)
class InfoDaTrava:
    """O que a trava registra sobre a sessão em curso."""

    pid: int
    criado_em_do_processo: float
    comando: str
    id_camera: str
    nome_camera: str | None
    iniciada_em: datetime


def mensagem_de_sessao_em_andamento(info: InfoDaTrava) -> str:
    """O texto único da recusa de AC-013.1, para a CLI e a interface."""
    camera = (
        info.id_camera
        if info.nome_camera is None
        else f"{info.nome_camera} ({info.id_camera})"
    )
    inicio = para_brasilia(info.iniciada_em).strftime("%d/%m/%Y %H:%M")
    return (
        f"já existe uma sessão em andamento: câmera {camera}, iniciada em "
        f"{inicio} (horário de Brasília). Espere ela terminar para iniciar outra."
    )


class OutraSessaoEmAndamentoError(RuntimeError):
    """A trava está em poder de um processo vivo (AC-013.1)."""

    def __init__(self, info: InfoDaTrava) -> None:
        self.info = info
        super().__init__(mensagem_de_sessao_em_andamento(info))


def _caminho(data_dir: str | Path) -> Path:
    return Path(data_dir) / NOME_DA_TRAVA


def _serializar(info: InfoDaTrava) -> bytes:
    return json.dumps(
        {
            "pid": info.pid,
            "criado_em_do_processo": info.criado_em_do_processo,
            "comando": info.comando,
            "id_camera": info.id_camera,
            "nome_camera": info.nome_camera,
            "iniciada_em": info.iniciada_em.astimezone(timezone.utc).isoformat(),
        },
        ensure_ascii=False,
    ).encode("utf-8")


def _interpretar(bruto: bytes) -> InfoDaTrava | None:
    """O conteúdo como `InfoDaTrava`, ou `None` se estiver ilegível."""
    try:
        dados = json.loads(bruto.decode("utf-8"))
        iniciada_em = datetime.fromisoformat(dados["iniciada_em"])
        if iniciada_em.tzinfo is None:
            return None
        return InfoDaTrava(
            pid=int(dados["pid"]),
            criado_em_do_processo=float(dados["criado_em_do_processo"]),
            comando=str(dados["comando"]),
            id_camera=str(dados["id_camera"]),
            nome_camera=(
                None if dados["nome_camera"] is None else str(dados["nome_camera"])
            ),
            iniciada_em=iniciada_em.astimezone(timezone.utc),
        )
    except (ValueError, KeyError, TypeError):
        return None


def _esta_viva(info: InfoDaTrava) -> bool:
    """O processo dono da trava existe e é o mesmo que a gravou."""
    try:
        if not psutil.pid_exists(info.pid):
            return False
        criado_em = psutil.Process(info.pid).create_time()
    except psutil.NoSuchProcess:
        return False
    except psutil.AccessDenied:
        # O processo existe, só não deixa ser inspecionado. Recusar uma sessão
        # nova custa pouco; passar por cima de uma sessão viva custa a captura.
        return True
    return abs(criado_em - info.criado_em_do_processo) <= (
        TOLERANCIA_DO_HORARIO_DO_PROCESSO
    )


def _remover(caminho: Path) -> None:
    """Remove o arquivo tolerando a janela de `PermissionError` do Windows."""
    for tentativa in range(TENTATIVAS_DE_REMOCAO):
        try:
            caminho.unlink(missing_ok=True)
            return
        except PermissionError:
            if tentativa == TENTATIVAS_DE_REMOCAO - 1:
                raise
            time.sleep(ESPERA_ENTRE_TENTATIVAS)


def ler_trava(data_dir: str | Path) -> InfoDaTrava | None:
    """A sessão em curso, ou `None` se não há trava ou se ela é órfã.

    Só lê: apagar a trava órfã é de quem vai adquirir uma nova (AC-013.2).
    """
    try:
        bruto = _caminho(data_dir).read_bytes()
    except OSError:
        return None
    info = _interpretar(bruto)
    if info is None or not _esta_viva(info):
        return None
    return info


def _publicar(caminho: Path, conteudo: bytes) -> None:
    """Cria a trava de forma exclusiva, já com o conteúdo completo.

    Levanta `FileExistsError` se ela existe.
    """
    temporario = caminho.with_name(f"{caminho.name}.{os.getpid()}.tmp")
    temporario.write_bytes(conteudo)
    try:
        os.link(temporario, caminho)
    finally:
        temporario.unlink(missing_ok=True)


@contextmanager
def adquirir_trava(
    data_dir: str | Path,
    *,
    comando: str,
    id_camera: str,
    nome_camera: str | None,
    agora: Callable[[], datetime],
) -> Iterator[InfoDaTrava]:
    """Pega a trava de sessão única e a solta na saída do bloco.

    Trava em poder de processo vivo → `OutraSessaoEmAndamentoError`, sem tocar no
    arquivo (AC-013.1). Trava órfã → apagada, e uma nova tentativa (AC-013.2);
    se outro processo ganhar essa corrida, a recusa é a mesma do caso vivo.
    """
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    caminho = _caminho(data_dir)

    info = InfoDaTrava(
        pid=os.getpid(),
        criado_em_do_processo=psutil.Process().create_time(),
        comando=comando,
        id_camera=id_camera,
        nome_camera=nome_camera,
        iniciada_em=agora().astimezone(timezone.utc),
    )
    conteudo = _serializar(info)

    for tentativa in (1, 2):
        try:
            _publicar(caminho, conteudo)
            break
        except FileExistsError:
            try:
                bruto = caminho.read_bytes()
            except FileNotFoundError:
                continue  # Liberada entre o `link` e a leitura.
            dono = _interpretar(bruto)
            if dono is not None and _esta_viva(dono):
                raise OutraSessaoEmAndamentoError(dono) from None
            if tentativa == 2:
                raise RuntimeError(
                    f"não foi possível adquirir a trava de sessão em {caminho}: "
                    f"outro processo a ocupou durante a limpeza da trava órfã"
                ) from None
            # Só apaga se ainda for a mesma trava órfã que foi lida.
            try:
                if caminho.read_bytes() == bruto:
                    _remover(caminho)
            except FileNotFoundError:
                pass
    else:
        raise RuntimeError(
            f"não foi possível adquirir a trava de sessão em {caminho}"
        )

    try:
        yield info
    finally:
        _soltar(caminho, info.pid)


def _soltar(caminho: Path, pid: int) -> None:
    """Remove a trava se ela ainda for deste processo; a de outro, nunca."""
    try:
        atual = _interpretar(caminho.read_bytes())
    except OSError:
        return
    if atual is not None and atual.pid == pid:
        _remover(caminho)

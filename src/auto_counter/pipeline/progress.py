"""Leitura do progresso da sessão, para a interface — T-13.

Comportamento em `.spec/features/interface-sessao/spec.md`: AC-012.1 a AC-012.6
(o que mostrar de uma sessão em andamento ou terminada) e AC-013.1 (a sessão em
curso, vista pela interface, impede outra).

`ler_progresso` é a **única** função que a interface chama para saber o que
mostrar, e é só leitura: não grava, não apaga nem cria arquivo, e não cria
banco. O banco é aberto em modo somente leitura e só se o arquivo existir. Nada
aqui abre o `manifest.json` (D-9): no Windows, um leitor com o manifest aberto
faz o `os.replace` da captura falhar.

Nada fica em memória entre duas chamadas: o progresso é reencontrado só a partir
do disco (AC-012.4), por isso reabrir a interface mostra a mesma sessão.
"""

import sqlite3
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from auto_counter.export.format import linha_de_aviso
from auto_counter.pipeline.lock import (
    InfoDaTrava,
    ler_trava,
    mensagem_de_sessao_em_andamento,
)
from auto_counter.pipeline.state import EstadoDaSessao, Fase, ler_estado
from auto_counter.storage.connection import caminho_do_banco
from auto_counter.storage.model import SessaoGravada
from auto_counter.storage.sessions import ler_sessao

MENSAGEM_PROCESSO_MORREU = "o processo da sessão terminou sem concluir"
"""D-9: estado não terminal sem trava viva é um processo que morreu."""


class Situacao(Enum):
    NENHUMA = "NENHUMA"
    EM_ANDAMENTO = "EM_ANDAMENTO"
    EM_ANDAMENTO_PELO_TERMINAL = "EM_ANDAMENTO_PELO_TERMINAL"
    TERMINADA = "TERMINADA"


@dataclass(frozen=True)
class Andamento:
    """O progresso de uma sessão que a interface sabe acompanhar."""

    nome_camera: str | None
    fase: Fase
    capturados: int
    perdidos: tuple[int, ...]
    pedidos: int
    processados: int
    a_processar: int
    pode_encerrar: bool


@dataclass(frozen=True)
class Resultado:
    """O desfecho da última sessão."""

    fase: Fase
    status: str | None
    aviso: str | None
    planilha: Path | None
    mensagem: str | None


@dataclass(frozen=True)
class Progresso:
    situacao: Situacao
    mensagem_de_recusa: str | None = None
    andamento: Andamento | None = None
    resultado: Resultado | None = None


def _andamento(estado: EstadoDaSessao) -> Andamento:
    return Andamento(
        nome_camera=estado.nome_camera,
        fase=estado.fase,
        capturados=len(estado.minutos_capturados),
        perdidos=estado.minutos_perdidos,
        pedidos=estado.duracao_pedida,
        processados=estado.minutos_processados,
        a_processar=estado.minutos_a_processar,
        pode_encerrar=not estado.fase.terminal,
    )


def _sessao_do_banco(data_dir: Path, id_sessao: str | None) -> SessaoGravada | None:
    """A linha da sessão, lida em modo somente leitura; `None` se não der."""
    caminho = caminho_do_banco(data_dir)
    if id_sessao is None or not caminho.is_file():
        return None
    try:
        conexao = sqlite3.connect(f"{caminho.as_uri()}?mode=ro", uri=True)
        try:
            conexao.row_factory = sqlite3.Row
            return ler_sessao(conexao, id_sessao)
        finally:
            conexao.close()
    except (sqlite3.Error, KeyError):
        return None


def _resultado(data_dir: Path, estado: EstadoDaSessao) -> Resultado:
    if not estado.fase.terminal:
        return Resultado(
            fase=Fase.FALHOU,
            status=estado.status,
            aviso=None,
            planilha=None,
            mensagem=MENSAGEM_PROCESSO_MORREU,
        )

    if estado.fase is not Fase.CONCLUIDA:
        return Resultado(
            fase=estado.fase,
            status=estado.status,
            aviso=None,
            planilha=None,
            mensagem=estado.mensagem,
        )

    sessao = _sessao_do_banco(data_dir, estado.id_sessao)
    status = estado.status
    aviso = None
    if sessao is not None and sessao.status is not None:
        status = sessao.status.value
        aviso = linha_de_aviso(sessao)

    planilha = Path(estado.planilha) if estado.planilha else None
    mensagem = estado.mensagem
    if planilha is not None and not planilha.is_file():
        mensagem = f"a planilha não está mais em {planilha}"
        planilha = None
    return Resultado(
        fase=Fase.CONCLUIDA,
        status=status,
        aviso=aviso,
        planilha=planilha,
        mensagem=mensagem,
    )


def _com_trava_viva(
    info: InfoDaTrava, estado: EstadoDaSessao | None
) -> Progresso | None:
    """O progresso de uma sessão em curso, ou `None` se o estado já terminou."""
    recusa = mensagem_de_sessao_em_andamento(info)
    do_run = (
        info.comando == "run" and estado is not None and estado.pid == info.pid
    )
    if not do_run:
        # D-15: iniciada pelo terminal (ou sem estado do mesmo processo). Não há
        # progresso a mostrar, só o fato de que há uma sessão.
        return Progresso(Situacao.EM_ANDAMENTO_PELO_TERMINAL, mensagem_de_recusa=recusa)
    if estado.fase.terminal:
        # O processo terminou de gravar o desfecho e ainda não soltou a trava.
        return None
    return Progresso(
        Situacao.EM_ANDAMENTO, mensagem_de_recusa=recusa, andamento=_andamento(estado)
    )


def ler_progresso(data_dir: str | Path) -> Progresso:
    """O que a interface deve mostrar agora, lido só do disco."""
    data_dir = Path(data_dir)
    estado = ler_estado(data_dir)

    info = ler_trava(data_dir)
    if info is not None:
        progresso = _com_trava_viva(info, estado)
        if progresso is not None:
            return progresso

    if estado is None:
        return Progresso(Situacao.NENHUMA)
    return Progresso(Situacao.TERMINADA, resultado=_resultado(data_dir, estado))

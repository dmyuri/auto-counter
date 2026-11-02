"""Leitura do progresso para a interface — T-13.

Critérios cobertos, de `.spec/features/interface-sessao/spec.md`: AC-012.1 a
AC-012.6 e AC-013.1, no lado de quem lê.

Trava e estado são montados à mão em `tmp_path`: "vivo" é o próprio processo do
teste e "morto" é um filho que já terminou. Nada aqui toca a rede.
"""

import os
import subprocess
import sys
from datetime import datetime, timezone

import psutil
import pytest

from auto_counter.capture.status import StatusDaSessao
from auto_counter.pipeline.lock import NOME_DA_TRAVA, adquirir_trava
from auto_counter.pipeline.progress import (
    MENSAGEM_PROCESSO_MORREU,
    Situacao,
    ler_progresso,
)
from auto_counter.pipeline.state import AnotadorDoEstado, Fase
from auto_counter.storage.connection import conectar
from tests.export_helpers import ID_SESSAO, gravar_sessao
from tests.test_pipeline_lock import grava_trava

INICIO = datetime(2026, 9, 7, 11, 0, tzinfo=timezone.utc)


def anotador(data_dir, *, pid=None, duracao_pedida=5) -> AnotadorDoEstado:
    return AnotadorDoEstado(
        data_dir,
        pid=os.getpid() if pid is None else pid,
        id_camera="000013",
        nome_camera="Praça Exemplo",
        duracao_pedida=duracao_pedida,
        iniciada_em=INICIO,
    )


def trava_do_run(data_dir):
    """Trava viva do `session run`, em poder deste processo."""
    return adquirir_trava(
        data_dir,
        comando="run",
        id_camera="000013",
        nome_camera="Praça Exemplo",
        agora=lambda: INICIO,
    )


def pid_morto() -> tuple[int, float]:
    filho = subprocess.Popen([sys.executable, "-c", "pass"])
    criado_em = psutil.Process(filho.pid).create_time()
    filho.wait()
    return filho.pid, criado_em


def instantaneo(pasta) -> dict:
    return {
        caminho.name: (caminho.stat().st_size, caminho.stat().st_mtime_ns)
        for caminho in pasta.rglob("*")
        if caminho.is_file()
    }


def test_AC_012_1_progresso_traz_capturados_do_total_e_perdidos(tmp_path):
    a = anotador(tmp_path)
    a.iniciar()
    a.minuto_da_captura(1, True)
    a.minuto_da_captura(2, False)
    a.minuto_da_captura(3, True)

    with trava_do_run(tmp_path):
        progresso = ler_progresso(tmp_path)

    assert progresso.situacao is Situacao.EM_ANDAMENTO
    assert progresso.andamento.capturados == 2
    assert progresso.andamento.perdidos == (2,)
    assert progresso.andamento.pedidos == 5
    assert progresso.andamento.nome_camera == "Praça Exemplo"


def test_AC_012_2_progresso_indica_a_fase_de_captura(tmp_path):
    a = anotador(tmp_path)
    a.iniciar()

    with trava_do_run(tmp_path):
        andamento = ler_progresso(tmp_path).andamento

    assert andamento.fase is Fase.CAPTURA
    assert andamento.pode_encerrar is True


def test_AC_012_2_progresso_indica_a_fase_de_processamento_e_quanto_falta(tmp_path):
    a = anotador(tmp_path)
    a.iniciar()
    a.minuto_da_captura(1, True)
    a.minuto_da_captura(2, True)
    a.processamento_iniciado(ID_SESSAO, 2)
    a.minuto_processado()

    with trava_do_run(tmp_path):
        andamento = ler_progresso(tmp_path).andamento

    assert andamento.fase is Fase.PROCESSAMENTO
    assert (andamento.processados, andamento.a_processar) == (1, 2)
    assert andamento.pode_encerrar is True


def test_AC_012_3_sessao_concluida_traz_o_status_do_banco_e_a_planilha(tmp_path):
    with conectar(tmp_path) as conexao:
        gravar_sessao(conexao, status=StatusDaSessao.COMPLETA)
    planilha = tmp_path / "000013_20260907_0800_2min.xlsx"
    planilha.write_bytes(b"xlsx")
    a = anotador(tmp_path)
    a.iniciar()
    a.terminar(
        Fase.CONCLUIDA,
        id_sessao=ID_SESSAO,
        status="mentira",
        planilha=str(planilha),
        mensagem="sessão concluída",
    )

    progresso = ler_progresso(tmp_path)

    assert progresso.situacao is Situacao.TERMINADA
    resultado = progresso.resultado
    assert resultado.fase is Fase.CONCLUIDA
    # O status vem do banco, e não do que o estado guardou.
    assert resultado.status == "COMPLETA"
    assert resultado.planilha == planilha
    assert resultado.aviso is None


def test_AC_012_3_sessao_degradada_traz_o_aviso(tmp_path):
    with conectar(tmp_path) as conexao:
        gravar_sessao(
            conexao,
            duracao_pedida=5,
            status=StatusDaSessao.DEGRADADA,
            minutos_perdidos=(2,),
        )
    planilha = tmp_path / "x.xlsx"
    planilha.write_bytes(b"xlsx")
    a = anotador(tmp_path)
    a.iniciar()
    a.terminar(
        Fase.CONCLUIDA, id_sessao=ID_SESSAO, status="DEGRADADA", planilha=str(planilha)
    )

    resultado = ler_progresso(tmp_path).resultado

    assert resultado.status == "DEGRADADA"
    assert "DEGRADADA" in resultado.aviso
    assert "1 de 5" in resultado.aviso


def test_planilha_que_sumiu_do_disco_vira_none_com_mensagem(tmp_path):
    with conectar(tmp_path) as conexao:
        gravar_sessao(conexao)
    a = anotador(tmp_path)
    a.iniciar()
    sumida = tmp_path / "sumiu.xlsx"
    a.terminar(
        Fase.CONCLUIDA, id_sessao=ID_SESSAO, status="COMPLETA", planilha=str(sumida)
    )

    resultado = ler_progresso(tmp_path).resultado

    assert resultado.planilha is None
    assert str(sumida) in resultado.mensagem


def test_AC_012_4_progresso_e_reencontrado_so_a_partir_do_disco(tmp_path):
    a = anotador(tmp_path)
    a.iniciar()
    a.minuto_da_captura(1, True)
    a.minuto_da_captura(2, False)

    with trava_do_run(tmp_path):
        primeiro = ler_progresso(tmp_path)
        # Leitor novo, sem nada em memória: só o que está em disco.
        segundo = ler_progresso(tmp_path)

    assert primeiro == segundo
    assert segundo.andamento.capturados == 1
    assert segundo.andamento.perdidos == (2,)


def test_AC_012_5_processamento_cancelado_nao_traz_planilha(tmp_path):
    a = anotador(tmp_path)
    a.iniciar()
    a.terminar(
        Fase.PROCESSAMENTO_CANCELADO,
        id_sessao=ID_SESSAO,
        status="COMPLETA",
        mensagem="reprocesse com `auto-counter session process x`",
    )

    resultado = ler_progresso(tmp_path).resultado

    assert resultado.fase is Fase.PROCESSAMENTO_CANCELADO
    assert resultado.planilha is None
    assert "session process" in resultado.mensagem


def test_AC_012_6_sessao_sem_planilha_traz_status_e_mensagem(tmp_path):
    a = anotador(tmp_path)
    a.iniciar()
    a.terminar(
        Fase.SEM_PLANILHA,
        id_sessao=ID_SESSAO,
        status="INVALIDA",
        mensagem="nenhum clipe da sessão pôde ser processado; não há planilha.",
    )

    resultado = ler_progresso(tmp_path).resultado

    assert resultado.fase is Fase.SEM_PLANILHA
    assert resultado.status == "INVALIDA"
    assert resultado.planilha is None
    assert "não há planilha" in resultado.mensagem


def test_AC_013_1_sessao_do_terminal_aparece_em_andamento_com_a_mensagem_de_recusa(
    tmp_path,
):
    with adquirir_trava(
        tmp_path,
        comando="capture",
        id_camera="000042",
        nome_camera="Outro local",
        agora=lambda: INICIO,
    ):
        progresso = ler_progresso(tmp_path)

    assert progresso.situacao is Situacao.EM_ANDAMENTO_PELO_TERMINAL
    assert progresso.andamento is None
    assert "Outro local" in progresso.mensagem_de_recusa
    assert "07/09/2026 08:00" in progresso.mensagem_de_recusa


def test_run_com_trava_viva_mas_estado_de_outro_processo_e_do_terminal(tmp_path):
    anotador(tmp_path, pid=os.getpid() + 1).iniciar()

    with trava_do_run(tmp_path):
        progresso = ler_progresso(tmp_path)

    assert progresso.situacao is Situacao.EM_ANDAMENTO_PELO_TERMINAL


def test_sessao_em_andamento_traz_a_mensagem_de_recusa(tmp_path):
    anotador(tmp_path).iniciar()

    with trava_do_run(tmp_path):
        progresso = ler_progresso(tmp_path)

    assert "Praça Exemplo" in progresso.mensagem_de_recusa


def test_estado_nao_terminal_sem_trava_viva_e_falha(tmp_path):
    pid, criado_em = pid_morto()
    a = anotador(tmp_path, pid=pid)
    a.iniciar()
    a.minuto_da_captura(1, True)
    grava_trava(tmp_path, pid=pid, criado_em=criado_em)

    progresso = ler_progresso(tmp_path)

    assert progresso.situacao is Situacao.TERMINADA
    assert progresso.resultado.fase is Fase.FALHOU
    assert progresso.resultado.mensagem == MENSAGEM_PROCESSO_MORREU
    assert progresso.resultado.planilha is None


def test_estado_terminal_com_a_trava_ainda_presa_ja_e_resultado(tmp_path):
    a = anotador(tmp_path)
    a.iniciar()
    a.terminar(Fase.SEM_PLANILHA, id_sessao=ID_SESSAO, status="INVALIDA")

    with trava_do_run(tmp_path):
        progresso = ler_progresso(tmp_path)

    assert progresso.situacao is Situacao.TERMINADA


def test_sem_nada_em_disco_a_situacao_e_nenhuma(tmp_path):
    assert ler_progresso(tmp_path).situacao is Situacao.NENHUMA
    assert ler_progresso(tmp_path / "nao_existe").situacao is Situacao.NENHUMA


@pytest.mark.parametrize("com_banco", [False, True])
def test_ler_progresso_nao_cria_banco_nem_arquivo(tmp_path, com_banco):
    if com_banco:
        with conectar(tmp_path) as conexao:
            gravar_sessao(conexao)
    planilha = tmp_path / "x.xlsx"
    planilha.write_bytes(b"xlsx")
    a = anotador(tmp_path)
    a.iniciar()
    a.terminar(Fase.CONCLUIDA, id_sessao=ID_SESSAO, status="COMPLETA", planilha=str(planilha))
    (tmp_path / NOME_DA_TRAVA).unlink(missing_ok=True)
    antes = instantaneo(tmp_path)

    ler_progresso(tmp_path)

    assert instantaneo(tmp_path) == antes


def test_ler_progresso_nao_abre_o_manifest(tmp_path, monkeypatch):
    def proibido(*args, **kwargs):
        raise AssertionError("ler_progresso abriu o manifest")

    monkeypatch.setattr("auto_counter.capture.manifest.ler", proibido)
    anotador(tmp_path).iniciar()

    with trava_do_run(tmp_path):
        assert ler_progresso(tmp_path).situacao is Situacao.EM_ANDAMENTO

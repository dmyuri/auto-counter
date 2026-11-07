"""Leitura do progresso para a interface — T-13.

Critérios cobertos, de `.spec/features/interface-sessao/spec.md`: AC-012.1 a
AC-012.6 e AC-013.1, no lado de quem lê.

Trava e estado são montados à mão em `tmp_path`: "vivo" é o próprio processo do
teste e "morto" é um filho que já terminou. Nada aqui toca a rede.
"""

import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import psutil
import pytest

from auto_counter.capture.status import StatusDaSessao
from auto_counter.counting.config import Categoria
from auto_counter.pipeline.lock import NOME_DA_TRAVA, adquirir_trava
from auto_counter.pipeline.progress import (
    MENSAGEM_PROCESSO_MORREU,
    Quantidades,
    Situacao,
    formatar_tempo,
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


def anotador_com_relogio(data_dir, *, fim=None) -> AnotadorDoEstado:
    return AnotadorDoEstado(
        data_dir,
        pid=os.getpid(),
        id_camera="000013",
        nome_camera="Praça Exemplo",
        duracao_pedida=5,
        iniciada_em=INICIO,
        **({} if fim is None else {"agora": lambda: fim}),
    )


def em_processamento(data_dir, *, fim=None) -> AnotadorDoEstado:
    a = anotador_com_relogio(data_dir, fim=fim)
    a.iniciar()
    a.minuto_da_captura(1, True)
    a.processamento_iniciado(ID_SESSAO, 1)
    return a


def test_AC_016_1_inicio_do_processamento_mostra_cinco_quantidades_em_zero(tmp_path):
    em_processamento(tmp_path)

    with trava_do_run(tmp_path):
        quantidades = ler_progresso(tmp_path).andamento.quantidades

    assert quantidades == Quantidades(carro=0, onibus=0, caminhao=0, moto=0)
    assert quantidades.total == 0


def test_AC_016_2_total_e_a_soma_das_quatro_categorias(tmp_path):
    a = em_processamento(tmp_path)
    for categoria in (Categoria.CARRO, Categoria.CARRO, Categoria.MOTO, Categoria.ONIBUS):
        a.evento_aceito(1, categoria)

    with trava_do_run(tmp_path):
        quantidades = ler_progresso(tmp_path).andamento.quantidades

    assert (quantidades.carro, quantidades.onibus) == (2, 1)
    assert (quantidades.caminhao, quantidades.moto) == (0, 1)
    assert quantidades.total == 4


def test_AC_016_5_captura_nao_tem_quantidades(tmp_path):
    a = anotador_com_relogio(tmp_path)
    a.iniciar()
    a.minuto_da_captura(1, True)

    with trava_do_run(tmp_path):
        andamento = ler_progresso(tmp_path).andamento

    assert andamento.fase is Fase.CAPTURA
    assert andamento.quantidades is None


def test_AC_016_7_reabrir_le_as_mesmas_quantidades(tmp_path):
    a = em_processamento(tmp_path)
    a.evento_aceito(1, Categoria.CAMINHAO)

    with trava_do_run(tmp_path):
        primeiro = ler_progresso(tmp_path, agora=INICIO).andamento.quantidades
        segundo = ler_progresso(tmp_path, agora=INICIO).andamento.quantidades

    assert primeiro == segundo
    assert segundo.caminhao == 1


def test_AC_017_1_tempo_decorrido_e_agora_menos_inicio_truncado(tmp_path):
    a = anotador_com_relogio(tmp_path)
    a.iniciar()

    with trava_do_run(tmp_path):
        andamento = ler_progresso(
            tmp_path, agora=INICIO + timedelta(seconds=75, milliseconds=900)
        ).andamento

    assert andamento.tempo_decorrido == 75
    assert formatar_tempo(andamento.tempo_decorrido) == "01:15"


def test_AC_017_1_relogio_que_recuou_nao_da_tempo_negativo(tmp_path):
    anotador_com_relogio(tmp_path).iniciar()

    with trava_do_run(tmp_path):
        andamento = ler_progresso(tmp_path, agora=INICIO - timedelta(seconds=5)).andamento

    assert andamento.tempo_decorrido == 0


def test_AC_017_2_tempo_nao_zera_na_passagem_para_o_processamento(tmp_path):
    a = anotador_com_relogio(tmp_path)
    a.iniciar()
    a.minuto_da_captura(1, True)
    agora = INICIO + timedelta(seconds=90)

    with trava_do_run(tmp_path):
        na_captura = ler_progresso(tmp_path, agora=agora).andamento
        a.processamento_iniciado(ID_SESSAO, 1)
        no_processamento = ler_progresso(tmp_path, agora=agora).andamento

    assert na_captura.fase is Fase.CAPTURA
    assert no_processamento.fase is Fase.PROCESSAMENTO
    assert na_captura.tempo_decorrido == no_processamento.tempo_decorrido == 90


def test_AC_017_3_duas_consultas_diferem_do_intervalo_entre_elas(tmp_path):
    em_processamento(tmp_path)

    with trava_do_run(tmp_path):
        t1 = ler_progresso(tmp_path, agora=INICIO + timedelta(seconds=10)).andamento
        t2 = ler_progresso(
            tmp_path, agora=INICIO + timedelta(seconds=10, milliseconds=2500)
        ).andamento

    assert abs((t2.tempo_decorrido - t1.tempo_decorrido) - 2.5) <= 1


def test_AC_017_4_tempo_conta_do_inicio_e_nao_da_reabertura(tmp_path):
    em_processamento(tmp_path)
    agora = INICIO + timedelta(minutes=7, seconds=3)

    with trava_do_run(tmp_path):
        antes_de_fechar = ler_progresso(tmp_path, agora=agora).andamento
        # "Reabrir": leitor novo, sem nada em memória.
        reaberto = ler_progresso(tmp_path, agora=agora).andamento

    assert reaberto.tempo_decorrido == antes_de_fechar.tempo_decorrido == 423


def test_formatar_tempo_minutos_passam_de_59():
    assert formatar_tempo(0) == "00:00"
    assert formatar_tempo(59) == "00:59"
    assert formatar_tempo(60) == "01:00"
    assert formatar_tempo(4503) == "75:03"


def test_AC_018_1_concluida_traz_quantidades_finais_e_tempo_total(tmp_path):
    fim = INICIO + timedelta(minutes=17, seconds=5, milliseconds=800)
    a = em_processamento(tmp_path, fim=fim)
    a.evento_aceito(1, Categoria.CARRO)
    a.evento_aceito(1, Categoria.CARRO)
    a.evento_aceito(1, Categoria.ONIBUS)
    a.minuto_processado()
    a.terminar(Fase.CONCLUIDA, id_sessao=ID_SESSAO, status="COMPLETA")

    resultado = ler_progresso(tmp_path).resultado

    assert resultado.quantidades == Quantidades(carro=2, onibus=1, caminhao=0, moto=0)
    assert resultado.quantidades.total == 3
    assert resultado.tempo_total == 17 * 60 + 5


def test_AC_018_2_tempo_total_nao_avanca_entre_consultas(tmp_path):
    fim = INICIO + timedelta(minutes=3)
    a = em_processamento(tmp_path, fim=fim)
    a.terminar(Fase.CONCLUIDA, id_sessao=ID_SESSAO, status="COMPLETA")

    primeira = ler_progresso(tmp_path, agora=fim + timedelta(seconds=1)).resultado
    segunda = ler_progresso(tmp_path, agora=fim + timedelta(hours=5)).resultado

    assert primeira.tempo_total == segunda.tempo_total == 180


@pytest.mark.parametrize(
    "fase",
    [Fase.PROCESSAMENTO_CANCELADO, Fase.SEM_PLANILHA, Fase.FALHOU],
)
def test_AC_018_3_cancelada_sem_planilha_e_falhou_trazem_tempo_e_nenhuma_quantidade(
    tmp_path, fase
):
    fim = INICIO + timedelta(minutes=2, seconds=30)
    a = em_processamento(tmp_path, fim=fim)
    a.evento_aceito(1, Categoria.CARRO)
    a.terminar(fase, id_sessao=ID_SESSAO, status="COMPLETA", mensagem="x")

    resultado = ler_progresso(tmp_path).resultado

    assert resultado.fase is fase
    assert resultado.tempo_total == 150
    assert resultado.quantidades is None


def test_AC_018_4_processo_morto_nao_traz_quantidades_nem_tempo(tmp_path):
    pid, criado_em = pid_morto()
    a = AnotadorDoEstado(
        tmp_path,
        pid=pid,
        id_camera="000013",
        nome_camera="Praça Exemplo",
        duracao_pedida=5,
        iniciada_em=INICIO,
    )
    a.iniciar()
    a.minuto_da_captura(1, True)
    a.processamento_iniciado(ID_SESSAO, 1)
    a.evento_aceito(1, Categoria.CARRO)
    grava_trava(tmp_path, pid=pid, criado_em=criado_em)

    resultado = ler_progresso(tmp_path).resultado

    assert resultado.mensagem == MENSAGEM_PROCESSO_MORREU
    assert resultado.quantidades is None
    assert resultado.tempo_total is None

"""Leitura do progresso para a interface — T-13.

Critérios cobertos, de `.spec/features/interface-sessao/spec.md`: AC-012.1 a
AC-012.6 e AC-013.1, no lado de quem lê.

Trava e estado são montados à mão em `tmp_path`: "vivo" é o próprio processo do
teste e "morto" é um filho que já terminou. Nada aqui toca a rede.
"""

import json
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
    formatar_taxa,
    formatar_tempo,
    ler_progresso,
)
from auto_counter.pipeline.state import AnotadorDoEstado, Fase
from auto_counter.storage.connection import caminho_do_banco, conectar
from tests.export_helpers import ID_SESSAO, evento, gravar_sessao
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


# --- layout-interface: percentual, participação, taxa e tempo estimado (T-06) ---


class Relogio:
    """Relógio do anotador, movido à mão pelo teste."""

    def __init__(self, instante: datetime = INICIO) -> None:
        self.instante = instante

    def __call__(self) -> datetime:
        return self.instante


def sessao_em_processamento(
    data_dir, *, a_processar, minutos_com_eventos=(), relogio=None
) -> AnotadorDoEstado:
    """Sessão no processamento com `a_processar` minutos.

    Cada item de `minutos_com_eventos` é um minuto já concluído, com essa
    quantidade de carros.
    """
    a = AnotadorDoEstado(
        data_dir,
        pid=os.getpid(),
        id_camera="000013",
        nome_camera="Praça Exemplo",
        duracao_pedida=a_processar,
        iniciada_em=INICIO,
        agora=relogio or Relogio(),
    )
    a.iniciar()
    for minuto in range(1, a_processar + 1):
        a.minuto_da_captura(minuto, True)
    a.processamento_iniciado(ID_SESSAO, a_processar)
    for minuto, quantos in enumerate(minutos_com_eventos, start=1):
        a.minuto_iniciado()
        for _ in range(quantos):
            a.evento_aceito(minuto, Categoria.CARRO)
        a.minuto_processado()
    return a


def com_eventos(a: AnotadorDoEstado, quantidades: dict[Categoria, int]) -> None:
    for categoria, quantos in quantidades.items():
        for _ in range(quantos):
            a.evento_aceito(1, categoria)


def andamento_de(data_dir, *, agora=None):
    with trava_do_run(data_dir):
        return ler_progresso(data_dir, agora=agora).andamento


def participacoes_de(data_dir) -> tuple[int, int, int, int]:
    p = andamento_de(data_dir).participacoes
    return (p.carro, p.onibus, p.caminhao, p.moto)


def test_AC_022_2_participacao_arredonda_ao_inteiro_com_meio_para_cima(tmp_path):
    a = sessao_em_processamento(tmp_path, a_processar=2)
    # 1/8 = 12,5 -> 13 e 3/8 = 37,5 -> 38
    com_eventos(
        a,
        {
            Categoria.CARRO: 1,
            Categoria.ONIBUS: 3,
            Categoria.CAMINHAO: 1,
            Categoria.MOTO: 3,
        },
    )

    assert participacoes_de(tmp_path) == (13, 38, 13, 38)


def test_AC_022_2_participacao_de_um_terco_e_33(tmp_path):
    a = sessao_em_processamento(tmp_path, a_processar=2)
    com_eventos(
        a, {Categoria.CARRO: 1, Categoria.ONIBUS: 1, Categoria.CAMINHAO: 1}
    )

    assert participacoes_de(tmp_path) == (33, 33, 33, 0)


def test_AC_022_2_total_zero_da_zero_por_cento_em_todas(tmp_path):
    sessao_em_processamento(tmp_path, a_processar=2)

    assert participacoes_de(tmp_path) == (0, 0, 0, 0)


def test_AC_022_7_captura_nao_tem_participacoes(tmp_path):
    a = anotador(tmp_path)
    a.iniciar()
    a.minuto_da_captura(1, True)

    assert andamento_de(tmp_path).participacoes is None


@pytest.mark.parametrize(
    ("por_minuto", "esperado"),
    [
        ((1, 0, 0, 0), "0,3 veíc/min"),  # 1/4 = 0,25 -> 0,3
        ((12, 12, 13), "12,3 veíc/min"),  # 37/3
        ((0, 0), "0,0 veíc/min"),
    ],
)
def test_AC_022_3_taxa_e_v_sobre_k_com_virgula_e_meio_para_cima(
    tmp_path, por_minuto, esperado
):
    sessao_em_processamento(
        tmp_path, a_processar=len(por_minuto) + 1, minutos_com_eventos=por_minuto
    )

    assert andamento_de(tmp_path).taxa == esperado


def test_AC_022_3_sem_minuto_concluido_com_dado_mostra_traco(tmp_path):
    sessao_em_processamento(tmp_path, a_processar=2)

    assert andamento_de(tmp_path).taxa == "— veíc/min"


def test_AC_022_3_captura_mostra_traco(tmp_path):
    a = anotador(tmp_path)
    a.iniciar()
    a.minuto_da_captura(1, True)

    assert andamento_de(tmp_path).taxa == "— veíc/min"


def test_AC_022_3_minuto_em_analise_nao_entra_na_taxa(tmp_path):
    a = sessao_em_processamento(tmp_path, a_processar=3, minutos_com_eventos=(4,))
    antes = andamento_de(tmp_path).taxa

    a.minuto_iniciado()
    com_eventos(a, {Categoria.CARRO: 9})

    assert antes == "4,0 veíc/min"
    assert andamento_de(tmp_path).taxa == antes


def test_formatar_taxa_regras_de_r1():
    assert formatar_taxa(1, 4) == "0,3 veíc/min"
    assert formatar_taxa(37, 3) == "12,3 veíc/min"
    assert formatar_taxa(0, 2) == "0,0 veíc/min"
    assert formatar_taxa(5, 0) == "— veíc/min"
    assert formatar_taxa(0, 0) == "— veíc/min"


def test_AC_022_4_percentual_da_captura_conta_capturados_e_perdidos(tmp_path):
    a = anotador(tmp_path, duracao_pedida=7)
    a.iniciar()
    a.minuto_da_captura(1, True)
    a.minuto_da_captura(2, False)
    a.minuto_da_captura(3, True)

    assert andamento_de(tmp_path).percentual == 42  # 3/7 = 42,8


@pytest.mark.parametrize(("processados", "esperado"), [(1, 33), (2, 66)])
def test_AC_022_4_percentual_do_processamento_e_piso(tmp_path, processados, esperado):
    sessao_em_processamento(
        tmp_path, a_processar=3, minutos_com_eventos=(0,) * processados
    )

    assert andamento_de(tmp_path).percentual == esperado


def test_AC_022_1_o_andamento_traz_o_id_da_camera(tmp_path):
    a = anotador(tmp_path)
    a.iniciar()

    assert andamento_de(tmp_path).id_camera == "000013"


def test_AC_022_5_tempo_estimado_da_captura(tmp_path):
    a = anotador(tmp_path, duracao_pedida=5)
    a.iniciar()
    a.minuto_da_captura(1, True)
    a.minuto_da_captura(2, False)

    andamento = andamento_de(tmp_path, agora=INICIO + timedelta(seconds=130.7))

    # max(0, 300 - 130,7) + 4 * 80 = 489,3
    assert andamento.tempo_estimado == 489


def test_AC_022_5_captura_passada_da_duracao_nao_fica_negativa(tmp_path):
    a = anotador(tmp_path, duracao_pedida=5)
    a.iniciar()
    a.minuto_da_captura(1, False)

    andamento = andamento_de(tmp_path, agora=INICIO + timedelta(seconds=400))

    assert andamento.tempo_estimado == 4 * 80


def processando_ha(tmp_path, *, a_processar, processados, segundos):
    """Sessão no processamento com `processados` minutos prontos e o seguinte em
    análise há `segundos` segundos. Devolve o `agora` da leitura."""
    relogio = Relogio(INICIO + timedelta(minutes=10))
    a = sessao_em_processamento(
        tmp_path,
        a_processar=a_processar,
        minutos_com_eventos=(0,) * processados,
        relogio=relogio,
    )
    a.minuto_iniciado()
    return relogio.instante + timedelta(seconds=segundos)


def test_AC_022_6_tempo_estimado_do_processamento_desconta_o_minuto_em_analise(
    tmp_path,
):
    agora = processando_ha(tmp_path, a_processar=3, processados=1, segundos=30.5)

    # max(80, 160 - 30,5) = 129,5
    assert andamento_de(tmp_path, agora=agora).tempo_estimado == 129


def test_AC_022_6_minuto_que_passa_do_orcamento_para_no_estimado_seguinte(tmp_path):
    agora = processando_ha(tmp_path, a_processar=3, processados=1, segundos=200)

    assert andamento_de(tmp_path, agora=agora).tempo_estimado == 80


def test_AC_022_6_todos_os_minutos_analisados_da_zero(tmp_path):
    agora = processando_ha(tmp_path, a_processar=2, processados=2, segundos=5)

    assert andamento_de(tmp_path, agora=agora).tempo_estimado == 0


def test_AC_022_6_estado_sem_tm_da_tempo_estimado_none(tmp_path):
    sessao_em_processamento(tmp_path, a_processar=3)
    caminho = tmp_path / "sessao_atual.json"
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    dados["minuto_em_analise_desde"] = None
    caminho.write_text(json.dumps(dados), encoding="utf-8")

    assert andamento_de(tmp_path).tempo_estimado is None


# --- layout-interface: registros, encerramento pelo usuário e chave (T-07) ---

OUTRA_SESSAO = "000013-20260907T120000Z"


def concluida(data_dir, *, iniciada_em=INICIO, id_sessao=ID_SESSAO) -> None:
    """Estado terminal CONCLUIDA, com a planilha em disco, do `pid` deste teste."""
    planilha = data_dir / "x.xlsx"
    planilha.write_bytes(b"xlsx")
    a = AnotadorDoEstado(
        data_dir,
        pid=os.getpid(),
        id_camera="000013",
        nome_camera="Praça Exemplo",
        duracao_pedida=2,
        iniciada_em=iniciada_em,
    )
    a.iniciar()
    a.terminar(
        Fase.CONCLUIDA, id_sessao=id_sessao, status="COMPLETA", planilha=str(planilha)
    )


def test_AC_023_2_concluida_traz_o_numero_de_eventos_gravados(tmp_path):
    with conectar(tmp_path) as conexao:
        gravar_sessao(
            conexao,
            eventos=tuple(
                evento(minuto=1, id_de_rastreio=f"a{i}") for i in range(3)
            ),
        )
        gravar_sessao(
            conexao,
            id_sessao=OUTRA_SESSAO,
            eventos=tuple(
                evento(minuto=1, id_de_rastreio=f"b{i}") for i in range(2)
            ),
        )
    concluida(tmp_path)

    resultado = ler_progresso(tmp_path).resultado

    assert resultado.registros == 3


def test_AC_023_2_concluida_encerrada_pelo_usuario_traz_a_marca(tmp_path):
    with conectar(tmp_path) as conexao:
        gravar_sessao(conexao, encerrada_pelo_usuario=True)
    concluida(tmp_path)

    assert ler_progresso(tmp_path).resultado.encerrada_pelo_usuario is True


def test_AC_023_2_concluida_sem_encerramento_pelo_usuario_nao_traz_a_marca(tmp_path):
    with conectar(tmp_path) as conexao:
        gravar_sessao(conexao)
    concluida(tmp_path)

    assert ler_progresso(tmp_path).resultado.encerrada_pelo_usuario is False


def test_AC_023_2_banco_ilegivel_da_registros_none_sem_falhar(tmp_path):
    caminho_do_banco(tmp_path).write_bytes(b"isto nao e um banco sqlite" * 50)
    concluida(tmp_path)

    resultado = ler_progresso(tmp_path).resultado

    assert resultado.registros is None
    assert resultado.encerrada_pelo_usuario is False


def test_AC_023_6_chave_do_resultado_muda_entre_sessoes(tmp_path):
    concluida(tmp_path)
    primeira = ler_progresso(tmp_path).resultado.chave
    assert ler_progresso(tmp_path).resultado.chave == primeira

    concluida(tmp_path, iniciada_em=INICIO + timedelta(hours=1))
    segunda = ler_progresso(tmp_path).resultado.chave

    assert segunda != primeira


def test_AC_023_6_todo_resultado_tem_chave_inclusive_o_de_processo_morto(tmp_path):
    pid, criado_em = pid_morto()
    a = anotador(tmp_path, pid=pid)
    a.iniciar()
    a.minuto_da_captura(1, True)
    # Sem trava viva: estado não terminal vira "falhou".

    resultado = ler_progresso(tmp_path).resultado

    assert resultado.fase is Fase.FALHOU
    assert resultado.chave == f"{pid}:{INICIO.isoformat()}"


def test_AC_023_7_resultado_e_relido_do_disco_com_a_mesma_chave(tmp_path):
    with conectar(tmp_path) as conexao:
        gravar_sessao(
            conexao, eventos=(evento(minuto=1, id_de_rastreio="a"),)
        )
    concluida(tmp_path)

    # Duas leituras sem nada em comum além do disco: duas abas.
    primeira = ler_progresso(tmp_path)
    segunda = ler_progresso(tmp_path)

    assert primeira == segunda
    assert primeira.resultado.chave == segunda.resultado.chave
    assert primeira.resultado.registros == 1


def test_ler_progresso_continua_so_leitura(tmp_path):
    concluida(tmp_path)
    antes = instantaneo(tmp_path)

    resultado = ler_progresso(tmp_path).resultado

    assert not caminho_do_banco(tmp_path).exists()
    assert resultado.registros is None
    assert instantaneo(tmp_path) == antes

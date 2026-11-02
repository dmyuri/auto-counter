"""Estado da sessão em `sessao_atual.json` — T-08.

Critérios cobertos, de `.spec/features/interface-sessao/spec.md`:

- AC-012.1 — minutos capturados e perdidos até ali;
- AC-012.2 — a fase e o progresso dentro dela;
- AC-012.4 — o progresso continua em disco, para ser reencontrado ao reabrir a
  interface.

Nada aqui toca a rede nem grava fora de `tmp_path`.
"""

import os
from datetime import datetime, timezone

import pytest

from auto_counter.pipeline import state
from auto_counter.pipeline.state import (
    NOME_DO_ESTADO,
    AnotadorDoEstado,
    Fase,
    ler_estado,
)

INICIO = datetime(2026, 9, 7, 11, 0, tzinfo=timezone.utc)


def anotador(data_dir, **extra) -> AnotadorDoEstado:
    return AnotadorDoEstado(
        data_dir,
        pid=extra.pop("pid", 4242),
        id_camera="000013",
        nome_camera="Praça Renascença",
        duracao_pedida=extra.pop("duracao_pedida", 5),
        iniciada_em=extra.pop("iniciada_em", INICIO),
    )


def test_AC_012_1_minutos_capturados_e_perdidos_sao_acumulados_no_estado(tmp_path):
    a = anotador(tmp_path)
    a.iniciar()

    a.minuto_da_captura(1, True)
    a.minuto_da_captura(2, False)
    a.minuto_da_captura(3, True)

    estado = ler_estado(tmp_path)
    assert estado.fase is Fase.CAPTURA
    assert estado.minutos_capturados == (1, 3)
    assert estado.minutos_perdidos == (2,)
    assert estado.duracao_pedida == 5
    assert estado.nome_camera == "Praça Renascença"
    assert estado.iniciada_em == INICIO
    assert estado.pid == 4242


def test_AC_012_2_o_estado_registra_a_fase_e_o_progresso_do_processamento(tmp_path):
    a = anotador(tmp_path)
    a.iniciar()
    a.minuto_da_captura(1, True)
    a.minuto_da_captura(2, True)

    a.processamento_iniciado("000013-20260907T110000Z", 2)
    antes = ler_estado(tmp_path)
    a.minuto_processado()
    depois = ler_estado(tmp_path)

    assert antes.fase is Fase.PROCESSAMENTO
    assert antes.id_sessao == "000013-20260907T110000Z"
    assert (antes.minutos_processados, antes.minutos_a_processar) == (0, 2)
    assert depois.minutos_processados == 1
    # A captura já terminada continua visível durante o processamento.
    assert depois.minutos_capturados == (1, 2)


def test_AC_012_4_o_estado_continua_em_disco_depois_do_fim_da_sessao(tmp_path):
    a = anotador(tmp_path)
    a.iniciar()
    a.minuto_da_captura(1, True)
    a.processamento_iniciado("000013-20260907T110000Z", 1)
    a.minuto_processado()

    a.terminar(
        Fase.CONCLUIDA,
        status="COMPLETA",
        planilha="data/000013_20260907_0800_1min.xlsx",
        mensagem="pronto",
    )

    # Leitor novo, sem nada em memória: só o que está em disco.
    estado = ler_estado(tmp_path)
    assert estado.fase is Fase.CONCLUIDA
    assert estado.fase.terminal
    assert estado.status == "COMPLETA"
    assert estado.planilha == "data/000013_20260907_0800_1min.xlsx"
    assert estado.mensagem == "pronto"
    assert estado.id_sessao == "000013-20260907T110000Z"
    assert (tmp_path / NOME_DO_ESTADO).is_file()


def test_fases_terminais_e_nao_terminais():
    assert not Fase.CAPTURA.terminal
    assert not Fase.PROCESSAMENTO.terminal
    for fase in (
        Fase.CONCLUIDA,
        Fase.SEM_PLANILHA,
        Fase.PROCESSAMENTO_CANCELADO,
        Fase.FALHOU,
    ):
        assert fase.terminal


def test_terminar_com_fase_nao_terminal_e_erro_de_programacao(tmp_path):
    with pytest.raises(ValueError):
        anotador(tmp_path).terminar(Fase.CAPTURA)


def test_falha_de_gravacao_nao_levanta(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "ESPERA_ENTRE_TENTATIVAS", 0)

    def negado(origem, destino):
        raise PermissionError("arquivo em uso")

    monkeypatch.setattr(state.os, "replace", negado)
    a = anotador(tmp_path)

    a.iniciar()
    a.minuto_da_captura(1, True)
    a.processamento_iniciado("x", 1)
    a.minuto_processado()
    a.terminar(Fase.FALHOU, mensagem="falha")

    assert not (tmp_path / NOME_DO_ESTADO).exists()
    assert list(tmp_path.glob("*.tmp")) == []


def test_falha_de_gravacao_ao_terminar_avisa_em_stderr(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(state, "ESPERA_ENTRE_TENTATIVAS", 0)
    monkeypatch.setattr(
        state.os, "replace", lambda o, d: (_ for _ in ()).throw(PermissionError())
    )

    anotador(tmp_path).terminar(Fase.CONCLUIDA, status="COMPLETA")

    assert "aviso" in capsys.readouterr().err


def test_gravacao_se_recupera_de_falha_transitoria(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "ESPERA_ENTRE_TENTATIVAS", 0)
    original = os.replace
    falhas = {"restantes": 2}

    def instavel(origem, destino):
        if falhas["restantes"] > 0:
            falhas["restantes"] -= 1
            raise PermissionError("arquivo em uso")
        original(origem, destino)

    monkeypatch.setattr(state.os, "replace", instavel)

    anotador(tmp_path).iniciar()

    assert ler_estado(tmp_path).fase is Fase.CAPTURA


@pytest.mark.parametrize("conteudo", [None, "", "{não é json", '{"pid": 1}', "[]"])
def test_ler_estado_ilegivel_devolve_none(tmp_path, conteudo):
    if conteudo is not None:
        (tmp_path / NOME_DO_ESTADO).write_text(conteudo, encoding="utf-8")

    assert ler_estado(tmp_path) is None


def test_instante_sem_fuso_e_recusado(tmp_path):
    with pytest.raises(ValueError, match="fuso"):
        anotador(tmp_path, iniciada_em=datetime(2026, 9, 7, 11, 0))


def test_o_instante_e_gravado_em_utc_com_fuso_explicito(tmp_path):
    from datetime import timedelta

    brasilia = timezone(timedelta(hours=-3))
    anotador(tmp_path, iniciada_em=datetime(2026, 9, 7, 8, 0, tzinfo=brasilia)).iniciar()

    bruto = (tmp_path / NOME_DO_ESTADO).read_text(encoding="utf-8")
    assert "2026-09-07T11:00:00+00:00" in bruto
    assert ler_estado(tmp_path).iniciada_em == INICIO

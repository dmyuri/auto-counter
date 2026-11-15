"""Estado da sessão em `sessao_atual.json` — T-08.

Critérios cobertos, de `.spec/features/interface-sessao/spec.md`:

- AC-012.1 — minutos capturados e perdidos até ali;
- AC-012.2 — a fase e o progresso dentro dela;
- AC-012.4 — o progresso continua em disco, para ser reencontrado ao reabrir a
  interface;
- AC-012.7 — a sessão cancelada na captura é um desfecho terminal próprio.

Nada aqui toca a rede nem grava fora de `tmp_path`.
"""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from auto_counter.counting.config import Categoria
from auto_counter.pipeline import state
from auto_counter.pipeline.state import (
    NOME_DO_ESTADO,
    AnotadorDoEstado,
    ClipeMantido,
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


def test_AC_012_7_sessao_cancelada_e_fase_terminal_distinta_do_processamento_cancelado(
    tmp_path,
):
    assert Fase.SESSAO_CANCELADA.terminal
    assert Fase.SESSAO_CANCELADA is not Fase.PROCESSAMENTO_CANCELADO

    a = anotador(tmp_path)
    a.iniciar()
    a.terminar(Fase.SESSAO_CANCELADA, mensagem="Sessão cancelada pelo usuário")

    estado = ler_estado(tmp_path)
    assert estado.fase is Fase.SESSAO_CANCELADA
    assert estado.terminada_em is not None
    assert estado.planilha is None
    assert estado.quantidades is None


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


ZERADAS = {"CARRO": 0, "ONIBUS": 0, "CAMINHAO": 0, "MOTO": 0}
"""As chaves são o `.value` de `Categoria`, sem tradução (D-4)."""


def anotador_em_processamento(data_dir, **extra) -> AnotadorDoEstado:
    a = anotador_com_relogio(data_dir, **extra)
    a.iniciar()
    a.minuto_da_captura(1, True)
    a.minuto_da_captura(2, True)
    a.processamento_iniciado("000013-20260907T110000Z", 2)
    return a


def anotador_com_relogio(data_dir, *, agora=None, **extra) -> AnotadorDoEstado:
    return AnotadorDoEstado(
        data_dir,
        pid=4242,
        id_camera="000013",
        nome_camera="Praça Renascença",
        duracao_pedida=5,
        iniciada_em=INICIO,
        **({} if agora is None else {"agora": agora}),
    )


def test_AC_016_1_processamento_iniciado_grava_as_quatro_categorias_em_zero(tmp_path):
    a = anotador_com_relogio(tmp_path)
    a.iniciar()
    a.minuto_da_captura(1, True)

    a.processamento_iniciado("000013-20260907T110000Z", 1)

    assert ler_estado(tmp_path).quantidades == ZERADAS


def test_AC_016_1_captura_nao_grava_quantidades(tmp_path):
    a = anotador_com_relogio(tmp_path)
    a.iniciar()
    a.minuto_da_captura(1, True)

    assert ler_estado(tmp_path).quantidades is None
    bruto = json.loads((tmp_path / NOME_DO_ESTADO).read_text(encoding="utf-8"))
    assert bruto["quantidades"] is None
    assert bruto["terminada_em"] is None


def test_AC_016_7_quantidades_sao_relidas_do_disco_por_outro_leitor(tmp_path):
    a = anotador_em_processamento(tmp_path)

    a.evento_aceito(1, Categoria.CARRO)
    a.evento_aceito(1, Categoria.CARRO)
    a.evento_aceito(1, Categoria.ONIBUS)
    a.evento_aceito(1, Categoria.CAMINHAO)
    a.evento_aceito(1, Categoria.MOTO)

    # Leitor novo, sem nada em memória: só o que está em disco.
    assert ler_estado(tmp_path).quantidades == {
        "CARRO": 2,
        "ONIBUS": 1,
        "CAMINHAO": 1,
        "MOTO": 1,
    }


def test_AC_016_8_minuto_descartado_volta_ao_valor_de_antes_do_minuto(tmp_path):
    a = anotador_em_processamento(tmp_path)
    a.evento_aceito(1, Categoria.CARRO)
    a.evento_aceito(1, Categoria.MOTO)
    a.minuto_processado()
    antes_do_minuto_2 = ler_estado(tmp_path).quantidades

    a.evento_aceito(2, Categoria.CARRO)
    a.evento_aceito(2, Categoria.CARRO)
    a.evento_aceito(2, Categoria.CAMINHAO)
    assert ler_estado(tmp_path).quantidades != antes_do_minuto_2
    a.minuto_descartado(2)

    assert ler_estado(tmp_path).quantidades == antes_do_minuto_2
    assert antes_do_minuto_2 == {"CARRO": 1, "ONIBUS": 0, "CAMINHAO": 0, "MOTO": 1}


def test_AC_016_8_minuto_ja_processado_nao_e_descontado(tmp_path):
    a = anotador_em_processamento(tmp_path)
    a.evento_aceito(1, Categoria.CARRO)
    a.minuto_processado()

    a.minuto_descartado(1)

    assert ler_estado(tmp_path).quantidades["CARRO"] == 1


@pytest.mark.parametrize(
    "fase",
    [
        Fase.CONCLUIDA,
        Fase.SEM_PLANILHA,
        Fase.PROCESSAMENTO_CANCELADO,
        Fase.FALHOU,
    ],
)
def test_AC_018_2_terminar_grava_o_instante_de_termino_do_relogio_injetado(
    tmp_path, fase
):
    fim = INICIO + timedelta(minutes=17, seconds=5)
    a = anotador_em_processamento(tmp_path, agora=lambda: fim)
    a.evento_aceito(1, Categoria.CARRO)

    a.terminar(fase, mensagem="x")

    estado = ler_estado(tmp_path)
    assert estado.terminada_em == fim
    assert estado.quantidades["CARRO"] == 1


def test_estado_de_versao_anterior_sem_campos_novos_e_lido_sem_falhar(tmp_path):
    a = anotador_com_relogio(tmp_path)
    a.iniciar()
    caminho = tmp_path / NOME_DO_ESTADO
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    del dados["quantidades"]
    del dados["terminada_em"]
    caminho.write_text(json.dumps(dados), encoding="utf-8")

    estado = ler_estado(tmp_path)

    assert estado is not None
    assert estado.quantidades is None
    assert estado.terminada_em is None


def test_falha_ao_regravar_por_evento_nao_levanta(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "ESPERA_ENTRE_TENTATIVAS", 0)
    a = anotador_em_processamento(tmp_path)

    def negado(origem, destino):
        raise OSError("disco cheio")

    monkeypatch.setattr(state.os, "replace", negado)

    a.evento_aceito(1, Categoria.CARRO)
    a.minuto_descartado(1)

    assert list(tmp_path.glob("*.tmp")) == []


# --- layout-interface: Tm, minutos com dado e veículos por minuto (T-02) ---


class RelogioMutavel:
    def __init__(self, instante: datetime) -> None:
        self.instante = instante

    def __call__(self) -> datetime:
        return self.instante


def test_AC_022_6_minuto_iniciado_grava_tm_do_relogio_injetado(tmp_path):
    relogio = RelogioMutavel(INICIO + timedelta(minutes=6))
    a = anotador_em_processamento(tmp_path, agora=relogio)

    a.minuto_iniciado()
    assert ler_estado(tmp_path).minuto_em_analise_desde == relogio.instante

    a.minuto_processado()
    relogio.instante = INICIO + timedelta(minutes=7, seconds=21)
    a.minuto_iniciado()

    assert ler_estado(tmp_path).minuto_em_analise_desde == relogio.instante


def test_AC_022_6_captura_nao_grava_tm(tmp_path):
    a = anotador_com_relogio(tmp_path)
    a.iniciar()
    a.minuto_da_captura(1, True)

    assert ler_estado(tmp_path).minuto_em_analise_desde is None
    bruto = json.loads((tmp_path / NOME_DO_ESTADO).read_text(encoding="utf-8"))
    assert bruto["minuto_em_analise_desde"] is None


def test_AC_022_3_minuto_concluido_com_dado_soma_k_e_grava_v(tmp_path):
    a = anotador_em_processamento(tmp_path)

    a.minuto_iniciado()
    a.evento_aceito(1, Categoria.CARRO)
    a.evento_aceito(1, Categoria.MOTO)
    a.minuto_processado()
    estado = ler_estado(tmp_path)
    assert (estado.minutos_com_dado, estado.veiculos_nos_minutos_com_dado) == (1, 2)

    a.minuto_iniciado()
    a.evento_aceito(2, Categoria.ONIBUS)
    a.minuto_processado()
    estado = ler_estado(tmp_path)
    assert (estado.minutos_com_dado, estado.veiculos_nos_minutos_com_dado) == (2, 3)


def test_AC_022_3_minuto_descartado_nao_entra_em_k_nem_em_v(tmp_path):
    a = anotador_em_processamento(tmp_path)
    a.minuto_iniciado()
    a.evento_aceito(1, Categoria.CARRO)
    a.minuto_processado()

    a.minuto_iniciado()
    a.evento_aceito(2, Categoria.CARRO)
    a.minuto_descartado(2)
    a.minuto_processado()

    estado = ler_estado(tmp_path)
    assert (estado.minutos_com_dado, estado.veiculos_nos_minutos_com_dado) == (1, 1)


def test_AC_022_3_minuto_sem_evento_e_sem_descarte_conta_em_k(tmp_path):
    a = anotador_em_processamento(tmp_path)

    a.minuto_iniciado()
    a.minuto_processado()

    estado = ler_estado(tmp_path)
    assert (estado.minutos_com_dado, estado.veiculos_nos_minutos_com_dado) == (1, 0)


def test_AC_022_3_evento_do_minuto_em_analise_nao_entra_em_v(tmp_path):
    a = anotador_em_processamento(tmp_path)
    a.minuto_iniciado()

    a.evento_aceito(1, Categoria.CARRO)

    estado = ler_estado(tmp_path)
    assert estado.veiculos_nos_minutos_com_dado == 0
    assert estado.minutos_com_dado == 0


def test_estado_de_versao_anterior_sem_tm_e_sem_k_e_lido_sem_falhar(tmp_path):
    a = anotador_em_processamento(tmp_path)
    caminho = tmp_path / NOME_DO_ESTADO
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    for campo in (
        "minuto_em_analise_desde",
        "minutos_com_dado",
        "veiculos_nos_minutos_com_dado",
    ):
        del dados[campo]
    caminho.write_text(json.dumps(dados), encoding="utf-8")

    estado = ler_estado(tmp_path)

    assert estado is not None
    assert estado.minuto_em_analise_desde is None
    assert estado.minutos_com_dado == 0
    assert estado.veiculos_nos_minutos_com_dado == 0


def test_falha_ao_regravar_tm_nao_levanta(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "ESPERA_ENTRE_TENTATIVAS", 0)
    a = anotador_em_processamento(tmp_path)

    def negado(origem, destino):
        raise OSError("disco cheio")

    monkeypatch.setattr(state.os, "replace", negado)

    a.minuto_iniciado()
    a.minuto_processado()

    assert list(tmp_path.glob("*.tmp")) == []


# --- download-clipes: manter_videos e clipes no estado (T-01) ---


@pytest.mark.parametrize("manter_videos", [True, False])
def test_AC_024_3_iniciar_grava_a_escolha_de_manter_videos(tmp_path, manter_videos):
    a = AnotadorDoEstado(
        tmp_path,
        pid=4242,
        id_camera="000013",
        nome_camera="Praça Renascença",
        duracao_pedida=5,
        iniciada_em=INICIO,
        manter_videos=manter_videos,
    )

    a.iniciar()

    assert ler_estado(tmp_path).manter_videos is manter_videos
    bruto = json.loads((tmp_path / NOME_DO_ESTADO).read_text(encoding="utf-8"))
    assert bruto["manter_videos"] is manter_videos


def test_AC_025_1_terminar_grava_os_clipes_em_ordem_com_last_modified_em_utc(tmp_path):
    a = anotador_com_relogio(tmp_path, manter_videos=True)
    a.iniciar()

    clipes = (
        ClipeMantido(
            minuto=1,
            caminho=tmp_path / "minuto-01.mp4",
            last_modified=datetime(2026, 11, 8, 8, 0, tzinfo=timezone(timedelta(hours=-3))),
            duracao_segundos=59,
        ),
        ClipeMantido(
            minuto=2,
            caminho=tmp_path / "minuto-02.mp4",
            last_modified=datetime(2026, 11, 8, 11, 1, tzinfo=timezone.utc),
            duracao_segundos=60,
        ),
    )
    a.terminar(Fase.CONCLUIDA, status="COMPLETA", clipes=clipes)

    estado = ler_estado(tmp_path)
    assert estado.clipes == clipes
    assert [c.minuto for c in estado.clipes] == [1, 2]
    assert estado.clipes[0].last_modified == datetime(2026, 11, 8, 11, 0, tzinfo=timezone.utc)

    bruto = json.loads((tmp_path / NOME_DO_ESTADO).read_text(encoding="utf-8"))
    assert bruto["clipes"][0]["last_modified"] == "2026-11-08T11:00:00+00:00"
    assert bruto["clipes"][0]["duracao_segundos"] == 59
    assert bruto["clipes"][1]["last_modified"] == "2026-11-08T11:01:00+00:00"


def test_AC_025_1_clipe_sem_duracao_e_gravado_com_null(tmp_path):
    a = anotador_com_relogio(tmp_path, manter_videos=True)
    a.iniciar()

    clipe = ClipeMantido(
        minuto=1,
        caminho=tmp_path / "minuto-01.mp4",
        last_modified=INICIO,
        duracao_segundos=None,
    )
    a.terminar(Fase.CONCLUIDA, status="COMPLETA", clipes=(clipe,))

    assert ler_estado(tmp_path).clipes[0].duracao_segundos is None
    bruto = json.loads((tmp_path / NOME_DO_ESTADO).read_text(encoding="utf-8"))
    assert bruto["clipes"][0]["duracao_segundos"] is None


def test_estado_de_versao_anterior_sem_manter_videos_nem_clipes_e_lido_sem_falhar(
    tmp_path,
):
    a = anotador_com_relogio(tmp_path)
    a.iniciar()
    caminho = tmp_path / NOME_DO_ESTADO
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    del dados["manter_videos"]
    del dados["clipes"]
    caminho.write_text(json.dumps(dados), encoding="utf-8")

    estado = ler_estado(tmp_path)

    assert estado is not None
    assert estado.manter_videos is False
    assert estado.clipes is None


def test_last_modified_sem_fuso_e_recusado():
    with pytest.raises(ValueError, match="fuso"):
        ClipeMantido(
            minuto=1,
            caminho=Path("minuto-01.mp4"),
            last_modified=datetime(2026, 11, 8, 8, 0),
            duracao_segundos=None,
        )


# --- processamento-upload: estado da sessão de upload (D-11, D-12) ---

from auto_counter.pipeline.state import (  # noqa: E402
    SituacaoDoVideo,
    VideoNoEstado,
)


def anotador_de_upload(data_dir, nomes=("a.mp4", "b.mp4", "c.mov"), minutos=5):
    return AnotadorDoEstado(
        data_dir,
        pid=4242,
        id_camera="000013",
        nome_camera="Praça Renascença",
        duracao_pedida=minutos,
        iniciada_em=INICIO,
        origem="UPLOAD",
        videos=nomes,
    )


def test_AC_028_3_upload_nasce_em_processamento_com_todos_em_fila_e_zeros(tmp_path):
    a = anotador_de_upload(tmp_path)
    a.iniciar()

    estado = ler_estado(tmp_path)

    assert estado.origem == "UPLOAD"
    assert estado.fase is Fase.PROCESSAMENTO
    assert estado.duracao_pedida == 5
    assert estado.minutos_a_processar == 5
    assert estado.minutos_processados == 0
    assert estado.quantidades == {categoria.value: 0 for categoria in Categoria}
    assert estado.videos == (
        VideoNoEstado("a.mp4", SituacaoDoVideo.FILA),
        VideoNoEstado("b.mp4", SituacaoDoVideo.FILA),
        VideoNoEstado("c.mov", SituacaoDoVideo.FILA),
    )


def test_AC_028_3_no_maximo_um_video_processando(tmp_path):
    a = anotador_de_upload(tmp_path)
    a.iniciar()
    a.video_iniciado(1)

    with pytest.raises(ValueError):
        a.video_iniciado(2)

    a.video_terminado(1, SituacaoDoVideo.CONCLUIDO)
    a.video_iniciado(2)
    situacoes = [v.situacao for v in ler_estado(tmp_path).videos]
    assert situacoes == [
        SituacaoDoVideo.CONCLUIDO,
        SituacaoDoVideo.PROCESSANDO,
        SituacaoDoVideo.FILA,
    ]


def test_AC_028_3_video_terminado_so_aceita_concluido_falhou_ou_interrompido(tmp_path):
    a = anotador_de_upload(tmp_path)
    a.iniciar()
    a.video_iniciado(1)

    with pytest.raises(ValueError):
        a.video_terminado(1, SituacaoDoVideo.FILA)
    with pytest.raises(ValueError):
        a.video_terminado(1, SituacaoDoVideo.PROCESSANDO)

    a.video_terminado(1, SituacaoDoVideo.FALHOU)
    assert ler_estado(tmp_path).videos[0].situacao is SituacaoDoVideo.FALHOU


def test_AC_016_8_minuto_sem_dado_nao_entra_na_taxa(tmp_path):
    a = anotador_de_upload(tmp_path)
    a.iniciar()
    a.video_iniciado(1)
    a.minuto_iniciado()
    a.evento_aceito(1, Categoria.CARRO)
    a.minuto_descartado(1)
    a.minuto_processado()
    a.minuto_sem_dado()

    estado = ler_estado(tmp_path)
    assert estado.minutos_processados == 2
    assert estado.minutos_com_dado == 0
    assert estado.veiculos_nos_minutos_com_dado == 0
    assert estado.quantidades[Categoria.CARRO.value] == 0


def test_AC_016_8_minuto_sem_dado_nao_soma_nos_minutos_com_dado(tmp_path):
    a = anotador_de_upload(tmp_path)
    a.iniciar()
    a.minuto_iniciado()
    a.evento_aceito(1, Categoria.CARRO)
    a.minuto_processado()
    a.minuto_sem_dado()

    estado = ler_estado(tmp_path)
    assert (estado.minutos_com_dado, estado.veiculos_nos_minutos_com_dado) == (1, 1)
    assert estado.minutos_processados == 2


def test_estado_de_versao_anterior_e_lido_como_camera_sem_videos(tmp_path):
    a = anotador(tmp_path)
    a.iniciar()
    caminho = tmp_path / NOME_DO_ESTADO
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    del dados["origem"]
    del dados["videos"]
    caminho.write_text(json.dumps(dados), encoding="utf-8")

    estado = ler_estado(tmp_path)

    assert estado.origem == "CAMERA"
    assert estado.videos == ()


def test_sessao_ao_vivo_continua_em_captura_sem_videos(tmp_path):
    a = anotador(tmp_path)
    a.iniciar()

    estado = ler_estado(tmp_path)
    assert estado.fase is Fase.CAPTURA
    assert estado.origem == "CAMERA"
    assert estado.videos == ()

"""Interface: acompanhamento, encerramento e resultado — T-16.

Critérios cobertos, de `.spec/features/interface-sessao/spec.md`: AC-012.1 a
AC-012.6.

A trava e o `sessao_atual.json` são montados à mão em `tmp_path`, como nos testes
de `pipeline.progress`, e a interface é o script real sob `AppTest`. Nada aqui
inicia uma sessão de verdade, abre navegador ou toca a rede.
"""

import os
from datetime import datetime, timedelta, timezone

import pytest

from auto_counter.capture.status import StatusDaSessao
from auto_counter.counting.config import Categoria
from auto_counter.pipeline.lock import adquirir_trava
from auto_counter.pipeline.state import (
    MENSAGEM_SESSAO_CANCELADA,
    AnotadorDoEstado,
    Fase,
)
from auto_counter.pipeline.stop import NOME_DO_PEDIDO
from auto_counter.storage.connection import conectar
from tests.export_helpers import ID_SESSAO, gravar_sessao
from tests.test_ui_formulario import (  # noqa: F401  (fixtures usadas por nome)
    abre_a_interface,
    ambiente,
    registro_com,
)

INICIO = datetime(2026, 9, 7, 11, 0, tzinfo=timezone.utc)


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    registro_com(tmp_path, monkeypatch, "valida_000013.yaml")
    return tmp_path / "data"


def anotador(data_dir, duracao_pedida=5) -> AnotadorDoEstado:
    return AnotadorDoEstado(
        data_dir,
        pid=os.getpid(),
        id_camera="000013",
        nome_camera="Praça Exemplo",
        duracao_pedida=duracao_pedida,
        iniciada_em=INICIO,
    )


def trava_do_run(data_dir):
    return adquirir_trava(
        data_dir,
        comando="run",
        id_camera="000013",
        nome_camera="Praça Exemplo",
        agora=lambda: INICIO,
    )


def botoes(at) -> list[str]:
    return [b.label for b in at.button]


def textos(at) -> str:
    """Todo o texto de marcação, aviso, informação e erro da página."""
    partes = [m.value for m in at.markdown]
    partes += [e.value for e in at.warning]
    partes += [e.value for e in at.info]
    partes += [e.value for e in at.error]
    partes += [e.value for e in at.success]
    partes += [e.value for e in at.caption]
    return "\n".join(partes)


def tempo(at, rotulo: str) -> str:
    """O valor de um cronômetro: o markdown logo depois do rótulo (AC-017.1).

    Rótulo e valor são dois elementos, para o rótulo ficar pequeno acima do
    número grande, como no protótipo.
    """
    valores = [m.value for m in at.markdown]
    return valores[valores.index(rotulo) + 1]


def downloads(at) -> list:
    return list(at.get("download_button"))


def clica(at, rotulo: str):
    botao = next(b for b in at.button if b.label == rotulo)
    botao.click()
    return at.run()


def captura_em_curso(data_dir):
    a = anotador(data_dir)
    a.iniciar()
    a.minuto_da_captura(1, True)
    a.minuto_da_captura(2, False)
    a.minuto_da_captura(3, True)


def termina(data_dir, fase, **campos):
    a = anotador(data_dir)
    a.iniciar()
    a.terminar(fase, id_sessao=ID_SESSAO, **campos)


def test_AC_012_1_a_interface_mostra_capturados_do_total_e_perdidos(data_dir):
    captura_em_curso(data_dir)

    with trava_do_run(data_dir):
        at = abre_a_interface()

    assert not at.exception
    assert "2 de 5 minutos capturados, 1 perdidos" in textos(at)
    assert "Minutos perdidos: 2" in textos(at)


def test_AC_012_2_a_interface_indica_a_fase_de_captura_e_o_progresso(data_dir):
    captura_em_curso(data_dir)

    with trava_do_run(data_dir):
        at = abre_a_interface()

    assert "Capturando" in textos(at)
    assert "Processando" not in textos(at)
    # Três dos cinco minutos já foram resolvidos (dois capturados e um perdido).
    assert at.get("progress")[0].proto.value == 60


def test_AC_012_2_a_interface_indica_a_fase_de_processamento_e_o_progresso(data_dir):
    a = anotador(data_dir)
    a.iniciar()
    a.minuto_da_captura(1, True)
    a.minuto_da_captura(2, True)
    a.processamento_iniciado(ID_SESSAO, 2)
    a.minuto_processado()

    with trava_do_run(data_dir):
        at = abre_a_interface()

    assert "Processando" in textos(at)
    assert "1 de 2 minutos analisados" in textos(at)
    assert "Capturando" not in textos(at)
    assert at.get("progress")[0].proto.value == 50


def test_AC_012_3_sessao_concluida_mostra_o_status_e_oferece_o_download(data_dir):
    with conectar(data_dir) as conexao:
        gravar_sessao(conexao, status=StatusDaSessao.COMPLETA)
    planilha = data_dir / "000013_20260907_0800_2min.xlsx"
    planilha.write_bytes(b"conteudo do xlsx")
    termina(data_dir, Fase.CONCLUIDA, status="COMPLETA", planilha=str(planilha))

    at = abre_a_interface()

    assert not at.exception
    assert "status COMPLETA" in textos(at)
    (download,) = downloads(at)
    assert download.proto.label == "Baixar .xlsx"
    assert botoes(at).count("Parar antecipadamente") == 0


def test_AC_012_3_sessao_degradada_mostra_o_aviso_junto_do_download(data_dir):
    with conectar(data_dir) as conexao:
        gravar_sessao(
            conexao,
            duracao_pedida=5,
            status=StatusDaSessao.DEGRADADA,
            minutos_perdidos=(2,),
        )
    planilha = data_dir / "x.xlsx"
    planilha.write_bytes(b"xlsx")
    termina(data_dir, Fase.CONCLUIDA, status="DEGRADADA", planilha=str(planilha))

    at = abre_a_interface()

    assert "status DEGRADADA" in textos(at)
    assert any("1 de 5" in w.value for w in at.warning)
    assert len(downloads(at)) == 1


def test_AC_012_4_reabrir_a_interface_reencontra_a_sessao_em_andamento(data_dir):
    captura_em_curso(data_dir)

    with trava_do_run(data_dir):
        primeira = abre_a_interface()
        # Outra aba, outra sessão do navegador: nada em comum além do disco.
        segunda = abre_a_interface()

    assert "2 de 5 minutos capturados" in textos(primeira)
    assert textos(primeira) == textos(segunda)
    assert not (data_dir / NOME_DO_PEDIDO).exists()


def test_AC_012_4_abrir_e_atualizar_a_interface_nunca_cria_pedido_de_parada(data_dir):
    captura_em_curso(data_dir)

    with trava_do_run(data_dir):
        at = abre_a_interface()
        at.run()
        at.run()

    assert not (data_dir / NOME_DO_PEDIDO).exists()


def test_AC_012_4_encerrar_so_pede_a_parada_depois_da_confirmacao(data_dir):
    captura_em_curso(data_dir)

    with trava_do_run(data_dir):
        at = abre_a_interface()
        assert "Parar antecipadamente" in botoes(at)

        at = clica(at, "Parar antecipadamente")
        # O primeiro clique só pergunta.
        assert not (data_dir / NOME_DO_PEDIDO).exists()
        assert "A sessão será cancelada" in textos(at)
        assert "Confirmar encerramento" in botoes(at)

        at = clica(at, "Voltar")
        assert not (data_dir / NOME_DO_PEDIDO).exists()
        assert "Parar antecipadamente" in botoes(at)

        at = clica(at, "Parar antecipadamente")
        at = clica(at, "Confirmar encerramento")

    assert (data_dir / NOME_DO_PEDIDO).is_file()


def test_AC_012_4_o_aviso_de_encerrar_no_processamento_fala_em_cancelar(data_dir):
    a = anotador(data_dir)
    a.iniciar()
    a.minuto_da_captura(1, True)
    a.processamento_iniciado(ID_SESSAO, 1)

    with trava_do_run(data_dir):
        at = abre_a_interface()
        at = clica(at, "Parar antecipadamente")

    assert "A contagem será cancelada" in textos(at)
    assert "vídeos serão mantidos" in textos(at)


def test_AC_012_5_processamento_cancelado_informa_e_nao_oferece_download(data_dir):
    termina(
        data_dir,
        Fase.PROCESSAMENTO_CANCELADO,
        status="COMPLETA",
        mensagem="reprocesse com `auto-counter session process x`",
    )

    at = abre_a_interface()

    assert any("Processamento cancelado" in i.value for i in at.info)
    assert "session process" in textos(at)
    assert downloads(at) == []


def test_AC_012_6_sessao_sem_planilha_mostra_status_e_aviso_sem_download(data_dir):
    termina(
        data_dir,
        Fase.SEM_PLANILHA,
        status="INVALIDA",
        mensagem="nenhum clipe da sessão pôde ser processado; não há planilha.",
    )

    at = abre_a_interface()

    assert any(
        "INVALIDA" in w.value and "não há planilha" in w.value for w in at.warning
    )
    assert downloads(at) == []


def test_sessao_do_terminal_aparece_sem_botao_de_encerrar(data_dir):
    with adquirir_trava(
        data_dir,
        comando="capture",
        id_camera="000042",
        nome_camera="Outro local",
        agora=lambda: INICIO,
    ):
        at = abre_a_interface()

    assert "Outro local" in textos(at)
    assert "Parar antecipadamente" not in botoes(at)
    assert at.get("progress") == []


def test_sessao_que_terminou_sem_concluir_aparece_como_falha(data_dir):
    # Estado não terminal de um processo que não existe mais.
    AnotadorDoEstado(
        data_dir,
        pid=2**22 + 777,
        id_camera="000013",
        nome_camera="Praça Exemplo",
        duracao_pedida=5,
        iniciada_em=INICIO,
    ).iniciar()

    at = abre_a_interface()

    assert any("terminou sem concluir" in e.value for e in at.error)
    assert downloads(at) == []


ROTULOS_DAS_METRICAS = ["Carro", "Ônibus", "Caminhão", "Moto", "Total"]
AVISO_DA_CAPTURA = "A contagem de veículos começa quando a captura terminar."


class Relogio:
    """O relógio da leitura de `ler_progresso`, fixado pelo teste."""

    def __init__(self, instante: datetime = INICIO) -> None:
        self.instante = instante

    def avancar(self, **intervalo) -> None:
        self.instante = self.instante + timedelta(**intervalo)


@pytest.fixture
def relogio(monkeypatch) -> Relogio:
    relogio = Relogio()
    monkeypatch.setattr("auto_counter.pipeline.progress._agora", lambda: relogio.instante)
    return relogio


def metricas(at) -> list[tuple[str, str]]:
    return [(m.proto.label, m.value) for m in at.metric]


def em_processamento(data_dir, fim: datetime | None = None) -> AnotadorDoEstado:
    a = AnotadorDoEstado(
        data_dir,
        pid=os.getpid(),
        id_camera="000013",
        nome_camera="Praça Exemplo",
        duracao_pedida=5,
        iniciada_em=INICIO,
        **({} if fim is None else {"agora": lambda: fim}),
    )
    a.iniciar()
    a.minuto_da_captura(1, True)
    a.processamento_iniciado(ID_SESSAO, 1)
    return a


def test_AC_016_1_processamento_mostra_cinco_metricas_em_zero(data_dir, relogio):
    em_processamento(data_dir)

    with trava_do_run(data_dir):
        at = abre_a_interface()

    assert not at.exception
    assert metricas(at) == [(rotulo, "0") for rotulo in ROTULOS_DAS_METRICAS]


def test_AC_016_5_captura_mostra_aviso_e_nenhuma_metrica(data_dir, relogio):
    captura_em_curso(data_dir)

    with trava_do_run(data_dir):
        at = abre_a_interface()

    assert not at.exception
    assert at.metric == []
    assert AVISO_DA_CAPTURA in textos(at)


def test_AC_016_2_processamento_mostra_as_quantidades_e_o_total(data_dir, relogio):
    a = em_processamento(data_dir)
    for categoria in (Categoria.CARRO, Categoria.CARRO, Categoria.MOTO):
        a.evento_aceito(1, categoria)

    with trava_do_run(data_dir):
        at = abre_a_interface()

    assert metricas(at) == [
        ("Carro", "2"),
        ("Ônibus", "0"),
        ("Caminhão", "0"),
        ("Moto", "1"),
        ("Total", "3"),
    ]
    assert AVISO_DA_CAPTURA not in textos(at)


def test_AC_016_7_reabrir_a_interface_mostra_as_mesmas_quantidades(data_dir, relogio):
    a = em_processamento(data_dir)
    a.evento_aceito(1, Categoria.ONIBUS)
    a.evento_aceito(1, Categoria.CAMINHAO)

    with trava_do_run(data_dir):
        primeira = abre_a_interface()
        segunda = abre_a_interface()

    assert metricas(primeira) == metricas(segunda)
    assert ("Total", "2") in metricas(segunda)


def test_AC_017_1_captura_e_processamento_mostram_tempo_decorrido_mm_ss(
    data_dir, relogio
):
    relogio.avancar(minutes=1, seconds=15, milliseconds=900)

    captura_em_curso(data_dir)
    with trava_do_run(data_dir):
        na_captura = abre_a_interface()

    assert tempo(na_captura, "Tempo decorrido") == "01:15"

    em_processamento(data_dir)
    with trava_do_run(data_dir):
        no_processamento = abre_a_interface()

    assert tempo(no_processamento, "Tempo decorrido") == "01:15"


def test_AC_017_3_tempo_exibido_avanca_com_o_relogio(data_dir, relogio):
    em_processamento(data_dir)

    with trava_do_run(data_dir):
        at = abre_a_interface()
        assert tempo(at, "Tempo decorrido") == "00:00"
        relogio.avancar(seconds=42)
        at = at.run()

    assert tempo(at, "Tempo decorrido") == "00:42"


def test_AC_017_4_reabrir_mostra_tempo_desde_o_inicio_da_sessao(data_dir, relogio):
    em_processamento(data_dir)
    relogio.avancar(minutes=7, seconds=3)

    with trava_do_run(data_dir):
        reaberta = abre_a_interface()

    assert tempo(reaberta, "Tempo decorrido") == "07:03"


def test_AC_018_1_concluida_mostra_metricas_finais_e_tempo_total(data_dir, relogio):
    with conectar(data_dir) as conexao:
        gravar_sessao(conexao, status=StatusDaSessao.COMPLETA)
    planilha = data_dir / "000013_20260907_0800_1min.xlsx"
    planilha.write_bytes(b"xlsx")
    a = em_processamento(data_dir, fim=INICIO + timedelta(minutes=17, seconds=5))
    a.evento_aceito(1, Categoria.CARRO)
    a.evento_aceito(1, Categoria.CARRO)
    a.evento_aceito(1, Categoria.MOTO)
    a.minuto_processado()
    a.terminar(
        Fase.CONCLUIDA, id_sessao=ID_SESSAO, status="COMPLETA", planilha=str(planilha)
    )
    relogio.avancar(hours=3)

    at = abre_a_interface()

    assert not at.exception
    assert metricas(at) == [
        ("Carro", "2"),
        ("Ônibus", "0"),
        ("Caminhão", "0"),
        ("Moto", "1"),
        ("Total", "3"),
    ]
    assert "Concluída · 17:05" in textos(at)
    (download,) = downloads(at)
    assert download.proto.label == "Baixar .xlsx"


@pytest.mark.parametrize(
    "fase",
    [Fase.PROCESSAMENTO_CANCELADO, Fase.SEM_PLANILHA, Fase.FALHOU],
)
def test_AC_018_3_cancelada_sem_planilha_e_falhou_mostram_so_o_tempo_total(
    data_dir, relogio, fase
):
    a = em_processamento(data_dir, fim=INICIO + timedelta(minutes=2, seconds=30))
    a.evento_aceito(1, Categoria.CARRO)
    a.terminar(fase, id_sessao=ID_SESSAO, status="COMPLETA", mensagem="desfecho")

    at = abre_a_interface()

    assert not at.exception
    assert at.metric == []
    assert "Tempo total: 02:30" in textos(at)


def test_AC_018_4_processo_morto_nao_mostra_metricas_nem_tempo(data_dir, relogio):
    a = AnotadorDoEstado(
        data_dir,
        pid=2**22 + 777,
        id_camera="000013",
        nome_camera="Praça Exemplo",
        duracao_pedida=5,
        iniciada_em=INICIO,
    )
    a.iniciar()
    a.minuto_da_captura(1, True)
    a.processamento_iniciado(ID_SESSAO, 1)
    a.evento_aceito(1, Categoria.CARRO)

    at = abre_a_interface()

    assert any("terminou sem concluir" in e.value for e in at.error)
    assert at.metric == []
    assert "Tempo" not in textos(at)


# --- AC-012.7: sessão cancelada pelo usuário na captura ---


def cancelada_na_captura(data_dir, fim: datetime | None = None) -> None:
    a = AnotadorDoEstado(
        data_dir,
        pid=os.getpid(),
        id_camera="000013",
        nome_camera="Praça Exemplo",
        duracao_pedida=5,
        iniciada_em=INICIO,
        **({} if fim is None else {"agora": lambda: fim}),
    )
    a.iniciar()
    a.minuto_da_captura(1, True)
    a.minuto_da_captura(2, True)
    a.terminar(
        Fase.SESSAO_CANCELADA,
        id_sessao=ID_SESSAO,
        status="COMPLETA",
        mensagem=MENSAGEM_SESSAO_CANCELADA,
    )


def test_AC_018_3_sessao_cancelada_na_captura_mostra_so_o_tempo_total(
    data_dir, relogio
):
    cancelada_na_captura(data_dir, fim=INICIO + timedelta(minutes=2, seconds=30))

    at = abre_a_interface()

    assert not at.exception
    assert at.metric == []
    assert "Tempo total: 02:30" in textos(at)


def test_AC_012_7_sessao_cancelada_nao_oferece_download_nem_reprocessar(
    data_dir, relogio
):
    cancelada_na_captura(data_dir)

    at = abre_a_interface()

    assert not at.exception
    assert any("Sessão cancelada pelo usuário" in i.value for i in at.info)
    assert downloads(at) == []
    texto = textos(at).lower()
    assert "session process" not in texto
    assert "reprocess" not in texto

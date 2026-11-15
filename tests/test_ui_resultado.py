"""Interface: painel "Sessão finalizada" — T-12 de `layout-interface`.

Critérios cobertos, de `.spec/features/layout-interface/spec.md`: AC-023.2,
AC-023.3 e AC-023.4 (SUP-073, SUP-075).

O `AppTest` não oferece clique em `download_button`. Por isso AC-023.3 é
verificado de duas formas, sem simular o navegador:

- um espião em `streamlit.download_button` registra o que a interface entrega
  (rótulo, bytes, nome do arquivo e o `on_click` com a chave do resultado);
- a marca de "baixado" é gravada em `at.session_state["planilha_baixada"]` com a
  chave do resultado, e a página roda de novo, como o `on_click` faria na aba.

A trava e o `sessao_atual.json` são montados à mão em `tmp_path`. Nada aqui
inicia sessão, abre navegador ou toca a rede.
"""

import os
from datetime import timedelta

import pytest
import streamlit

from auto_counter.capture.status import StatusDaSessao
from auto_counter.pipeline.progress import ler_progresso
from auto_counter.pipeline.state import AnotadorDoEstado, Fase
from auto_counter.storage.connection import caminho_do_banco, conectar
from tests.export_helpers import ID_SESSAO, evento, gravar_sessao
from tests.test_ui_acompanhamento import (  # noqa: F401  (fixtures usadas por nome)
    INICIO,
    data_dir,
    downloads,
    termina,
    textos,
)
from tests.test_ui_formulario import (  # noqa: F401  (fixtures usadas por nome)
    abre_a_interface,
    ambiente,
    registro_com,
)

DURACAO = timedelta(minutes=17, seconds=5)
NOME_DA_PLANILHA = "000013_20260907_0800_2min.xlsx"
CONTEUDO = b"conteudo do xlsx"


def concluida(
    data_dir,
    *,
    eventos: int = 0,
    encerrada_pelo_usuario: bool = False,
    iniciada_em=INICIO,
    com_tempo: bool = True,
):
    """Sessão concluída com planilha em disco; devolve o caminho da planilha."""
    data_dir.mkdir(parents=True, exist_ok=True)
    with conectar(data_dir) as conexao:
        gravar_sessao(
            conexao,
            status=StatusDaSessao.COMPLETA,
            encerrada_pelo_usuario=encerrada_pelo_usuario,
            eventos=tuple(
                evento(minuto=1, id_de_rastreio=f"r{i}") for i in range(eventos)
            ),
        )
    planilha = data_dir / NOME_DA_PLANILHA
    planilha.write_bytes(CONTEUDO)
    fim = iniciada_em + DURACAO
    a = AnotadorDoEstado(
        data_dir,
        pid=os.getpid(),
        id_camera="000013",
        nome_camera="Praça Exemplo",
        duracao_pedida=2,
        iniciada_em=iniciada_em,
        agora=lambda: fim,
    )
    a.iniciar()
    a.terminar(
        Fase.CONCLUIDA, id_sessao=ID_SESSAO, status="COMPLETA", planilha=str(planilha)
    )
    return planilha


def rotulo_do_download(at) -> str:
    (download,) = downloads(at)
    return download.proto.label


def chave_do_resultado(data_dir) -> str:
    return ler_progresso(data_dir).resultado.chave


@pytest.fixture
def entregas(monkeypatch) -> list[dict]:
    """O que a interface entrega a cada `st.download_button` desenhado."""
    registradas: list[dict] = []
    original = streamlit.download_button

    def espiao(label, data, *args, **kwargs):
        registradas.append({"label": label, "data": data, **kwargs})
        return original(label, data, *args, **kwargs)

    monkeypatch.setattr(streamlit, "download_button", espiao)
    return registradas


def test_AC_023_2_concluida_mostra_concluida_com_o_tempo_total(data_dir):
    concluida(data_dir)

    at = abre_a_interface()

    assert not at.exception
    assert "Sessão finalizada" in [s.value for s in at.subheader]
    assert "Concluída · 17:05" in textos(at)
    assert "Interrompida" not in textos(at)
    assert "Tempo total" not in textos(at)


def test_AC_023_2_encerrada_pelo_usuario_mostra_interrompida_com_o_tempo_total(
    data_dir,
):
    concluida(data_dir, encerrada_pelo_usuario=True)

    at = abre_a_interface()

    assert "Interrompida pelo usuário · 17:05" in textos(at)
    assert "Concluída" not in textos(at)


def test_AC_023_2_cartao_mostra_nome_do_arquivo_e_n_registros(data_dir):
    concluida(data_dir, eventos=3)

    at = abre_a_interface()

    assert NOME_DA_PLANILHA in textos(at)
    assert "3 registros · contagem por categoria e por minuto" in textos(at)
    assert rotulo_do_download(at) == "Baixar .xlsx"


def test_AC_023_2_banco_ilegivel_mostra_traco_no_lugar_do_numero(data_dir):
    planilha = concluida(data_dir, eventos=3)
    caminho_do_banco(data_dir).write_bytes(b"isto nao e um banco sqlite" * 50)

    at = abre_a_interface()

    assert planilha.name in textos(at)
    assert "— registros · contagem por categoria e por minuto" in textos(at)


def test_AC_023_3_baixar_entrega_o_arquivo_da_sessao_e_vira_baixado(
    data_dir, entregas
):
    planilha = concluida(data_dir)
    at = abre_a_interface()

    assert entregas[-1]["label"] == "Baixar .xlsx"
    assert entregas[-1]["data"] == planilha.read_bytes() == CONTEUDO
    assert entregas[-1]["file_name"] == NOME_DA_PLANILHA
    assert entregas[-1]["args"] == (chave_do_resultado(data_dir),)
    assert callable(entregas[-1]["on_click"])

    # É o que o `on_click` grava na aba depois do acionamento.
    at.session_state["planilha_baixada"] = chave_do_resultado(data_dir)
    at = at.run()

    assert rotulo_do_download(at) == "✓ Baixado"
    assert entregas[-1]["data"] == CONTEUDO


def test_AC_023_3_baixado_nao_passa_para_a_sessao_seguinte(data_dir):
    concluida(data_dir)
    at = abre_a_interface()
    at.session_state["planilha_baixada"] = chave_do_resultado(data_dir)
    at = at.run()
    assert rotulo_do_download(at) == "✓ Baixado"

    concluida(data_dir, iniciada_em=INICIO + timedelta(hours=1))
    at = at.run()

    assert rotulo_do_download(at) == "Baixar .xlsx"


def test_AC_023_3_aba_nova_mostra_baixar_de_novo(data_dir):
    concluida(data_dir)
    aba = abre_a_interface()
    aba.session_state["planilha_baixada"] = chave_do_resultado(data_dir)
    aba = aba.run()
    assert rotulo_do_download(aba) == "✓ Baixado"

    outra_aba = abre_a_interface()

    assert rotulo_do_download(outra_aba) == "Baixar .xlsx"


@pytest.mark.parametrize(
    "fase", [Fase.PROCESSAMENTO_CANCELADO, Fase.SEM_PLANILHA, Fase.FALHOU]
)
def test_AC_023_4_cancelada_sem_planilha_e_falhou_mostram_a_mensagem_sem_cartao(
    data_dir, fase
):
    termina(data_dir, fase, status="INVALIDA", mensagem="desfecho de teste")

    at = abre_a_interface()

    assert not at.exception
    # O processamento cancelado tem texto próprio na interface; o `mensagem` do
    # estado, com o comando de reprocessar, é só do terminal.
    esperado = (
        "Processamento cancelado. Inicie uma nova sessão."
        if fase is Fase.PROCESSAMENTO_CANCELADO
        else "desfecho de teste"
    )
    assert esperado in textos(at)
    assert downloads(at) == []
    assert "registros" not in textos(at)


def test_AC_023_4_processo_morto_mostra_a_falha_sem_cartao(data_dir):
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
    assert "registros" not in textos(at)


def test_AC_023_4_planilha_que_sumiu_do_disco_mostra_a_mensagem_sem_cartao(data_dir):
    planilha = concluida(data_dir)
    planilha.unlink()

    at = abre_a_interface()

    assert any(str(planilha) in w.value for w in at.warning)
    assert downloads(at) == []
    assert "registros" not in textos(at)


def test_AC_023_4_sessao_cancelada_na_captura_mostra_a_mensagem_sem_cartao(data_dir):
    termina(
        data_dir,
        Fase.SESSAO_CANCELADA,
        status="COMPLETA",
        mensagem="Sessão cancelada pelo usuário",
    )

    at = abre_a_interface()

    assert not at.exception
    assert "Sessão cancelada pelo usuário" in textos(at)
    # O cancelamento foi pedido pelo usuário: é um aviso, e não uma falha.
    assert at.error == []
    assert downloads(at) == []
    assert "registros" not in textos(at)

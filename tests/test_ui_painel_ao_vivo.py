"""Interface: o painel "Contagem ao vivo" fixo na tela — ajuste de `layout-interface`.

O painel ao vivo é desenhado em qualquer estado, e o painel "Sessão finalizada"
fica abaixo dele, na mesma coluna. O que o painel mostra em cada estado:

- sem sessão e sem resultado na tela: zeros, "— veíc/min" e 00:00, como no
  protótipo. Não é captura, então AC-016.5 e SUP-055 não se aplicam;
- captura: sem quantidade nenhuma, só o aviso em destaque (AC-016.5, AC-022.7);
- processamento: como em `test_ui_ao_vivo.py`;
- sessão concluída: os valores finais, que são as quantidades de AC-018.1;
- sessão iniciada pelo terminal, cancelada, sem planilha, que falhou ou de
  processo morto: nenhum número (AC-018.3, AC-018.4).

Nada aqui inicia sessão, abre navegador ou toca a rede.
"""

import os
import re
from datetime import timedelta

import pytest

from auto_counter.counting.config import Categoria
from auto_counter.pipeline.lock import adquirir_trava
from auto_counter.pipeline.state import AnotadorDoEstado, Fase
from tests.export_helpers import ID_SESSAO
from tests.test_pipeline_progress import Relogio, sessao_em_processamento
from tests.test_ui_acompanhamento import (  # noqa: F401  (fixtures usadas por nome)
    INICIO,
    captura_em_curso,
    clica,
    data_dir,
    metricas,
    relogio,
    termina,
    textos,
    trava_do_run,
)
from tests.test_ui_formulario import (  # noqa: F401  (fixtures usadas por nome)
    abre_a_interface,
    ambiente,
    registro_com,
)

ZEROS = [
    ("Carro", "0"),
    ("Ônibus", "0"),
    ("Caminhão", "0"),
    ("Moto", "0"),
    ("Total", "0"),
]
MENSAGEM_DO_TERMINAL = "não acompanha o progresso"
MENSAGEM_SEM_CONTAGEM = "Sem contagem a exibir para esta sessão."


def subtitulos(at) -> list[str]:
    return [s.value for s in at.subheader]


def participacoes(at) -> list[str]:
    return [m.value for m in at.markdown if re.fullmatch(r"\d+%", m.value)]


def barras(at) -> list[int]:
    return [p.proto.value for p in at.get("progress")]


def test_sem_sessao_o_painel_ao_vivo_mostra_zeros_como_no_prototipo(data_dir):
    at = abre_a_interface()

    assert not at.exception
    assert subtitulos(at) == ["Contagem ao vivo"]
    assert metricas(at) == ZEROS
    assert participacoes(at) == ["0%"] * 4
    assert barras(at) == [0, 0, 0, 0, 0]
    assert "— veíc/min" in textos(at)
    assert "Tempo decorrido: 00:00" in textos(at)
    assert "Tempo estimado: 00:00" in textos(at)
    assert "0% concluído" in textos(at)


def test_depois_de_nova_sessao_o_painel_ao_vivo_volta_a_zerar(data_dir):
    termina(data_dir, Fase.CONCLUIDA, status="COMPLETA")
    at = abre_a_interface()

    at = clica(at, "Nova sessão")

    assert subtitulos(at) == ["Contagem ao vivo"]
    assert metricas(at) == ZEROS


def test_sessao_do_terminal_deixa_o_painel_ao_vivo_sem_numeros(data_dir):
    with adquirir_trava(
        data_dir,
        comando="capture",
        id_camera="000042",
        nome_camera="Outro local",
        agora=lambda: INICIO,
    ):
        at = abre_a_interface()

    assert subtitulos(at) == ["Contagem ao vivo"]
    assert MENSAGEM_DO_TERMINAL in textos(at)
    assert at.metric == []
    assert at.get("progress") == []


def test_captura_nao_mostra_quantidade_nenhuma_so_o_aviso_em_destaque(
    data_dir, relogio
):
    captura_em_curso(data_dir)

    with trava_do_run(data_dir):
        at = abre_a_interface()

    assert at.metric == []
    assert participacoes(at) == []
    assert "A contagem de veículos começa quando a captura terminar." in textos(at)
    assert len(at.get("progress")) == 1


def test_concluida_mostra_os_valores_finais_no_painel_ao_vivo(data_dir, relogio):
    fim = INICIO + timedelta(minutes=17, seconds=5)
    a = sessao_em_processamento(
        data_dir,
        a_processar=2,
        minutos_com_eventos=(3, 1),
        relogio=Relogio(fim),
    )
    a.terminar(Fase.CONCLUIDA, id_sessao=ID_SESSAO, status="COMPLETA")

    at = abre_a_interface()

    assert not at.exception
    # Um único conjunto de métricas: o do painel ao vivo, e não o do resultado.
    assert metricas(at) == [
        ("Carro", "4"),
        ("Ônibus", "0"),
        ("Caminhão", "0"),
        ("Moto", "0"),
        ("Total", "4"),
    ]
    assert participacoes(at) == ["100%", "0%", "0%", "0%"]
    assert "2,0 veíc/min" in textos(at)
    assert "100% concluído" in textos(at)
    assert "Tempo decorrido: 17:05" in textos(at)
    assert "Tempo estimado: 00:00" in textos(at)
    # O resultado fica abaixo do painel ao vivo.
    assert subtitulos(at) == ["Contagem ao vivo · Praça Exemplo", "Sessão finalizada"]


@pytest.mark.parametrize(
    "fase", [Fase.PROCESSAMENTO_CANCELADO, Fase.SEM_PLANILHA, Fase.FALHOU]
)
def test_AC_018_3_desfecho_sem_contagem_deixa_o_painel_ao_vivo_sem_numeros(
    data_dir, relogio, fase
):
    a = sessao_em_processamento(
        data_dir, a_processar=2, minutos_com_eventos=(3,), relogio=Relogio(INICIO)
    )
    a.terminar(fase, id_sessao=ID_SESSAO, status="COMPLETA", mensagem="desfecho")

    at = abre_a_interface()

    assert at.metric == []
    assert at.get("progress") == []
    assert MENSAGEM_SEM_CONTAGEM in textos(at)
    assert "Tempo decorrido" not in textos(at)
    assert subtitulos(at) == ["Contagem ao vivo · Praça Exemplo", "Sessão finalizada"]


def test_AC_018_4_processo_morto_deixa_o_painel_ao_vivo_sem_numeros(data_dir, relogio):
    AnotadorDoEstado(
        data_dir,
        pid=2**22 + 777,
        id_camera="000013",
        nome_camera="Praça Exemplo",
        duracao_pedida=5,
        iniciada_em=INICIO,
    ).iniciar()

    at = abre_a_interface()

    assert at.metric == []
    assert MENSAGEM_SEM_CONTAGEM in textos(at)
    assert "Tempo" not in textos(at)

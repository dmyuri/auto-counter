"""Interface: painel ao vivo e "Parar antecipadamente" — T-11 de `layout-interface`.

Critérios cobertos, de `.spec/features/layout-interface/spec.md`: AC-022.1 a
AC-022.7 e AC-023.1 (SUP-071).

A tela só exibe o que `ler_progresso` devolve: percentual, participação, taxa e
tempo estimado vêm prontos de `pipeline/progress.py` (T-06). O relógio da leitura
é a fixture `relogio`, e o estado é montado com o anotador, como nos testes de
acompanhamento. Nada aqui inicia sessão, abre navegador ou toca a rede.

A participação é o único markdown que é só "NN%"; "NN% concluído" é o percentual
da fase.
"""

import os
import re
from datetime import timedelta

import pytest

from auto_counter.counting.config import Categoria
from auto_counter.pipeline.state import AnotadorDoEstado
from auto_counter.pipeline.stop import NOME_DO_PEDIDO
from tests.test_pipeline_progress import (
    Relogio,
    com_eventos,
    sessao_em_processamento,
)
from tests.test_ui_acompanhamento import (  # noqa: F401  (fixtures usadas por nome)
    AVISO_DA_CAPTURA,
    INICIO,
    anotador,
    botoes,
    captura_em_curso,
    clica,
    data_dir,
    relogio,
    textos,
    trava_do_run,
)
from tests.test_ui_formulario import (  # noqa: F401  (fixtures usadas por nome)
    abre_a_interface,
    ambiente,
    registro_com,
)


def participacoes(at) -> list[str]:
    return [m.value for m in at.markdown if re.fullmatch(r"\d+%", m.value)]


def barras(at) -> list[int]:
    return [p.proto.value for p in at.get("progress")]


def ao_vivo(data_dir):
    """Abre a interface com a trava do `run`, como numa sessão da interface."""
    with trava_do_run(data_dir):
        return abre_a_interface()


def test_AC_022_1_titulo_traz_o_nome_do_local(data_dir, relogio):
    captura_em_curso(data_dir)

    at = ao_vivo(data_dir)

    assert "Contagem ao vivo · Praça Exemplo" in [s.value for s in at.subheader]


def test_AC_022_1_sem_nome_do_local_o_titulo_traz_o_id_da_camera(data_dir, relogio):
    a = AnotadorDoEstado(
        data_dir,
        pid=os.getpid(),
        id_camera="000013",
        nome_camera=None,
        duracao_pedida=5,
        iniciada_em=INICIO,
    )
    a.iniciar()

    at = ao_vivo(data_dir)

    assert "Contagem ao vivo · 000013" in [s.value for s in at.subheader]


def test_AC_022_2_cada_categoria_mostra_a_participacao_e_uma_barra(data_dir, relogio):
    a = sessao_em_processamento(data_dir, a_processar=2)
    com_eventos(a, {Categoria.CARRO: 1, Categoria.MOTO: 3})

    at = ao_vivo(data_dir)

    assert not at.exception
    assert participacoes(at) == ["25%", "0%", "0%", "75%"]
    # A barra da fase (0 de 2 minutos) e as quatro das categorias.
    assert barras(at) == [0, 25, 0, 0, 75]


def test_AC_022_2_total_zero_mostra_zero_por_cento_em_todas(data_dir, relogio):
    sessao_em_processamento(data_dir, a_processar=2)

    at = ao_vivo(data_dir)

    assert participacoes(at) == ["0%", "0%", "0%", "0%"]
    assert barras(at)[1:] == [0, 0, 0, 0]


def test_AC_022_3_processamento_mostra_a_taxa_com_virgula(data_dir, relogio):
    sessao_em_processamento(
        data_dir, a_processar=5, minutos_com_eventos=(1, 0, 0, 0)
    )

    at = ao_vivo(data_dir)

    assert "0,3 veíc/min" in textos(at)


def test_AC_022_3_captura_mostra_traco(data_dir, relogio):
    captura_em_curso(data_dir)

    assert "— veíc/min" in textos(ao_vivo(data_dir))


def test_AC_022_3_processamento_sem_minuto_com_dado_mostra_traco(data_dir, relogio):
    sessao_em_processamento(data_dir, a_processar=2)

    assert "— veíc/min" in textos(ao_vivo(data_dir))


def test_AC_022_4_captura_mostra_percentual_concluido_e_barra_na_mesma_proporcao(
    data_dir, relogio
):
    a = anotador(data_dir, duracao_pedida=7)
    a.iniciar()
    a.minuto_da_captura(1, True)
    a.minuto_da_captura(2, False)
    a.minuto_da_captura(3, True)

    at = ao_vivo(data_dir)

    assert "42% concluído" in textos(at)
    assert barras(at) == [42]


def test_AC_022_4_processamento_mostra_percentual_concluido_e_barra_na_mesma_proporcao(
    data_dir, relogio
):
    sessao_em_processamento(data_dir, a_processar=3, minutos_com_eventos=(0,))

    at = ao_vivo(data_dir)

    assert "33% concluído" in textos(at)
    assert barras(at)[0] == 33


def test_AC_022_5_captura_mostra_tempo_estimado_mm_ss(data_dir, relogio):
    captura_em_curso(data_dir)  # 5 minutos pedidos, 1 perdido
    relogio.avancar(seconds=130.7)

    at = ao_vivo(data_dir)

    # max(0, 300 - 130,7) + 4 * 80 = 489,3 -> 489 s
    assert "Tempo estimado: 08:09" in textos(at)


def test_AC_022_6_processamento_mostra_tempo_estimado_mm_ss(data_dir, relogio):
    inicio_do_minuto = INICIO + timedelta(minutes=10)
    sessao_em_processamento(
        data_dir,
        a_processar=3,
        minutos_com_eventos=(0,),
        relogio=Relogio(inicio_do_minuto),
    ).minuto_iniciado()
    relogio.instante = inicio_do_minuto + timedelta(seconds=30.5)

    at = ao_vivo(data_dir)

    # max(80, 160 - 30,5) = 129,5 -> 129 s
    assert "Tempo estimado: 02:09" in textos(at)


def test_AC_022_6_todos_os_minutos_analisados_mostra_zero(data_dir, relogio):
    sessao_em_processamento(data_dir, a_processar=2, minutos_com_eventos=(0, 0))

    assert "Tempo estimado: 00:00" in textos(ao_vivo(data_dir))


def test_AC_022_6_estado_sem_tm_mostra_traco_no_tempo_estimado(data_dir, relogio):
    a = AnotadorDoEstado(
        data_dir,
        pid=os.getpid(),
        id_camera="000013",
        nome_camera="Praça Exemplo",
        duracao_pedida=2,
        iniciada_em=INICIO,
    )
    a.iniciar()
    a.minuto_da_captura(1, True)
    a.processamento_iniciado("000013-20260907T110000Z", 1)

    assert "Tempo estimado: —" in textos(ao_vivo(data_dir))


def test_AC_022_7_captura_nao_mostra_participacao_nem_barra_de_categoria(
    data_dir, relogio
):
    captura_em_curso(data_dir)

    at = ao_vivo(data_dir)

    assert len(at.get("progress")) == 1
    assert at.metric == []
    assert participacoes(at) == []
    assert AVISO_DA_CAPTURA in textos(at)


def test_AC_023_1_sessao_da_interface_troca_iniciar_por_parar_antecipadamente(
    data_dir, relogio
):
    captura_em_curso(data_dir)

    at = ao_vivo(data_dir)

    assert "Iniciar sessão" not in botoes(at)
    assert "Parar antecipadamente" in botoes(at)


@pytest.mark.parametrize("fase", ["captura", "processamento"])
def test_AC_023_1_so_a_confirmacao_pede_a_parada(data_dir, relogio, fase):
    if fase == "captura":
        captura_em_curso(data_dir)
        aviso = "Os minutos já capturados serão processados"
    else:
        sessao_em_processamento(data_dir, a_processar=2)
        aviso = "A contagem será cancelada"

    with trava_do_run(data_dir):
        at = abre_a_interface()
        at = clica(at, "Parar antecipadamente")

        assert aviso in textos(at)
        assert not (data_dir / NOME_DO_PEDIDO).exists()
        assert "Confirmar encerramento" in botoes(at)

        at = clica(at, "Confirmar encerramento")

    assert (data_dir / NOME_DO_PEDIDO).is_file()

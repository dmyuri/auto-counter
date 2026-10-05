"""A linha de sessão: abrir, fechar a captura, completar o processamento —
T-03.

Comportamento em `.spec/features/persistencia-resultados/spec.md`: AC-008.1.

D-1 (`.spec/features/persistencia-resultados/_tasks.md`) dá os três momentos
do ciclo de vida de uma sessão no banco: `abrir_sessao` no início da captura,
`fechar_captura` no fim dela e `completar_processamento` no fim do
processamento. Este arquivo testa os três separadamente — a ligação com
`capture/session.py` é entrega de T-04.

Nenhum teste grava banco dentro do repositório: tudo acontece em `tmp_path`.
"""

from datetime import datetime, timezone

import pytest

from auto_counter.capture.status import StatusDaSessao
from auto_counter.storage.connection import conectar
from auto_counter.storage.sessions import (
    SessaoInexistenteError,
    abrir_sessao,
    completar_processamento,
    fechar_captura,
    ler_sessao,
)

ID_SESSAO = "000013-20260101T080000Z"
ID_CAMERA = "000013"
CRIADA_EM = datetime(2026, 1, 1, 8, 0, 0, tzinfo=timezone.utc)
INICIO = datetime(2026, 1, 1, 8, 0, 3, tzinfo=timezone.utc)
FIM = datetime(2026, 1, 1, 8, 4, 58, tzinfo=timezone.utc)


def _abrir(conexao, **kwargs) -> None:
    """Abre a sessão padrão dos testes, com os campos default de D-6."""
    parametros = dict(
        id_sessao=ID_SESSAO,
        id_camera=ID_CAMERA,
        criada_em=CRIADA_EM,
        duracao_pedida=5,
        sentido_a="Icaraí",
        sentido_b="Centro",
    )
    parametros.update(kwargs)
    abrir_sessao(conexao, **parametros)


def test_AC_008_1_a_sessao_persistida_tem_id_camera_periodo_e_duracoes(tmp_path):
    with conectar(tmp_path) as conexao:
        _abrir(conexao)
        fechar_captura(
            conexao,
            ID_SESSAO,
            inicio=INICIO,
            fim=FIM,
            duracao_real=5,
            encerrada_pelo_usuario=False,
            status=StatusDaSessao.COMPLETA,
            minutos_perdidos=[],
        )

        sessao = ler_sessao(conexao, ID_SESSAO)

    assert sessao.id_sessao == ID_SESSAO
    assert sessao.id_camera == ID_CAMERA
    assert sessao.inicio == INICIO
    assert sessao.fim == FIM
    assert sessao.duracao_pedida == 5
    assert sessao.duracao_real == 5


def test_AC_008_1_a_sessao_persistida_registra_status_e_os_minutos_perdidos(tmp_path):
    with conectar(tmp_path) as conexao:
        _abrir(conexao)
        fechar_captura(
            conexao,
            ID_SESSAO,
            inicio=INICIO,
            fim=FIM,
            duracao_real=5,
            encerrada_pelo_usuario=False,
            status=StatusDaSessao.DEGRADADA,
            minutos_perdidos=[3, 5],
        )

        sessao = ler_sessao(conexao, ID_SESSAO)

    assert sessao.status is StatusDaSessao.DEGRADADA
    assert sessao.minutos_perdidos_quantidade == 2
    assert sessao.minutos_perdidos == (3, 5)


def test_AC_008_1_a_sessao_persistida_registra_encerramento_pelo_usuario(tmp_path):
    with conectar(tmp_path) as conexao:
        _abrir(conexao)
        fechar_captura(
            conexao,
            ID_SESSAO,
            inicio=INICIO,
            fim=FIM,
            duracao_real=3,
            encerrada_pelo_usuario=True,
            status=StatusDaSessao.COMPLETA,
            minutos_perdidos=[],
        )

        sessao = ler_sessao(conexao, ID_SESSAO)

    assert sessao.encerrada_pelo_usuario is True
    assert sessao.duracao_real == 3


def test_AC_008_1_a_sessao_persistida_registra_modelo_amostragem_e_limiar(tmp_path):
    with conectar(tmp_path) as conexao:
        _abrir(conexao)
        completar_processamento(
            conexao,
            ID_SESSAO,
            versao_do_modelo="yolo11n.onnx@abc123def456",
            amostragem=3,
            limiar_de_confianca=0.35,
        )

        sessao = ler_sessao(conexao, ID_SESSAO)

    assert sessao.versao_do_modelo == "yolo11n.onnx@abc123def456"
    assert sessao.amostragem == 3
    assert sessao.limiar_de_confianca == 0.35


def test_a_sessao_recem_aberta_tem_status_nulo_e_nao_um_quarto_status(tmp_path):
    """Status nulo = ainda em captura (momento 1 de D-1), não um quarto
    valor do vocabulário fechado de `StatusDaSessao`."""
    with conectar(tmp_path) as conexao:
        _abrir(conexao)
        sessao = ler_sessao(conexao, ID_SESSAO)

    assert sessao.status is None
    assert sessao.inicio is None
    assert sessao.fim is None
    assert sessao.duracao_real is None
    assert sessao.id_camera == ID_CAMERA
    assert sessao.duracao_pedida == 5


def test_abrir_sessao_duas_vezes_nao_apaga_o_que_ja_foi_fechado(tmp_path):
    """Idempotência de `abrir_sessao`: reabrir a mesma sessão não perde o
    que já foi gravado pelo momento 2 (`fechar_captura`)."""
    with conectar(tmp_path) as conexao:
        _abrir(conexao)
        fechar_captura(
            conexao,
            ID_SESSAO,
            inicio=INICIO,
            fim=FIM,
            duracao_real=5,
            encerrada_pelo_usuario=False,
            status=StatusDaSessao.COMPLETA,
            minutos_perdidos=[],
        )

        _abrir(conexao)  # reabertura acidental

        sessao = ler_sessao(conexao, ID_SESSAO)

    assert sessao.status is StatusDaSessao.COMPLETA
    assert sessao.duracao_real == 5


def test_instante_sem_fuso_e_recusado_na_gravacao(tmp_path):
    """Um `datetime` ingênuo não diz qual é o fuso dele (SUP-030)."""
    ingenuo = datetime(2026, 1, 1, 8, 0, 0)

    with conectar(tmp_path) as conexao:
        with pytest.raises(ValueError):
            abrir_sessao(
                conexao,
                id_sessao=ID_SESSAO,
                id_camera=ID_CAMERA,
                criada_em=ingenuo,
                duracao_pedida=5,
                sentido_a="Icaraí",
                sentido_b="Centro",
            )

        _abrir(conexao)
        with pytest.raises(ValueError):
            fechar_captura(
                conexao,
                ID_SESSAO,
                inicio=ingenuo,
                fim=FIM,
                duracao_real=5,
                encerrada_pelo_usuario=False,
                status=StatusDaSessao.COMPLETA,
                minutos_perdidos=[],
            )


def test_fechar_captura_de_sessao_inexistente_erra_citando_o_id(tmp_path):
    with conectar(tmp_path) as conexao:
        with pytest.raises(SessaoInexistenteError, match=ID_SESSAO):
            fechar_captura(
                conexao,
                ID_SESSAO,
                inicio=INICIO,
                fim=FIM,
                duracao_real=5,
                encerrada_pelo_usuario=False,
                status=StatusDaSessao.COMPLETA,
                minutos_perdidos=[],
            )


def test_completar_processamento_de_sessao_inexistente_erra_citando_o_id(tmp_path):
    with conectar(tmp_path) as conexao:
        with pytest.raises(SessaoInexistenteError, match=ID_SESSAO):
            completar_processamento(
                conexao,
                ID_SESSAO,
                versao_do_modelo="yolo11n.onnx@abc123def456",
                amostragem=3,
                limiar_de_confianca=0.35,
            )


def test_ler_sessao_inexistente_devolve_none(tmp_path):
    with conectar(tmp_path) as conexao:
        assert ler_sessao(conexao, "sessao-que-nao-existe") is None

"""A linha de sessão: abrir, fechar a captura, completar o processamento —
T-03.

Comportamento em `.spec/features/persistencia-resultados/spec.md`: AC-008.1 e
AC-008.6 (a marca de sessão cancelada pelo usuário).

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
    marcar_sessao_cancelada,
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


def test_AC_010_4_abrir_sessao_grava_o_nome_da_camera(tmp_path):
    with conectar(tmp_path) as conexao:
        _abrir(conexao, nome_camera="Av. Roberto Silveira")

        sessao = ler_sessao(conexao, ID_SESSAO)

    assert sessao.nome_camera == "Av. Roberto Silveira"


def test_abrir_sessao_sem_nome_da_camera_continua_funcionando(tmp_path):
    with conectar(tmp_path) as conexao:
        _abrir(conexao)

        sessao = ler_sessao(conexao, ID_SESSAO)

    assert sessao.nome_camera is None


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


# --- processamento-upload: origem e vídeos da sessão (SUP-096) ---

from auto_counter.storage.model import OrigemDaSessao, VideoGravado  # noqa: E402
from auto_counter.storage.sessions import gravar_videos  # noqa: E402


def _videos():
    return (
        VideoGravado(2, "segundo.mov", 45, "b" * 64, 4, 4),
        VideoGravado(1, "primeiro.mp4", 130, "a" * 64, 1, 3),
    )


def test_AC_030_1_videos_da_sessao_ida_e_volta_em_ordem_de_posicao(tmp_path):
    with conectar(tmp_path) as conexao:
        _abrir(conexao, origem=OrigemDaSessao.UPLOAD)
        gravar_videos(conexao, ID_SESSAO, _videos())

        sessao = ler_sessao(conexao, ID_SESSAO)

    assert sessao.origem is OrigemDaSessao.UPLOAD
    assert sessao.videos == (
        VideoGravado(1, "primeiro.mp4", 130, "a" * 64, 1, 3),
        VideoGravado(2, "segundo.mov", 45, "b" * 64, 4, 4),
    )


def test_AC_030_1_regravar_os_videos_nao_duplica(tmp_path):
    with conectar(tmp_path) as conexao:
        _abrir(conexao, origem=OrigemDaSessao.UPLOAD)
        gravar_videos(conexao, ID_SESSAO, _videos())
        gravar_videos(conexao, ID_SESSAO, _videos())

        sessao = ler_sessao(conexao, ID_SESSAO)

    assert len(sessao.videos) == 2


def test_AC_030_1_sessao_ao_vivo_tem_origem_camera_e_nenhum_video(tmp_path):
    with conectar(tmp_path) as conexao:
        _abrir(conexao)

        sessao = ler_sessao(conexao, ID_SESSAO)

    assert sessao.origem is OrigemDaSessao.CAMERA
    assert sessao.videos == ()


# --- AC-008.6: sessão cancelada pelo usuário na captura ---


def test_AC_008_6_marcar_sessao_cancelada_grava_a_marca_sem_eventos_nem_agregados(
    tmp_path,
):
    from auto_counter.storage.events import ler_eventos
    from auto_counter.storage.minutes import ler_agregados

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
        assert ler_sessao(conexao, ID_SESSAO).cancelada_pelo_usuario is False

        marcar_sessao_cancelada(conexao, ID_SESSAO)

        sessao = ler_sessao(conexao, ID_SESSAO)
        eventos = ler_eventos(conexao, ID_SESSAO)
        agregados = ler_agregados(conexao, ID_SESSAO)

    assert sessao.cancelada_pelo_usuario is True
    # A marca é campo próprio: o status continua um dos três de AC-004.4 a AC-004.6.
    assert sessao.status is StatusDaSessao.COMPLETA
    assert eventos == ()
    assert agregados == ()


def test_AC_008_6_marcar_sessao_inexistente_e_erro_explicito(tmp_path):
    with conectar(tmp_path) as conexao:
        with pytest.raises(SessaoInexistenteError, match="fantasma"):
            marcar_sessao_cancelada(conexao, "fantasma")


# --- AC-036.1: encerramento por servidor indisponível ---


def test_AC_036_1_fechar_captura_grava_a_marca_de_servidor_indisponivel(tmp_path):
    with conectar(tmp_path) as conexao:
        _abrir(conexao)
        fechar_captura(
            conexao,
            ID_SESSAO,
            inicio=None,
            fim=None,
            duracao_real=5,
            encerrada_pelo_usuario=False,
            status=StatusDaSessao.INVALIDA,
            minutos_perdidos=[1, 2, 3, 4, 5],
            encerrada_por_servidor_indisponivel=True,
        )

        sessao = ler_sessao(conexao, ID_SESSAO)

    assert sessao.encerrada_por_servidor_indisponivel is True
    assert sessao.encerrada_pelo_usuario is False


def test_AC_036_1_fechar_captura_sem_a_marca_grava_nao(tmp_path):
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

        assert ler_sessao(conexao, ID_SESSAO).encerrada_por_servidor_indisponivel is False

"""Comando `auto-counter session list` — T-10.

Comportamento em `.spec/features/persistencia-resultados/spec.md`: AC-009.1 e
AC-009.2, pela superfície de CLI (D-5 do `_tasks.md`).

Nenhum teste toca a rede: as sessões são gravadas diretamente no banco com as
funções de `storage.sessions`, porque este comando só lê o que já está lá —
não existe câmera para resolver, nem clipe para abrir.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

from auto_counter.capture.status import StatusDaSessao
from auto_counter.cli import app
from auto_counter.storage.connection import NOME_DO_ARQUIVO_DO_BANCO, conectar
from auto_counter.storage.model import OrigemDaSessao
from auto_counter.storage.sessions import (
    abrir_sessao,
    fechar_captura,
    marcar_sessao_cancelada,
)

ID_CAMERA = "000013"
SENTIDO_A = "Icaraí"
SENTIDO_B = "Centro"


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def data_dir(monkeypatch, tmp_path) -> Path:
    caminho = tmp_path / "data"
    monkeypatch.setenv("AUTO_COUNTER_DATA_DIR", str(caminho))
    return caminho


def _abrir_e_fechar(
    conexao,
    id_sessao: str,
    *,
    criada_em: datetime,
    status: StatusDaSessao = StatusDaSessao.COMPLETA,
) -> None:
    abrir_sessao(
        conexao,
        id_sessao=id_sessao,
        id_camera=ID_CAMERA,
        criada_em=criada_em,
        duracao_pedida=1,
        sentido_a=SENTIDO_A,
        sentido_b=SENTIDO_B,
    )
    fechar_captura(
        conexao,
        id_sessao,
        inicio=criada_em,
        fim=criada_em + timedelta(minutes=1),
        duracao_real=1,
        encerrada_pelo_usuario=False,
        status=status,
        minutos_perdidos=(),
    )


def test_AC_009_2_session_list_imprime_as_sessoes_da_mais_recente_para_a_mais_antiga(
    runner, data_dir
):
    base = datetime(2026, 1, 1, 8, 0, 0, tzinfo=timezone.utc)
    with conectar(data_dir) as conexao:
        _abrir_e_fechar(conexao, "antiga", criada_em=base)
        _abrir_e_fechar(conexao, "recente", criada_em=base + timedelta(minutes=10))
        conexao.commit()

    resultado = runner.invoke(app, ["session", "list"])

    assert resultado.exit_code == 0, resultado.output
    posicao_recente = resultado.output.find("recente")
    posicao_antiga = resultado.output.find("antiga")
    assert posicao_recente != -1 and posicao_antiga != -1
    assert posicao_recente < posicao_antiga


def test_AC_009_1_session_list_lista_sessao_cujos_videos_foram_apagados(
    runner, data_dir
):
    """O comando não sabe, e não precisa saber, se o diretório da sessão
    ainda existe — ele não é criado aqui de propósito."""
    with conectar(data_dir) as conexao:
        _abrir_e_fechar(
            conexao, "s1", criada_em=datetime(2026, 1, 1, 8, 0, 0, tzinfo=timezone.utc)
        )
        conexao.commit()

    assert not (data_dir / "sessions" / "s1").exists()

    resultado = runner.invoke(app, ["session", "list"])

    assert resultado.exit_code == 0, resultado.output
    assert "s1" in resultado.output
    assert ID_CAMERA in resultado.output
    assert StatusDaSessao.COMPLETA.value in resultado.output


def test_session_list_sem_banco_informa_historico_vazio_e_sai_com_codigo_zero(
    runner, data_dir
):
    assert not data_dir.exists()

    resultado = runner.invoke(app, ["session", "list"])

    assert resultado.exit_code == 0, resultado.output
    assert "Traceback" not in resultado.output
    assert str(data_dir / NOME_DO_ARQUIVO_DO_BANCO) in resultado.output
    # E a listagem não teve o efeito colateral de criar o banco sozinha.
    assert not (data_dir / NOME_DO_ARQUIVO_DO_BANCO).exists()


def test_session_list_com_banco_existente_mas_sem_sessao_informa_historico_vazio(
    runner, data_dir
):
    with conectar(data_dir):  # cria o banco, sem gravar nenhuma sessão
        pass

    resultado = runner.invoke(app, ["session", "list"])

    assert resultado.exit_code == 0, resultado.output
    assert "Traceback" not in resultado.output


def test_session_list_respeita_a_opcao_limit(runner, data_dir):
    base = datetime(2026, 1, 1, 8, 0, 0, tzinfo=timezone.utc)
    with conectar(data_dir) as conexao:
        for indice in range(3):
            _abrir_e_fechar(conexao, f"s{indice}", criada_em=base + timedelta(minutes=indice))
        conexao.commit()

    resultado = runner.invoke(app, ["session", "list", "--limit", "1"])

    assert resultado.exit_code == 0, resultado.output
    assert "s2" in resultado.output
    assert "s1" not in resultado.output
    assert "s0" not in resultado.output


def test_session_list_mostra_sessao_em_andamento_sem_status_inventado(runner, data_dir):
    with conectar(data_dir) as conexao:
        abrir_sessao(
            conexao,
            id_sessao="em-andamento",
            id_camera=ID_CAMERA,
            criada_em=datetime(2026, 1, 1, 8, 0, 0, tzinfo=timezone.utc),
            duracao_pedida=5,
            sentido_a=SENTIDO_A,
            sentido_b=SENTIDO_B,
        )

    resultado = runner.invoke(app, ["session", "list"])

    assert resultado.exit_code == 0, resultado.output
    assert "em-andamento" in resultado.output
    for status in StatusDaSessao:
        assert status.value not in resultado.output


def _abrir_com_origem(conexao, id_sessao: str, origem: OrigemDaSessao, criada_em: datetime):
    abrir_sessao(
        conexao,
        id_sessao=id_sessao,
        id_camera=ID_CAMERA,
        criada_em=criada_em,
        duracao_pedida=1,
        sentido_a=SENTIDO_A,
        sentido_b=SENTIDO_B,
        origem=origem,
    )
    fechar_captura(
        conexao,
        id_sessao,
        inicio=criada_em,
        fim=criada_em + timedelta(minutes=1),
        duracao_real=1,
        encerrada_pelo_usuario=False,
        status=StatusDaSessao.COMPLETA,
        minutos_perdidos=(),
    )


def _linha_da_sessao(saida: str, id_sessao: str) -> str:
    return next(linha for linha in saida.splitlines() if linha.startswith(id_sessao))


def test_AC_030_2_session_list_mostra_a_origem_de_cada_sessao(runner, data_dir):
    base = datetime(2026, 1, 1, 8, 0, 0, tzinfo=timezone.utc)
    with conectar(data_dir) as conexao:
        _abrir_com_origem(conexao, "sessao-camera", OrigemDaSessao.CAMERA, base)
        _abrir_com_origem(
            conexao, "sessao-upload", OrigemDaSessao.UPLOAD, base + timedelta(minutes=10)
        )
        conexao.commit()

    resultado = runner.invoke(app, ["session", "list"])

    assert resultado.exit_code == 0, resultado.output
    linha_camera = _linha_da_sessao(resultado.output, "sessao-camera")
    linha_upload = _linha_da_sessao(resultado.output, "sessao-upload")
    assert f"sessao-camera  CAMERA {ID_CAMERA}  " in linha_camera
    assert f"sessao-upload  UPLOAD {ID_CAMERA}  " in linha_upload


def test_AC_030_2_periodo_do_upload_marcado_como_horario_do_processamento(
    runner, data_dir
):
    base = datetime(2026, 1, 1, 8, 0, 0, tzinfo=timezone.utc)
    with conectar(data_dir) as conexao:
        _abrir_com_origem(conexao, "sessao-camera", OrigemDaSessao.CAMERA, base)
        _abrir_com_origem(
            conexao, "sessao-upload", OrigemDaSessao.UPLOAD, base + timedelta(minutes=10)
        )
        conexao.commit()

    resultado = runner.invoke(app, ["session", "list"])

    assert resultado.exit_code == 0, resultado.output
    marca = "(horário do processamento)"
    assert marca in _linha_da_sessao(resultado.output, "sessao-upload")
    assert marca not in _linha_da_sessao(resultado.output, "sessao-camera")


def test_AC_009_2_session_list_mostra_a_marca_da_sessao_cancelada(runner, data_dir):
    base = datetime(2026, 1, 1, 8, 0, 0, tzinfo=timezone.utc)
    with conectar(data_dir) as conexao:
        _abrir_e_fechar(conexao, "normal", criada_em=base)
        _abrir_e_fechar(conexao, "cancelada", criada_em=base + timedelta(minutes=10))
        marcar_sessao_cancelada(conexao, "cancelada")

    resultado = runner.invoke(app, ["session", "list"])

    assert resultado.exit_code == 0, resultado.output
    linhas = {
        linha.split()[0]: linha for linha in resultado.output.splitlines() if linha
    }
    assert "COMPLETA · cancelada pelo usuário" in linhas["cancelada"]
    assert "cancelada pelo usuário" not in linhas["normal"]

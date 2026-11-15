"""Comando `session capture` na CLI — T-10.

Critérios cobertos, de `.spec/features/captura-clipes/spec.md`:

- AC-003.3 — duração fora de 1..15 minutos é rejeitada com erro que cita o
  limite, **antes de qualquer requisição ao servidor**;
- AC-003.5 — a opção de manter os vídeos é explícita e vem desligada por padrão
  (SUP-012), e a decisão fica gravada no manifest, porque quem descarta é o
  encerramento da sessão, depois do processamento (T-09);
- AC-003.6 — o Ctrl+C é a parada explícita de T-08: a sessão encerra pela regra
  da duração real, com os minutos já capturados preservados e o manifest
  fechado.

Nenhum teste daqui toca a rede nem grava dentro do repositório: o registro de
câmeras é um diretório temporário montado a partir de `tests/fixtures/cameras/`,
`AUTO_COUNTER_DATA_DIR` aponta para `tmp_path` e o transporte HTTP é o dublê de
`tests.test_capture_session`. O relógio e a espera do comando também são
injetados (D-7) — uma sessão de 15 minutos com janela de 90 s não teria como ser
dirigida em tempo real.

O Ctrl+C é levantado de verdade, com `signal.raise_signal(SIGINT)` de dentro da
espera falsa, e não simulado chamando a parada na mão: o que T-10 exige é que o
sinal do terminal vire o encerramento explícito de AC-003.6, e um dublê que pula
o `signal` provaria outra coisa.
"""

import shutil
import signal
from pathlib import Path

import pytest
from typer.testing import CliRunner

from auto_counter.cameras.url import VARIAVEL_BASE_URL
from auto_counter.capture.manifest import ler
from auto_counter.capture.status import StatusDaSessao
from auto_counter.cli import app
from auto_counter.storage.connection import conectar
from auto_counter.storage.sessions import ler_sessao
from tests.test_capture_session import (  # noqa: F401  (dublês reusados de T-07)
    BASE_URL,
    DormirFalso,
    RelogioFalso,
    ServidorFalso,
    clipes_legiveis,
)

FIXTURES = Path(__file__).parent / "fixtures" / "cameras"


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def registro(tmp_path) -> Path:
    """Registro temporário com a câmera 000013 das fixtures."""
    destino = tmp_path / "cameras"
    destino.mkdir(exist_ok=True)
    shutil.copy(FIXTURES / "valida_000013.yaml", destino / "valida_000013.yaml")
    return destino


@pytest.fixture(autouse=True)
def ambiente(monkeypatch, tmp_path):
    """Base URL dublê e data dir dentro do `tmp_path` — nada no repositório."""
    monkeypatch.setenv(VARIAVEL_BASE_URL, BASE_URL)
    monkeypatch.setenv("AUTO_COUNTER_DATA_DIR", str(tmp_path / "data"))


@pytest.fixture
def sem_rede(monkeypatch):
    """Faz o comando explodir se ele construir cliente HTTP (AC-003.3)."""

    def proibido():
        raise AssertionError(
            "o comando construiu cliente HTTP antes de validar a duração"
        )

    monkeypatch.setattr("auto_counter.cli._cliente_http", proibido)


def liga_o_servidor(monkeypatch, servidor, relogio, dormir=None):
    """Injeta transporte, relógio e espera falsos no comando (D-7)."""
    monkeypatch.setattr("auto_counter.cli._cliente_http", servidor.cliente)
    monkeypatch.setattr("auto_counter.cli._agora", relogio.agora)
    monkeypatch.setattr("auto_counter.cli._dormir", dormir or DormirFalso(relogio))


def servidor_de_um_clipe_por_minuto(relogio, clipes_legiveis, minutos: int):
    """Publica um clipe novo a cada 60 s, sem falha nenhuma.

    Conteúdo próprio por minuto, e não só ETag novo: republicar o mesmo vídeo é
    recusado desde AC-004.7 e viraria minuto perdido.
    """
    publicacoes = [(60.0 * indice, f"clipe-{indice:02d}") for indice in range(minutos)]
    return ServidorFalso(
        relogio, publicacoes, clipes_legiveis(*[etag for _, etag in publicacoes])
    )


def dir_da_sessao(tmp_path) -> Path:
    """O único diretório de sessão criado pelo comando."""
    sessoes = sorted((tmp_path / "data" / "sessions").iterdir())
    assert len(sessoes) == 1, f"esperava uma sessão, e há {sessoes}"
    return sessoes[0]


class DormirQueInterrompe(DormirFalso):
    """Espera falsa que dispara um Ctrl+C de verdade no instante marcado.

    O sinal é levantado uma única vez: o segundo Ctrl+C aborta de verdade, e
    este teste é sobre o primeiro.
    """

    def __init__(self, relogio, segundo: float):
        super().__init__(relogio)
        self.segundo = segundo
        self.disparado = False

    def __call__(self, segundos: float) -> None:
        super().__call__(segundos)
        if not self.disparado and self.relogio.decorrido() >= self.segundo:
            self.disparado = True
            signal.raise_signal(signal.SIGINT)


@pytest.mark.parametrize("minutos", [0, -3, 16, 60])
def test_AC_003_3_session_capture_recusa_duracao_fora_do_intervalo_citando_o_limite(
    runner, registro, sem_rede, minutos
):
    resultado = runner.invoke(
        app,
        [
            "session",
            "capture",
            "000013",
            "--minutes",
            str(minutos),
            "--config-dir",
            str(registro),
        ],
    )

    assert resultado.exit_code != 0
    # A mensagem cita os dois limites e o valor recebido (AC-003.3).
    assert "1" in resultado.output and "15" in resultado.output
    assert str(minutos) in resultado.output
    assert "Traceback" not in resultado.output


def test_AC_003_3_duracao_invalida_e_recusada_antes_de_qualquer_requisicao(
    runner, registro, sem_rede, tmp_path
):
    # Id de câmera que nem existe no registro: se a mensagem falar da câmera, a
    # ordem está invertida — a duração tem de ser recusada antes de resolver a
    # câmera, montar a URL ou construir o cliente HTTP.
    resultado = runner.invoke(
        app,
        [
            "session",
            "capture",
            "000999",
            "--minutes",
            "99",
            "--config-dir",
            str(registro),
        ],
    )

    assert resultado.exit_code != 0
    assert "15" in resultado.output
    assert "000999" not in resultado.output
    # E nenhuma sessão chegou a existir em disco.
    assert not (tmp_path / "data" / "sessions").exists()


def test_AC_003_5_a_flag_de_preservar_videos_vem_desligada_por_padrao(
    runner, registro, monkeypatch, tmp_path, clipes_legiveis
):
    relogio = RelogioFalso()
    liga_o_servidor(
        monkeypatch,
        servidor_de_um_clipe_por_minuto(relogio, clipes_legiveis, 1),
        relogio,
    )

    resultado = runner.invoke(
        app,
        [
            "session",
            "capture",
            "000013",
            "--minutes",
            "1",
            "--config-dir",
            str(registro),
        ],
    )

    assert resultado.exit_code == 0, resultado.output
    sessao = dir_da_sessao(tmp_path)
    # A decisão de preservação fica no manifest, desligada por padrão (SUP-012).
    assert ler(sessao).manter_videos is False
    # E o comando de captura, sozinho, não apaga nada: quem descarta é o
    # encerramento da sessão, depois do processamento (T-09, AC-007.4).
    assert sorted(p.name for p in sessao.glob("*.mp4")) == ["minuto-01.mp4"]


def test_AC_003_5_a_flag_de_preservar_videos_ligada_fica_registrada_na_sessao(
    runner, registro, monkeypatch, tmp_path, clipes_legiveis
):
    relogio = RelogioFalso()
    liga_o_servidor(
        monkeypatch,
        servidor_de_um_clipe_por_minuto(relogio, clipes_legiveis, 1),
        relogio,
    )

    resultado = runner.invoke(
        app,
        [
            "session",
            "capture",
            "000013",
            "--minutes",
            "1",
            "--keep-clips",
            "--config-dir",
            str(registro),
        ],
    )

    assert resultado.exit_code == 0, resultado.output
    sessao = dir_da_sessao(tmp_path)
    assert ler(sessao).manter_videos is True
    assert sorted(p.name for p in sessao.glob("*.mp4")) == ["minuto-01.mp4"]


def test_AC_003_6_ctrl_c_encerra_a_sessao_pela_regra_de_duracao_real(
    runner, registro, monkeypatch, tmp_path, clipes_legiveis
):
    relogio = RelogioFalso()
    servidor = servidor_de_um_clipe_por_minuto(relogio, clipes_legiveis, minutos=15)
    # O minuto 7 é aceito em t=360; o Ctrl+C chega no meio da janela do minuto
    # 8, longe de qualquer publicação, para que o desfecho não seja ambíguo.
    liga_o_servidor(
        monkeypatch, servidor, relogio, dormir=DormirQueInterrompe(relogio, 380.0)
    )

    resultado = runner.invoke(
        app,
        [
            "session",
            "capture",
            "000013",
            "--minutes",
            "15",
            "--config-dir",
            str(registro),
        ],
    )

    # Ctrl+C não é erro nem traceback: a sessão encerra pela regra de AC-003.6 e
    # os minutos já capturados seguem para processamento.
    assert resultado.exit_code == 0, resultado.output
    assert "Traceback" not in resultado.output

    sessao = dir_da_sessao(tmp_path)
    gravado = ler(sessao)
    assert gravado.duracao_pedida == 15
    assert gravado.duracao_real == 7
    assert gravado.encerrada_pelo_usuario is True
    # Sem nenhuma perda, o status sai sobre a duração real: COMPLETA, e não
    # INVALIDA por "8 minutos perdidos" (SUP-013).
    assert gravado.status is StatusDaSessao.COMPLETA
    assert gravado.minutos_perdidos == ()
    assert len(gravado.minutos_capturados) == 7
    assert len(sorted(sessao.glob("*.mp4"))) == 7

    # E o relatório final mostra o que a sessão foi.
    assert gravado.id_sessao in resultado.output
    assert "COMPLETA" in resultado.output
    assert str(sessao) in resultado.output


def test_session_capture_grava_a_linha_da_sessao_no_banco(
    runner, registro, monkeypatch, tmp_path, clipes_legiveis
):
    """Ligação com `persistencia-resultados` (T-04 daquela feature): o
    comando `session capture` abre a linha da sessão no banco, não só no
    manifest."""
    relogio = RelogioFalso()
    liga_o_servidor(
        monkeypatch,
        servidor_de_um_clipe_por_minuto(relogio, clipes_legiveis, 1),
        relogio,
    )

    resultado = runner.invoke(
        app,
        [
            "session",
            "capture",
            "000013",
            "--minutes",
            "1",
            "--config-dir",
            str(registro),
        ],
    )

    assert resultado.exit_code == 0, resultado.output
    sessao = dir_da_sessao(tmp_path)
    gravado = ler(sessao)

    with conectar(tmp_path / "data") as conexao:
        sessao_no_banco = ler_sessao(conexao, gravado.id_sessao)

    assert sessao_no_banco is not None
    assert sessao_no_banco.id_camera == "000013"
    assert sessao_no_banco.duracao_pedida == 1
    assert sessao_no_banco.duracao_real == 1
    assert sessao_no_banco.status is StatusDaSessao.COMPLETA


# --- servidor-indisponivel: terminal (T-09, D-11, D-12) ---


def captura(runner, registro, minutos: int):
    return runner.invoke(
        app,
        [
            "session",
            "capture",
            "000013",
            "--minutes",
            str(minutos),
            "--config-dir",
            str(registro),
        ],
    )


def test_AC_035_4_session_capture_imprime_servidor_indisponivel_e_os_perdidos(
    runner, registro, monkeypatch, clipes_legiveis
):
    from tests.test_capture_session import servidor_que_cai_depois_do_minuto_3

    relogio = RelogioFalso()
    servidor = servidor_que_cai_depois_do_minuto_3(relogio, clipes_legiveis)
    liga_o_servidor(monkeypatch, servidor, relogio)

    resultado = captura(runner, registro, 5)

    # O código de saída é o do desfecho de sempre da captura: 0.
    assert resultado.exit_code == 0, resultado.output
    assert "Traceback" not in resultado.output
    # A primeira falha foi a checagem de t=103, e os perdidos são 4 e 5.
    assert (
        "Servidor indisponível desde 01:43 da sessão; minutos perdidos: 4, 5"
        in resultado.output
    )


def test_AC_035_4_session_capture_com_o_servidor_fora_desde_o_inicio_sai_com_zero(
    runner, registro, monkeypatch, clipes_legiveis
):
    from tests.test_capture_session import FORA_DO_AR, ServidorComFalhas

    relogio = RelogioFalso()
    servidor = ServidorComFalhas(
        relogio,
        [(0.0, "clipe-a")],
        clipes_legiveis("clipe-a"),
        indisponivel=[(0.0, FORA_DO_AR, "conexao")],
    )
    liga_o_servidor(monkeypatch, servidor, relogio)

    resultado = captura(runner, registro, 3)

    assert resultado.exit_code == 0, resultado.output
    assert (
        "Servidor indisponível desde 00:00 da sessão; minutos perdidos: 1, 2, 3"
        in resultado.output
    )


def test_AC_035_5_session_capture_sem_a_marca_nao_imprime_servidor_indisponivel(
    runner, registro, monkeypatch, clipes_legiveis
):
    from tests.test_capture_session import (
        FORA_DO_AR,
        QUEDA_DEPOIS_DO_MINUTO_3,
        servidor_que_cai_depois_do_minuto_3,
    )

    relogio = RelogioFalso()
    # Só o minuto 4 cai (N = 4): há um minuto com servidor indisponível, mas
    # nenhum encerramento, e o terminal não diz nada sobre servidor.
    servidor = servidor_que_cai_depois_do_minuto_3(
        relogio,
        clipes_legiveis,
        indisponivel=[(QUEDA_DEPOIS_DO_MINUTO_3, FORA_DO_AR, "conexao")],
    )
    liga_o_servidor(monkeypatch, servidor, relogio)

    resultado = captura(runner, registro, 4)

    assert resultado.exit_code == 0, resultado.output
    assert "servidor indisponível" not in resultado.output.lower()

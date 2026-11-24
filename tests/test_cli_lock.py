"""Trava de sessão única nos comandos `session capture` e `session process` — T-11.

Critérios cobertos, de `.spec/features/interface-sessao/spec.md`:

- AC-013.1 — uma segunda sessão é recusada com mensagem que informa a câmera e o
  horário de início da sessão em curso, e a sessão em andamento não é afetada;
- AC-013.2 — a trava órfã é ignorada e a nova sessão começa normalmente;
- SUP-052 — a trava vale para todo comando que baixa ou processa vídeo, e
  `session list` e `session export` ficam livres.

A "sessão em curso" é uma trava adquirida pelo próprio processo do teste, que
está vivo. Nada aqui toca a rede nem grava fora de `tmp_path`.
"""

import json
import subprocess
import sys
from datetime import datetime, timezone

import psutil

from auto_counter.cli import app
from auto_counter.pipeline.lock import NOME_DA_TRAVA, adquirir_trava
from tests.test_capture_session import (  # noqa: F401
    RelogioFalso,
    clipes_legiveis,
)
from tests.test_cli_process import (  # noqa: F401  (fixtures usadas por nome)
    data_dir,
    detector,
    modelo,
    monta_sessao,
    processa,
    registro,
    runner,
    videos,
)
from tests.test_cli_session import (  # noqa: F401  (fixtures usadas por nome)
    ambiente,
    liga_o_servidor,
    sem_rede,
    servidor_de_um_clipe_por_minuto,
)

INICIO_DA_OUTRA = datetime(2026, 9, 7, 11, 0, tzinfo=timezone.utc)


def sessao_em_curso(data_dir):
    """Uma sessão de outra câmera segurando a trava, com este processo vivo."""
    return adquirir_trava(
        data_dir,
        comando="run",
        id_camera="000042",
        nome_camera="Outro local",
        agora=lambda: INICIO_DA_OUTRA,
    )


def captura(runner, registro, minutos: int = 1):
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


def grava_trava_orfa(data_dir):
    filho = subprocess.Popen([sys.executable, "-c", "pass"])
    criado_em = psutil.Process(filho.pid).create_time()
    filho.wait()
    (data_dir / NOME_DA_TRAVA).write_text(
        json.dumps(
            {
                "pid": filho.pid,
                "criado_em_do_processo": criado_em,
                "comando": "run",
                "id_camera": "000042",
                "nome_camera": "Outro local",
                "iniciada_em": INICIO_DA_OUTRA.isoformat(),
            }
        ),
        encoding="utf-8",
    )


def test_AC_013_1_capture_com_sessao_em_andamento_e_recusado_sem_requisicao(
    runner, registro, sem_rede, data_dir
):
    with sessao_em_curso(data_dir):
        resultado = captura(runner, registro)

    # `sem_rede` explode se o comando construir o cliente HTTP: a recusa veio
    # antes de qualquer requisição.
    assert resultado.exit_code == 1
    assert "Traceback" not in resultado.output
    assert not (data_dir / "sessions").exists()


def test_AC_013_1_process_com_sessao_em_andamento_e_recusado(
    runner, registro, data_dir, modelo, detector
):
    dir_sessao = monta_sessao(data_dir)

    with sessao_em_curso(data_dir):
        resultado = processa(runner, registro)

    assert resultado.exit_code == 1
    assert "Traceback" not in resultado.output
    assert detector.chamadas == 0
    # Recusado, nada foi processado nem apagado.
    assert videos(dir_sessao) == ["minuto-01.mp4", "minuto-02.mp4"]
    assert not (dir_sessao / "eventos.json").exists()


def test_AC_013_1_a_recusa_cita_a_camera_e_o_horario_de_inicio(
    runner, registro, sem_rede, data_dir
):
    with sessao_em_curso(data_dir):
        resultado = captura(runner, registro)

    assert "Outro local" in resultado.output
    assert "000042" in resultado.output
    assert "07/09/2026 08:00" in resultado.output


def test_AC_013_1_a_recusa_nao_afeta_a_sessao_em_curso(
    runner, registro, sem_rede, data_dir
):
    with sessao_em_curso(data_dir):
        antes = (data_dir / NOME_DA_TRAVA).read_bytes()
        captura(runner, registro)

        assert (data_dir / NOME_DA_TRAVA).read_bytes() == antes


def test_AC_013_2_capture_com_trava_orfa_segue_normalmente(
    runner, registro, data_dir, monkeypatch, clipes_legiveis
):
    relogio = RelogioFalso()
    servidor = servidor_de_um_clipe_por_minuto(relogio, clipes_legiveis, 1)
    liga_o_servidor(monkeypatch, servidor, relogio)
    data_dir.mkdir(parents=True, exist_ok=True)
    grava_trava_orfa(data_dir)

    resultado = captura(runner, registro)

    assert resultado.exit_code == 0, resultado.output
    assert "COMPLETA" in resultado.output


def test_capture_libera_a_trava_ao_terminar(
    runner, registro, data_dir, monkeypatch, clipes_legiveis
):
    relogio = RelogioFalso()
    servidor = servidor_de_um_clipe_por_minuto(relogio, clipes_legiveis, 1)
    liga_o_servidor(monkeypatch, servidor, relogio)

    resultado = captura(runner, registro)

    assert resultado.exit_code == 0, resultado.output
    assert not (data_dir / NOME_DA_TRAVA).exists()


def test_process_libera_a_trava_ao_terminar(
    runner, registro, data_dir, modelo, detector
):
    monta_sessao(data_dir)

    resultado = processa(runner, registro)

    assert resultado.exit_code == 0, resultado.output
    assert not (data_dir / NOME_DA_TRAVA).exists()


def test_list_e_export_funcionam_com_a_trava_presa(runner, data_dir):
    with sessao_em_curso(data_dir):
        listagem = runner.invoke(app, ["session", "list"])
        exportacao = runner.invoke(app, ["session", "export", "000013-inexistente"])

    assert listagem.exit_code == 0, listagem.output
    # O export falha por não haver banco, e não por causa da trava.
    assert exportacao.exit_code == 1
    assert "já existe uma sessão em andamento" not in exportacao.output


def envio(runner, registro, arquivo):
    return runner.invoke(
        app,
        ["session", "upload", "000013", str(arquivo), "--config-dir", str(registro)],
    )


def test_AC_028_2_session_upload_recusado_com_sessao_em_andamento(
    runner, registro, data_dir, modelo, detector, tmp_path
):
    from tests.test_cli_session_upload import escreve_video

    video = escreve_video(tmp_path / "um.mp4")
    data_dir.mkdir(parents=True, exist_ok=True)
    estado_anterior = b'{"pid": 1, "fase": "CAPTURA"}'
    (data_dir / "sessao_atual.json").write_bytes(estado_anterior)

    with sessao_em_curso(data_dir):
        resultado = envio(runner, registro, video)

    assert resultado.exit_code == 1
    assert "Outro local" in resultado.output
    assert "07/09/2026 08:00" in resultado.output
    assert "Traceback" not in resultado.output
    # A sessão em andamento não é afetada, e nada do upload é tocado.
    assert (data_dir / "sessao_atual.json").read_bytes() == estado_anterior
    assert video.is_file()
    assert not (data_dir / "sessions").exists()
    assert detector.chamadas == 0


def test_AC_028_2_session_run_recusado_com_upload_em_andamento(
    runner, registro, data_dir, sem_rede
):
    data_dir.mkdir(parents=True, exist_ok=True)

    with adquirir_trava(
        data_dir,
        comando="upload",
        id_camera="000042",
        nome_camera="Outro local",
        agora=lambda: INICIO_DA_OUTRA,
    ):
        resultado = runner.invoke(
            app,
            ["session", "run", "000013", "--minutes", "1",
             "--config-dir", str(registro)],
        )

    assert resultado.exit_code == 1
    assert "Outro local" in resultado.output
    assert "Traceback" not in resultado.output

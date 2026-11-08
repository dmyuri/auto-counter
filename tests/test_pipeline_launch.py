"""Disparo da sessão em segundo plano — T-14.

Critérios cobertos, de `.spec/features/interface-sessao/spec.md`:

- AC-012.4 — a sessão é disparada num processo destacado de quem a disparou, com
  o mesmo diretório de dados, e só a ação explícita a encerra;
- AC-013.1 — com sessão em andamento, nada é disparado;
- AC-011.2 — duração fora de 1..15 não dispara nada.

O `Popen` é um dublê, exceto no teste de `python -m auto_counter --help`. Nada
aqui inicia uma sessão de verdade nem grava fora de `tmp_path`.
"""

import os
import subprocess
import sys
from datetime import datetime, timezone

import pytest

from auto_counter.capture.duration import DuracaoForaDoIntervaloError
from auto_counter.pipeline.ambiente import VARIAVEL_DATA_DIR
from auto_counter.pipeline.launch import (
    aguardar_inicio,
    encerrar_sessao,
    iniciar_sessao,
)
from auto_counter.pipeline.lock import OutraSessaoEmAndamentoError, adquirir_trava
from auto_counter.pipeline.state import AnotadorDoEstado
from auto_counter.pipeline.stop import NOME_DO_PEDIDO, pedir_parada

INICIO = datetime(2026, 9, 7, 11, 0, tzinfo=timezone.utc)


class PopenDuble:
    """Registra como o processo foi disparado e responde ao `poll`."""

    def __init__(self, codigo=None):
        self.chamadas = []
        self.codigo = codigo
        self.pid = 999

    def __call__(self, comando, **opcoes):
        self.chamadas.append((comando, opcoes))
        return self

    def poll(self):
        return self.codigo


def dispara(tmp_path, popen, minutos=3, id_camera="000013"):
    return iniciar_sessao(
        id_camera,
        minutos,
        data_dir=tmp_path,
        config_dir=tmp_path / "cameras",
        popen=popen,
    )


def trava_do_run(data_dir, id_camera="000013"):
    return adquirir_trava(
        data_dir,
        comando="run",
        id_camera=id_camera,
        nome_camera="Praça Exemplo",
        agora=lambda: INICIO,
    )


def test_AC_012_4_a_sessao_e_disparada_em_processo_destacado_da_interface(tmp_path):
    popen = PopenDuble()

    disparada = dispara(tmp_path, popen)

    (comando, opcoes), = popen.chamadas
    assert comando[:4] == [sys.executable, "-m", "auto_counter", "session"]
    assert comando[4:6] == ["run", "000013"]
    assert comando[6:8] == ["--minutes", "3"]
    if sys.platform == "win32":
        assert opcoes["creationflags"] & subprocess.DETACHED_PROCESS
        assert opcoes["creationflags"] & subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        assert opcoes["start_new_session"] is True
    assert opcoes["stdin"] == subprocess.DEVNULL
    assert opcoes["stderr"] == subprocess.STDOUT
    assert opcoes["stdout"].name == str(disparada.log)
    assert disparada.log.parent == tmp_path / "logs"
    assert disparada.log.name.startswith("run-")
    assert opcoes["env"]["PYTHONUTF8"] == "1"
    assert opcoes["env"]["PYTHONIOENCODING"] == "utf-8"


def test_AC_012_4_o_filho_recebe_o_mesmo_data_dir_da_interface(tmp_path, monkeypatch):
    monkeypatch.setenv(VARIAVEL_DATA_DIR, "outro/lugar")
    popen = PopenDuble()

    dispara(tmp_path, popen)

    _, opcoes = popen.chamadas[0]
    assert opcoes["env"][VARIAVEL_DATA_DIR] == str(tmp_path)


def test_o_filho_recebe_o_diretorio_de_configuracao(tmp_path):
    popen = PopenDuble()

    dispara(tmp_path, popen)

    comando, _ = popen.chamadas[0]
    indice = comando.index("--config-dir")
    assert comando[indice + 1] == str(tmp_path / "cameras")


def test_AC_013_1_com_sessao_em_andamento_nada_e_disparado(tmp_path):
    popen = PopenDuble()

    with trava_do_run(tmp_path):
        with pytest.raises(OutraSessaoEmAndamentoError) as recusa:
            dispara(tmp_path, popen)

    assert popen.chamadas == []
    assert "Praça Exemplo" in str(recusa.value)
    assert not (tmp_path / "logs").exists()


@pytest.mark.parametrize("minutos", [0, -1, 16])
def test_AC_011_2_duracao_fora_do_intervalo_nada_e_disparado(tmp_path, minutos):
    popen = PopenDuble()

    with pytest.raises(DuracaoForaDoIntervaloError):
        dispara(tmp_path, popen, minutos=minutos)

    assert popen.chamadas == []
    assert not (tmp_path / "logs").exists()


def test_AC_024_3_sem_a_opcao_o_comando_nao_pede_para_manter_os_videos(tmp_path):
    popen = PopenDuble()

    dispara(tmp_path, popen)

    comando, _ = popen.chamadas[0]
    assert "--keep-clips" not in comando


def test_AC_024_2_com_a_opcao_o_comando_pede_para_manter_os_videos(tmp_path):
    popen = PopenDuble()

    iniciar_sessao(
        "000013",
        3,
        data_dir=tmp_path,
        config_dir=tmp_path / "cameras",
        manter_videos=True,
        popen=popen,
    )

    comando, _ = popen.chamadas[0]
    assert comando[:4] == [sys.executable, "-m", "auto_counter", "session"]
    assert comando[4:6] == ["run", "000013"]
    assert "--minutes" in comando and "3" in comando
    assert "--config-dir" in comando
    assert "--keep-clips" in comando


def test_AC_024_2_a_opcao_vale_no_processo_destacado(tmp_path):
    popen = PopenDuble()

    disparada = iniciar_sessao(
        "000013",
        3,
        data_dir=tmp_path,
        config_dir=tmp_path / "cameras",
        manter_videos=True,
        popen=popen,
    )

    comando, opcoes = popen.chamadas[0]
    assert "--keep-clips" in comando
    if sys.platform == "win32":
        assert opcoes["creationflags"] & subprocess.DETACHED_PROCESS
        assert opcoes["creationflags"] & subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        assert opcoes["start_new_session"] is True
    assert opcoes["stdin"] == subprocess.DEVNULL
    assert opcoes["stdout"].name == str(disparada.log)


def test_pedido_de_parada_antigo_e_descartado_ao_disparar(tmp_path):
    pedir_parada(tmp_path)

    dispara(tmp_path, PopenDuble())

    assert not (tmp_path / NOME_DO_PEDIDO).exists()


def test_encerrar_sem_sessao_em_andamento_nao_cria_pedido(tmp_path):
    assert encerrar_sessao(tmp_path) is False
    assert not (tmp_path / NOME_DO_PEDIDO).exists()


def test_AC_012_4_encerrar_com_sessao_em_andamento_cria_o_pedido(tmp_path):
    AnotadorDoEstado(
        tmp_path,
        pid=os.getpid(),
        id_camera="000013",
        nome_camera="Praça Exemplo",
        duracao_pedida=3,
        iniciada_em=INICIO,
    ).iniciar()

    with trava_do_run(tmp_path):
        assert encerrar_sessao(tmp_path) is True

    assert (tmp_path / NOME_DO_PEDIDO).is_file()


def test_aguardar_inicio_devolve_none_quando_a_sessao_assume_a_trava(tmp_path):
    disparada = dispara(tmp_path, PopenDuble())

    with trava_do_run(tmp_path):
        assert aguardar_inicio(disparada, dormir=lambda s: None) is None


def test_aguardar_inicio_devolve_o_fim_do_log_quando_o_filho_falha(tmp_path):
    disparada = dispara(tmp_path, PopenDuble(codigo=1))
    disparada.log.write_text(
        "erro: o modelo não foi encontrado\n\n", encoding="utf-8"
    )

    mensagem = aguardar_inicio(disparada, dormir=lambda s: None)

    assert mensagem == "erro: o modelo não foi encontrado"


def test_aguardar_inicio_com_filho_mudo_cita_o_codigo_de_saida(tmp_path):
    disparada = dispara(tmp_path, PopenDuble(codigo=3))

    assert "código 3" in aguardar_inicio(disparada, dormir=lambda s: None)


def test_aguardar_inicio_desiste_no_limite_sem_travar(tmp_path):
    disparada = dispara(tmp_path, PopenDuble())
    relogio = iter([0.0, 1.0, 6.0, 7.0])

    mensagem = aguardar_inicio(
        disparada, limite=5.0, dormir=lambda s: None, relogio=lambda: next(relogio)
    )

    assert "não confirmou" in mensagem
    assert str(disparada.log) in mensagem


def test_python_m_auto_counter_responde_ao_help():
    # O mesmo ambiente que `iniciar_sessao` dá ao processo destacado: sem UTF-8
    # forçado, o help sai em cp1252 num pipe do Windows.
    ambiente = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    resultado = subprocess.run(
        [sys.executable, "-m", "auto_counter", "--help"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        env=ambiente,
    )

    assert resultado.returncode == 0, resultado.stderr
    assert "session" in resultado.stdout

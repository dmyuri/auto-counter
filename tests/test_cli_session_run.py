"""Comando `session run` na CLI — T-12.

Critérios cobertos, de `.spec/features/interface-sessao/spec.md`:

- AC-011.4 — a duração e a câmera válidas levam o pipeline da captura ao XLSX sem
  que a interface web seja iniciada;
- AC-013.1 e AC-013.2 — a segunda sessão é recusada sem tocar a sessão em curso, e
  a trava órfã é ignorada;
- AC-012.5 — Ctrl+C no processamento cancela a contagem e mantém os vídeos;
- AC-012.7 — a sessão cancelada na captura pela interface sai com código 0.

E, de `captura-clipes`, AC-003.6: Ctrl+C na captura segue para o processamento.

O Ctrl+C é levantado de verdade, com `signal.raise_signal(SIGINT)`, como em
`tests.test_cli_session`. Servidor, relógio e detector são dublês e nada aqui
toca a rede nem grava fora de `tmp_path`.
"""

import ast
import json
import signal
from pathlib import Path

import supervision as sv

import auto_counter.cli as cli
import auto_counter.pipeline as pacote_pipeline
from auto_counter.cli import app
from auto_counter.pipeline.lock import NOME_DA_TRAVA
from auto_counter.pipeline.state import NOME_DO_ESTADO
from auto_counter.pipeline.stop import pedir_parada
from tests.test_capture_session import (  # noqa: F401
    LIXO,
    RelogioFalso,
    ServidorFalso,
    clipes_legiveis,
)
from tests.test_cli_lock import grava_trava_orfa, sessao_em_curso
from tests.test_cli_process import (  # noqa: F401  (fixtures usadas por nome)
    DetectorDuble,
    data_dir,
    detector,
    modelo,
    registro,
    runner,
    videos,
)
from tests.test_cli_session import (  # noqa: F401  (fixtures usadas por nome)
    DormirFalso,
    DormirQueInterrompe,
    ambiente,
    liga_o_servidor,
    sem_rede,
    servidor_de_um_clipe_por_minuto,
)


def roda(runner, registro, minutos: int = 2, *extras: str):
    return runner.invoke(
        app,
        [
            "session",
            "run",
            "000013",
            "--minutes",
            str(minutos),
            "--config-dir",
            str(registro),
            *extras,
        ],
    )


def dir_da_sessao(data_dir) -> Path:
    sessoes = sorted((data_dir / "sessions").iterdir())
    assert len(sessoes) == 1, f"esperava uma sessão, e há {sessoes}"
    return sessoes[0]


class DetectorQueInterrompe(DetectorDuble):
    """Dispara o Ctrl+C no primeiro frame analisado: o clipe 1 já está rodando."""

    def __init__(self) -> None:
        super().__init__()
        self.disparado = False

    def detectar(self, frame):
        if not self.disparado:
            self.disparado = True
            signal.raise_signal(signal.SIGINT)
        return sv.Detections.empty()


def test_AC_011_4_session_run_vai_da_captura_ao_xlsx_sem_iniciar_a_interface(
    runner, registro, data_dir, modelo, detector, monkeypatch, clipes_legiveis
):
    relogio = RelogioFalso()
    servidor = servidor_de_um_clipe_por_minuto(relogio, clipes_legiveis, 2)
    liga_o_servidor(monkeypatch, servidor, relogio)

    resultado = roda(runner, registro)

    assert resultado.exit_code == 0, resultado.output
    xlsx = list(data_dir.glob("*.xlsx"))
    assert len(xlsx) == 1
    assert str(xlsx[0]) in resultado.output
    assert "COMPLETA" in resultado.output
    assert "Traceback" not in resultado.output
    # A sessão não deixa trava para trás, e os vídeos foram descartados.
    assert not (data_dir / NOME_DA_TRAVA).exists()
    assert videos(dir_da_sessao(data_dir)) == []


def test_AC_011_4_nem_a_cli_nem_o_pipeline_importam_streamlit():
    arquivos = [Path(cli.__file__), *Path(pacote_pipeline.__file__).parent.glob("*.py")]
    for arquivo in arquivos:
        arvore = ast.parse(arquivo.read_text(encoding="utf-8"))
        for no in ast.walk(arvore):
            nomes = []
            if isinstance(no, ast.Import):
                nomes = [alias.name for alias in no.names]
            elif isinstance(no, ast.ImportFrom):
                nomes = [no.module or ""]
            assert not any(
                nome == "streamlit" or nome.startswith("streamlit.") for nome in nomes
            ), f"{arquivo.name} importa o streamlit"


def test_AC_011_4_session_run_com_duracao_fora_do_intervalo_sai_sem_requisicao(
    runner, registro, sem_rede, data_dir
):
    resultado = roda(runner, registro, 16)

    assert resultado.exit_code == 1
    assert "15" in resultado.output
    assert not (data_dir / NOME_DO_ESTADO).exists()
    assert not (data_dir / NOME_DA_TRAVA).exists()


def test_AC_013_1_session_run_com_sessao_em_andamento_e_recusado_sem_tocar_o_estado(
    runner, registro, sem_rede, data_dir
):
    data_dir.mkdir(parents=True, exist_ok=True)
    estado_anterior = b'{"pid": 1, "fase": "CAPTURA"}'
    (data_dir / NOME_DO_ESTADO).write_bytes(estado_anterior)

    with sessao_em_curso(data_dir):
        resultado = roda(runner, registro)

    assert resultado.exit_code == 1
    assert "Outro local" in resultado.output
    assert "07/09/2026 08:00" in resultado.output
    # D-14: a recusa nunca sobrescreve o estado da sessão em curso.
    assert (data_dir / NOME_DO_ESTADO).read_bytes() == estado_anterior


def test_AC_013_2_session_run_com_trava_orfa_segue_normalmente(
    runner, registro, data_dir, modelo, detector, monkeypatch, clipes_legiveis
):
    relogio = RelogioFalso()
    servidor = servidor_de_um_clipe_por_minuto(relogio, clipes_legiveis, 2)
    liga_o_servidor(monkeypatch, servidor, relogio)
    data_dir.mkdir(parents=True, exist_ok=True)
    grava_trava_orfa(data_dir)

    resultado = roda(runner, registro)

    assert resultado.exit_code == 0, resultado.output
    assert len(list(data_dir.glob("*.xlsx"))) == 1


def test_AC_012_5_ctrl_c_no_processamento_cancela_e_mantem_os_videos(
    runner, registro, data_dir, modelo, monkeypatch, clipes_legiveis
):
    relogio = RelogioFalso()
    servidor = servidor_de_um_clipe_por_minuto(relogio, clipes_legiveis, 2)
    liga_o_servidor(monkeypatch, servidor, relogio)
    interrompe = DetectorQueInterrompe()
    monkeypatch.setattr(cli, "_detector", lambda caminho, config: interrompe)

    resultado = roda(runner, registro)

    assert resultado.exit_code == 0, resultado.output
    assert "cancelado" in resultado.output
    assert "session process" in resultado.output
    assert list(data_dir.glob("*.xlsx")) == []
    assert videos(dir_da_sessao(data_dir)) == ["minuto-01.mp4", "minuto-02.mp4"]


def test_AC_003_6_ctrl_c_na_captura_segue_para_o_processamento(
    runner, registro, data_dir, modelo, detector, monkeypatch, clipes_legiveis
):
    relogio = RelogioFalso()
    servidor = servidor_de_um_clipe_por_minuto(relogio, clipes_legiveis, 5)
    liga_o_servidor(
        monkeypatch, servidor, relogio, DormirQueInterrompe(relogio, segundo=80.0)
    )

    resultado = roda(runner, registro, 5)

    assert resultado.exit_code == 0, resultado.output
    assert detector.chamadas > 0
    xlsx = list(data_dir.glob("*.xlsx"))
    assert len(xlsx) == 1
    assert "_2min" in xlsx[0].name


def test_session_run_sem_planilha_sai_com_codigo_1_e_mensagem(
    runner, registro, data_dir, modelo, detector, monkeypatch
):
    relogio = RelogioFalso()
    servidor = ServidorFalso(
        relogio, [(0.0, "ruim-a"), (60.0, "ruim-b")], {"ruim-a": LIXO, "ruim-b": LIXO}
    )
    liga_o_servidor(monkeypatch, servidor, relogio)

    resultado = roda(runner, registro)

    assert resultado.exit_code == 1
    assert "INVALIDA" in resultado.output
    assert "não há planilha" in resultado.output
    assert "Traceback" not in resultado.output
    assert list(data_dir.glob("*.xlsx")) == []


def test_session_run_libera_a_trava_mesmo_quando_falha(
    runner, registro, data_dir, monkeypatch, clipes_legiveis
):
    relogio = RelogioFalso()
    servidor = servidor_de_um_clipe_por_minuto(relogio, clipes_legiveis, 2)
    liga_o_servidor(monkeypatch, servidor, relogio)

    # Sem o modelo no diretório de dados, a sessão falha antes de capturar.
    resultado = roda(runner, registro)

    assert resultado.exit_code == 1
    assert servidor.pedidos == []
    assert "Traceback" not in resultado.output
    assert not (data_dir / NOME_DA_TRAVA).exists()
    estado = json.loads((data_dir / NOME_DO_ESTADO).read_text(encoding="utf-8"))
    assert estado["fase"] == "FALHOU"


class DormirQueCriaOPedido(DormirFalso):
    """O clique em "Parar antecipadamente": grava o arquivo de pedido no instante."""

    def __init__(self, relogio, segundo: float, data_dir) -> None:
        super().__init__(relogio)
        self.segundo = segundo
        self._data_dir = data_dir

    def __call__(self, segundos: float) -> None:
        super().__call__(segundos)
        if self.relogio.decorrido() >= self.segundo:
            pedir_parada(self._data_dir)


def test_AC_012_7_session_run_cancelada_na_captura_sai_com_codigo_zero(
    runner, registro, data_dir, modelo, detector, monkeypatch, clipes_legiveis
):
    relogio = RelogioFalso()
    servidor = servidor_de_um_clipe_por_minuto(relogio, clipes_legiveis, 5)
    dormir = DormirQueCriaOPedido(relogio, 80.0, data_dir)
    liga_o_servidor(monkeypatch, servidor, relogio, dormir)

    resultado = roda(runner, registro, 5)

    assert resultado.exit_code == 0, resultado.output
    assert "Sessão cancelada pelo usuário" in resultado.output
    assert "Traceback" not in resultado.output
    assert detector.chamadas == 0
    assert list(data_dir.glob("*.xlsx")) == []
    assert videos(dir_da_sessao(data_dir)) == []
    assert not (data_dir / NOME_DA_TRAVA).exists()


# --- servidor-indisponivel: terminal (T-09, D-11, D-12) ---


def test_AC_035_4_session_run_com_planilha_imprime_a_linha_e_sai_com_zero(
    runner, registro, data_dir, modelo, detector, monkeypatch, clipes_legiveis
):
    from tests.test_capture_session import servidor_que_cai_depois_do_minuto_3

    relogio = RelogioFalso()
    servidor = servidor_que_cai_depois_do_minuto_3(relogio, clipes_legiveis)
    liga_o_servidor(monkeypatch, servidor, relogio)

    resultado = roda(runner, registro, 5)

    assert resultado.exit_code == 0, resultado.output
    assert len(list(data_dir.glob("*.xlsx"))) == 1
    assert (
        "Servidor indisponível desde 01:43 da sessão; minutos perdidos: 4, 5"
        in resultado.output
    )
    assert "Traceback" not in resultado.output


def test_AC_035_4_session_run_sem_planilha_imprime_a_linha_e_mantem_o_codigo(
    runner, registro, data_dir, modelo, detector, monkeypatch, clipes_legiveis
):
    from tests.test_capture_session import FORA_DO_AR, ServidorComFalhas

    relogio = RelogioFalso()
    servidor = ServidorComFalhas(
        relogio,
        [(0.0, "clipe-a")],
        clipes_legiveis("clipe-a"),
        indisponivel=[(0.0, FORA_DO_AR, "timeout")],
    )
    liga_o_servidor(monkeypatch, servidor, relogio)

    resultado = roda(runner, registro, 3)

    # O mesmo código de qualquer sessão sem planilha (`session run`): 1.
    assert resultado.exit_code == 1
    assert (
        "Servidor indisponível desde 00:00 da sessão; minutos perdidos: 1, 2, 3"
        in resultado.output
    )
    assert "não há planilha" in resultado.output
    assert list(data_dir.glob("*.xlsx")) == []


def test_AC_035_5_session_run_sem_a_marca_nao_imprime_servidor_indisponivel(
    runner, registro, data_dir, modelo, detector, monkeypatch, clipes_legiveis
):
    relogio = RelogioFalso()
    servidor = servidor_de_um_clipe_por_minuto(relogio, clipes_legiveis, 2)
    liga_o_servidor(monkeypatch, servidor, relogio)

    resultado = roda(runner, registro)

    assert resultado.exit_code == 0, resultado.output
    assert "servidor indisponível" not in resultado.output.lower()

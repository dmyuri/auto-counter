"""Comando `session process` na CLI e o descarte dos vídeos — T-13.

Critério coberto, de `.spec/features/captura-clipes/spec.md`:

- AC-003.5 — sessão cujo processamento terminou e que foi executada **sem** a
  opção de manter os vídeos não deixa nenhum arquivo de vídeo em disco; com a
  opção ativa, todos os clipes permanecem no diretório da sessão. O descarte é
  D-5 do `_tasks.md` de `contagem-veiculos`: acontece **depois** do
  processamento e **só** quando ele termina com sucesso — processamento que
  falha não apaga nada, porque a sessão ainda pode ser reprocessada.

Mais os dois erros tratados do comando, que nunca podem virar traceback
(`CLAUDE.md`): modelo ausente e sessão inexistente.

Nenhum teste daqui toca a rede, carrega o `.onnx` ou grava dentro do
repositório: o registro de câmeras é um diretório temporário montado a partir
de `tests/fixtures/cameras/`, `AUTO_COUNTER_DATA_DIR` aponta para `tmp_path`, o
modelo é um arquivo qualquer — só o hash do conteúdo dele é lido (SUP-027) — e
o detector é dublê (D-8), injetado por `_detector`.
"""

import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import cv2
import numpy as np
import pytest
import supervision as sv
from typer.testing import CliRunner

from auto_counter.capture.manifest import ManifestDaSessao, nome_do_arquivo_do_minuto
from auto_counter.capture.status import StatusDaSessao
from auto_counter.cli import app
from auto_counter.counting.events import NOME_DO_ARQUIVO_DE_EVENTOS
from auto_counter.counting.model import (
    NOME_DO_ARQUIVO_DO_MODELO,
    SUBDIRETORIO_DE_MODELOS,
)

FIXTURES = Path(__file__).parent / "fixtures" / "cameras"

ID_CAMERA = "000013"
ID_SESSAO = "000013-20260504T123000Z"
PRIMEIRO_LAST_MODIFIED = datetime(2026, 5, 4, 12, 30, 0, tzinfo=timezone.utc)

LARGURA = 128
ALTURA = 48
FPS = 30.0
QUADROS_POR_CLIPE = 6


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


@pytest.fixture
def data_dir(monkeypatch, tmp_path) -> Path:
    """Diretório de dados dentro do `tmp_path` — nada cai no repositório."""
    caminho = tmp_path / "data"
    monkeypatch.setenv("AUTO_COUNTER_DATA_DIR", str(caminho))
    return caminho


@pytest.fixture
def modelo(data_dir) -> Path:
    """Um `.onnx` de mentira: nada aqui carrega o modelo, só o hasheia."""
    caminho = data_dir / SUBDIRETORIO_DE_MODELOS / NOME_DO_ARQUIVO_DO_MODELO
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_bytes(b"onnx de mentira")
    return caminho


class DetectorDuble:
    """Dublê do detector (D-8): cena vazia em todo frame analisado.

    AC-003.5 é sobre o descarte dos vídeos depois do processamento, não sobre a
    contagem: um clipe sem ninguém em cena é processado do mesmo jeito, e a
    contagem em si já é verificada em T-09 a T-12.
    """

    def __init__(self) -> None:
        self.chamadas = 0

    def detectar(self, frame: np.ndarray) -> sv.Detections:
        self.chamadas += 1
        return sv.Detections.empty()


@pytest.fixture
def detector(monkeypatch) -> DetectorDuble:
    """Substitui a construção do detector real pelo dublê (D-8)."""
    duble = DetectorDuble()
    monkeypatch.setattr("auto_counter.cli._detector", lambda caminho, config: duble)
    return duble


def escreve_clipe(caminho: Path) -> Path:
    """Um MP4 válido e curto, como o de T-12."""
    escritor = cv2.VideoWriter(
        str(caminho), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (LARGURA, ALTURA)
    )
    assert escritor.isOpened(), (
        "o codec mp4v não está disponível nesta máquina e a fixture de vídeo "
        "válido não pôde ser gerada"
    )
    try:
        for _ in range(QUADROS_POR_CLIPE):
            escritor.write(np.zeros((ALTURA, LARGURA, 3), dtype=np.uint8))
    finally:
        escritor.release()
    assert caminho.exists() and caminho.stat().st_size > 0
    return caminho


def monta_sessao(
    data_dir: Path,
    *,
    minutos=(1, 2),
    manter_videos: bool = False,
    corrompidos=(),
) -> Path:
    """Cria o diretório da sessão com manifest e clipes, e devolve o caminho.

    `corrompidos` são minutos cujo `.mp4` existe mas não abre — o ramo de clipe
    ilegível de D-4, que é como esta suíte faz o processamento falhar sem
    apagar arquivo nenhum de propósito.
    """
    dir_sessao = data_dir / "sessions" / ID_SESSAO
    dir_sessao.mkdir(parents=True, exist_ok=True)
    manifest = ManifestDaSessao(
        dir_sessao,
        id_sessao=ID_SESSAO,
        id_camera=ID_CAMERA,
        duracao_pedida=max(minutos, default=0),
        status=StatusDaSessao.COMPLETA,
        manter_videos=manter_videos,
    )
    for minuto in sorted(minutos):
        manifest.registrar_minuto(
            minuto,
            etag=f"etag-{minuto}",
            last_modified=PRIMEIRO_LAST_MODIFIED + timedelta(minutes=minuto - 1),
            relogio_local=PRIMEIRO_LAST_MODIFIED + timedelta(minutes=minuto - 1),
        )
        caminho = dir_sessao / nome_do_arquivo_do_minuto(minuto)
        if minuto in corrompidos:
            caminho.write_bytes(b"isto nao e um video")
        else:
            escreve_clipe(caminho)
    manifest.gravar()
    return dir_sessao


def videos(dir_sessao: Path) -> list[str]:
    """Os arquivos de vídeo que restaram no diretório da sessão."""
    return sorted(caminho.name for caminho in dir_sessao.glob("*.mp4"))


def processa(runner: CliRunner, registro: Path, *extras: str):
    """Roda `session process` com o registro temporário do teste."""
    return runner.invoke(
        app,
        ["session", "process", ID_SESSAO, "--config-dir", str(registro), *extras],
    )


def test_AC_003_5_processamento_concluido_apaga_os_videos_da_sessao(
    runner, registro, data_dir, modelo, detector
):
    """Sem `manter_videos`, o sucesso do processamento leva os clipes embora.

    O `manifest.json` e o `eventos.json` continuam: o que AC-003.5 manda apagar
    é arquivo de vídeo, e é dos dois que `persistencia-resultados` vive depois
    que os `.mp4` somem.
    """
    dir_sessao = monta_sessao(data_dir)

    resultado = processa(runner, registro)

    assert resultado.exit_code == 0, resultado.output
    assert videos(dir_sessao) == []
    assert (dir_sessao / "manifest.json").is_file()
    assert (dir_sessao / NOME_DO_ARQUIVO_DE_EVENTOS).is_file()


def test_AC_003_5_sessao_com_manter_videos_preserva_os_clipes_apos_o_processamento(
    runner, registro, data_dir, modelo, detector
):
    """Com a opção ativa no manifest, **todos** os clipes permanecem."""
    dir_sessao = monta_sessao(data_dir, manter_videos=True)

    resultado = processa(runner, registro)

    assert resultado.exit_code == 0, resultado.output
    assert videos(dir_sessao) == ["minuto-01.mp4", "minuto-02.mp4"]
    assert (dir_sessao / NOME_DO_ARQUIVO_DE_EVENTOS).is_file()


def test_AC_003_5_processamento_que_falha_nao_apaga_nenhum_video(
    runner, registro, data_dir, modelo, detector
):
    """Nenhum clipe legível: a sessão falha (D-4) e nada é descartado.

    O descarte é irreversível e a sessão ainda pode ser reprocessada depois que
    a causa da falha for corrigida — apagar aqui destruiria o material.
    """
    dir_sessao = monta_sessao(data_dir, minutos=(1, 2), corrompidos=(1, 2))

    resultado = processa(runner, registro)

    assert resultado.exit_code == 1
    assert videos(dir_sessao) == ["minuto-01.mp4", "minuto-02.mp4"]
    assert not (dir_sessao / NOME_DO_ARQUIVO_DE_EVENTOS).exists()
    assert "Traceback" not in resultado.output


def test_session_process_sem_modelo_erra_citando_o_comando_de_export(
    runner, registro, data_dir, detector
):
    """Modelo ausente é erro tratado, com o caminho e o comando que o produz.

    E acontece **antes** de abrir qualquer vídeo: o detector não chega a ser
    consultado, e nenhum clipe é descartado.
    """
    dir_sessao = monta_sessao(data_dir)

    resultado = processa(runner, registro)

    assert resultado.exit_code == 1
    assert "auto-counter model export" in resultado.output
    assert NOME_DO_ARQUIVO_DO_MODELO in resultado.output
    assert detector.chamadas == 0
    assert videos(dir_sessao) == ["minuto-01.mp4", "minuto-02.mp4"]
    assert "Traceback" not in resultado.output


def test_session_process_em_sessao_inexistente_erra_citando_o_caminho(
    runner, registro, data_dir, modelo, detector
):
    """Sessão que não existe, ou diretório sem manifest, dizem onde se procurou."""
    resultado = processa(runner, registro)

    assert resultado.exit_code == 1
    assert ID_SESSAO in resultado.output
    assert "manifest.json" in resultado.output
    assert "Traceback" not in resultado.output

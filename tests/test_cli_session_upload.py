"""Comando `session upload` na CLI — T-14 de `processamento-upload`.

Critérios cobertos, de `.spec/features/processamento-upload/spec.md`:

- AC-030.7 — a câmera do registro e um ou mais vídeos válidos levam o pipeline
  até o XLSX sem que a interface web seja iniciada, e o arquivo inválido é
  recusado antes de qualquer processamento, com mensagem que nomeia o arquivo;
- SUP-098 — o comando não tem `--keep-clips`, e a duplicata avisa no terminal e
  é processada;
- D-13 — `--nome` em quantidade diferente da dos arquivos é erro, e a câmera
  inexistente é recusada antes da trava.

A trava de AC-028.2 está em `tests/test_cli_lock.py`. Os vídeos são gerados em
`tmp_path` e o detector é um dublê; nada aqui toca a rede nem grava fora de
`tmp_path`.
"""

import cv2
import numpy as np
import pytest

from auto_counter.cli import app
from auto_counter.pipeline.lock import NOME_DA_TRAVA
from auto_counter.pipeline.state import NOME_DO_ESTADO, Fase, ler_estado
from tests.test_cli_process import (  # noqa: F401  (fixtures usadas por nome)
    DetectorDuble,
    data_dir,
    detector,
    modelo,
    registro,
    runner,
)

RESOLUCAO_DA_CAMERA = (1280, 720)


def escreve_video(caminho, *, lado=RESOLUCAO_DA_CAMERA, quadros=10, fps=10, cor=0):
    largura, altura = lado
    escritor = cv2.VideoWriter(
        str(caminho), cv2.VideoWriter_fourcc(*"mp4v"), fps, (largura, altura)
    )
    assert escritor.isOpened()
    try:
        for indice in range(quadros):
            quadro = np.full((altura, largura, 3), cor, dtype=np.uint8)
            quadro[0, 0] = indice  # um conteúdo diferente por quadro
            escritor.write(quadro)
    finally:
        escritor.release()
    return caminho


def envia(runner, registro, *argumentos, camera="000013"):
    return runner.invoke(
        app,
        [
            "session",
            "upload",
            camera,
            *[str(a) for a in argumentos],
            "--config-dir",
            str(registro),
        ],
    )


@pytest.fixture
def sem_ui(monkeypatch):
    """Faz o teste falhar se o comando tentar subir a interface web."""

    def proibido(comando):
        raise AssertionError("session upload tentou iniciar a interface web")

    monkeypatch.setattr("auto_counter.cli._executar_ui", proibido)


@pytest.fixture
def detectores_criados(monkeypatch):
    """Registra cada detector construído; nenhum teste carrega o modelo real."""
    criados = []

    def fabrica(caminho, config):
        criados.append(caminho)
        return DetectorDuble()

    monkeypatch.setattr("auto_counter.cli._detector", fabrica)
    return criados


def test_AC_030_7_session_upload_roda_ate_o_xlsx_sem_a_interface(
    runner, registro, data_dir, modelo, detectores_criados, sem_ui, tmp_path
):
    um = escreve_video(tmp_path / "um.mp4", cor=10)
    dois = escreve_video(tmp_path / "dois.mp4", cor=20)

    resultado = envia(runner, registro, um, dois)

    assert resultado.exit_code == 0, resultado.output
    assert "Traceback" not in resultado.output
    planilhas = list(data_dir.glob("*.xlsx"))
    assert len(planilhas) == 1
    assert "_upload" in planilhas[0].name
    assert str(planilhas[0]) in resultado.output
    assert "Sessão:" in resultado.output
    assert "COMPLETA" in resultado.output
    assert ler_estado(data_dir).fase is Fase.CONCLUIDA
    assert not (data_dir / NOME_DA_TRAVA).exists()
    # SUP-097: o que o sistema apaga é a cópia; o original do usuário fica.
    assert um.is_file() and dois.is_file()
    assert list((data_dir / "sessions").rglob("video-*")) == []


def test_AC_030_7_arquivo_de_extensao_invalida_e_recusado_nomeando_o_arquivo(
    runner, registro, data_dir, modelo, detectores_criados, tmp_path
):
    texto = tmp_path / "relatorio.txt"
    texto.write_bytes(b"nao e video")

    resultado = envia(runner, registro, texto)

    assert resultado.exit_code != 0
    assert "relatorio.txt" in resultado.output
    assert "Traceback" not in resultado.output
    assert texto.is_file()


def test_AC_030_7_arquivo_invalido_nao_inicia_processamento(
    runner, registro, data_dir, modelo, detectores_criados, tmp_path
):
    bom = escreve_video(tmp_path / "bom.mp4")
    pequeno = escreve_video(tmp_path / "pequeno.mp4", lado=(640, 480))

    resultado = envia(runner, registro, bom, pequeno, "--nome", "bom.mp4",
                      "--nome", "meu-video.mp4")

    assert resultado.exit_code != 0
    assert "meu-video.mp4" in resultado.output
    assert "Traceback" not in resultado.output
    assert detectores_criados == []
    assert not (data_dir / "sessions").exists()
    assert not list(data_dir.glob("*.xlsx"))
    estado = ler_estado(data_dir)
    assert estado.fase is Fase.FALHOU
    assert "meu-video.mp4" in estado.mensagem
    assert not (data_dir / NOME_DA_TRAVA).exists()
    assert bom.is_file() and pequeno.is_file()


def test_SUP_098_duplicata_avisa_no_terminal_e_processa(
    runner, registro, data_dir, modelo, detectores_criados, tmp_path
):
    original = escreve_video(tmp_path / "original.mp4")
    copia = tmp_path / "copia.mp4"
    copia.write_bytes(original.read_bytes())

    resultado = envia(runner, registro, original, copia)

    assert resultado.exit_code == 0, resultado.output
    assert "copia.mp4" in resultado.output
    assert "Duplicata de original.mp4" in resultado.output
    assert len(list(data_dir.glob("*.xlsx"))) == 1


def test_SUP_098_session_upload_nao_tem_keep_clips(
    runner, registro, data_dir, modelo, detectores_criados, tmp_path
):
    video = escreve_video(tmp_path / "um.mp4")

    resultado = envia(runner, registro, video, "--keep-clips")

    assert resultado.exit_code != 0
    assert "keep-clips" in resultado.output
    assert detectores_criados == []
    assert not (data_dir / NOME_DO_ESTADO).exists()


def test_D_13_nomes_em_quantidade_diferente_dos_arquivos_e_erro(
    runner, registro, data_dir, modelo, detectores_criados, tmp_path
):
    um = escreve_video(tmp_path / "um.mp4", cor=10)
    dois = escreve_video(tmp_path / "dois.mp4", cor=20)

    resultado = envia(runner, registro, um, dois, "--nome", "so-um.mp4")

    assert resultado.exit_code != 0
    assert "--nome" in resultado.output
    assert "Traceback" not in resultado.output
    assert detectores_criados == []
    assert not (data_dir / NOME_DO_ESTADO).exists()
    assert not (data_dir / NOME_DA_TRAVA).exists()


def test_camera_inexistente_e_recusada_antes_da_trava(
    runner, registro, data_dir, modelo, detectores_criados, tmp_path, monkeypatch
):
    def proibida(*args, **kwargs):
        raise AssertionError("a trava foi pega antes de resolver a câmera")

    monkeypatch.setattr("auto_counter.cli._trava", proibida)
    video = escreve_video(tmp_path / "um.mp4")

    resultado = envia(runner, registro, video, camera="999999")

    assert resultado.exit_code != 0
    assert "999999" in resultado.output
    assert "Traceback" not in resultado.output
    assert not (data_dir / NOME_DO_ESTADO).exists()

"""Nomes de download, tamanho em MB e `.zip` dos clipes — download-clipes.

Critérios cobertos, de `.spec/features/download-clipes/spec.md`: AC-025.1
(formato do tamanho), AC-025.3 (nome do arquivo, SUP-077, D-3) e AC-025.4
(conteúdo do `.zip`, D-6).

Nada aqui toca a rede nem grava fora de `tmp_path`.
"""

import zipfile
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

import cv2
import numpy as np
import pytest

from auto_counter.capture.manifest import MinutoCapturado
from auto_counter.pipeline.clipes import (
    clipes_mantidos,
    duracao_em_segundos,
    formatar_megabytes,
    montar_zip,
    nomes_de_download,
)

ID_CAMERA = "000013"
LARGURA = 128
ALTURA = 48
FPS = 10.0


def escreve_clipe_de_3s(caminho: Path) -> Path:
    """Um `.mp4` válido de 3 s a 10 fps."""
    escritor = cv2.VideoWriter(
        str(caminho), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (LARGURA, ALTURA)
    )
    assert escritor.isOpened(), (
        "o codec mp4v não está disponível nesta máquina e a fixture de vídeo "
        "válido não pôde ser gerada"
    )
    try:
        for _ in range(int(FPS) * 3):
            escritor.write(np.zeros((ALTURA, LARGURA, 3), dtype=np.uint8))
    finally:
        escritor.release()
    assert caminho.exists() and caminho.stat().st_size > 0
    return caminho


def minuto_capturado(minuto: int, arquivo: str, last_modified: datetime) -> MinutoCapturado:
    return MinutoCapturado(
        minuto=minuto,
        arquivo=arquivo,
        etag=f"etag-{minuto}",
        last_modified=last_modified,
        relogio_local=last_modified,
    )


def test_AC_025_3_nome_usa_id_data_e_hora_de_brasilia():
    instante = datetime(2026, 11, 8, 11, 5, 30, tzinfo=timezone.utc)

    nomes = nomes_de_download(ID_CAMERA, [instante])

    assert nomes == ("000013_20261108_0805.mp4",)


def test_AC_025_3_virada_do_dia_em_utc_usa_a_data_de_brasilia():
    instante = datetime(2026, 11, 9, 1, 30, 0, tzinfo=timezone.utc)

    nomes = nomes_de_download(ID_CAMERA, [instante])

    assert nomes == ("000013_20261108_2230.mp4",)


def test_AC_025_3_mesmo_minuto_de_relogio_recebe_sufixo_2_e_3():
    minuto = datetime(2026, 11, 8, 11, 0, tzinfo=timezone.utc)
    instantes = [
        minuto,
        minuto + timedelta(seconds=10),
        minuto + timedelta(seconds=20),
        minuto + timedelta(minutes=1),
    ]

    nomes = nomes_de_download(ID_CAMERA, instantes)

    assert nomes == (
        "000013_20261108_0800.mp4",
        "000013_20261108_0800_2.mp4",
        "000013_20261108_0800_3.mp4",
        "000013_20261108_0801.mp4",
    )


def test_AC_025_4_nomes_nao_se_repetem():
    base = datetime(2026, 11, 8, 11, 0, tzinfo=timezone.utc)
    instantes = [
        base,
        base + timedelta(seconds=5),
        base + timedelta(minutes=1),
        base + timedelta(seconds=15),
        base + timedelta(minutes=1, seconds=5),
        base + timedelta(minutes=2),
    ]

    nomes = nomes_de_download(ID_CAMERA, instantes)

    assert len(nomes) == len(set(nomes))


def test_instante_sem_fuso_e_recusado():
    with pytest.raises(ValueError, match="fuso"):
        nomes_de_download(ID_CAMERA, [datetime(2026, 11, 8, 11, 0)])


@pytest.mark.parametrize(
    "tamanho_em_bytes, esperado",
    [
        (0, "0,0 MB"),
        (32_000_000, "32,0 MB"),
        (31_950_000, "32,0 MB"),
        (31_949_999, "31,9 MB"),
    ],
)
def test_AC_025_1_megabytes_com_uma_casa_e_virgula(tamanho_em_bytes, esperado):
    assert formatar_megabytes(tamanho_em_bytes) == esperado


def test_AC_025_4_zip_contem_exatamente_os_arquivos_com_os_nomes_e_bytes(tmp_path):
    arquivo_1 = tmp_path / "minuto-01.mp4"
    arquivo_1.write_bytes(b"conteudo-1" * 1000)
    arquivo_2 = tmp_path / "minuto-02.mp4"
    arquivo_2.write_bytes(b"conteudo-2" * 2000)

    bruto = montar_zip([(arquivo_1, "cam_20261108_0800.mp4"), (arquivo_2, "cam_20261108_0801.mp4")])

    with zipfile.ZipFile(BytesIO(bruto)) as zip_arquivo:
        nomes = zip_arquivo.namelist()
        assert nomes == ["cam_20261108_0800.mp4", "cam_20261108_0801.mp4"]
        assert zip_arquivo.read("cam_20261108_0800.mp4") == arquivo_1.read_bytes()
        assert zip_arquivo.read("cam_20261108_0801.mp4") == arquivo_2.read_bytes()


def test_AC_025_4_zip_nao_recomprime(tmp_path):
    arquivo = tmp_path / "minuto-01.mp4"
    arquivo.write_bytes(b"conteudo" * 500)

    bruto = montar_zip([(arquivo, "cam_20261108_0800.mp4")])

    with zipfile.ZipFile(BytesIO(bruto)) as zip_arquivo:
        for info in zip_arquivo.infolist():
            assert info.compress_type == zipfile.ZIP_STORED


# --- duração e lista dos clipes mantidos (T-03) ---


def test_AC_025_1_duracao_de_um_clipe_gerado(tmp_path):
    caminho = escreve_clipe_de_3s(tmp_path / "minuto-01.mp4")

    assert duracao_em_segundos(caminho) == 3


def test_AC_025_1_duracao_de_arquivo_que_nao_e_video_e_none(tmp_path):
    caminho = tmp_path / "minuto-01.mp4"
    caminho.write_bytes(b"isto nao e um video")

    assert duracao_em_segundos(caminho) is None


def test_AC_025_1_duracao_de_arquivo_inexistente_e_none(tmp_path):
    assert duracao_em_segundos(tmp_path / "nao-existe.mp4") is None


def test_AC_025_1_clipes_mantidos_saem_em_ordem_de_minuto(tmp_path):
    lm1 = datetime(2026, 11, 8, 11, 0, tzinfo=timezone.utc)
    lm2 = datetime(2026, 11, 8, 11, 1, tzinfo=timezone.utc)
    lm3 = datetime(2026, 11, 8, 11, 2, tzinfo=timezone.utc)
    minutos = [
        minuto_capturado(3, "minuto-03.mp4", lm3),
        minuto_capturado(1, "minuto-01.mp4", lm1),
        minuto_capturado(2, "minuto-02.mp4", lm2),
    ]

    clipes = clipes_mantidos(tmp_path, minutos, medir=lambda caminho: None)

    assert [c.minuto for c in clipes] == [1, 2, 3]
    assert clipes[0].caminho == (tmp_path / "minuto-01.mp4").resolve()
    assert clipes[0].last_modified == lm1


def test_AC_025_2_minutos_perdidos_nao_entram_na_lista(tmp_path):
    lm1 = datetime(2026, 11, 8, 11, 0, tzinfo=timezone.utc)
    lm2 = datetime(2026, 11, 8, 11, 1, tzinfo=timezone.utc)
    lm4 = datetime(2026, 11, 8, 11, 3, tzinfo=timezone.utc)
    minutos = [
        minuto_capturado(1, "minuto-01.mp4", lm1),
        minuto_capturado(2, "minuto-02.mp4", lm2),
        minuto_capturado(4, "minuto-04.mp4", lm4),
    ]

    clipes = clipes_mantidos(tmp_path, minutos, medir=lambda caminho: None)

    assert [c.minuto for c in clipes] == [1, 2, 4]

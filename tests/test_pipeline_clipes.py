"""Nomes de download, tamanho em MB e `.zip` dos clipes — download-clipes.

Critérios cobertos, de `.spec/features/download-clipes/spec.md`: AC-025.1
(formato do tamanho), AC-025.3 (nome do arquivo, SUP-077, D-3) e AC-025.4
(conteúdo do `.zip`, D-6).

Nada aqui toca a rede nem grava fora de `tmp_path`.
"""

import zipfile
from datetime import datetime, timedelta, timezone
from io import BytesIO

import pytest

from auto_counter.pipeline.clipes import (
    formatar_megabytes,
    montar_zip,
    nomes_de_download,
)

ID_CAMERA = "000013"


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

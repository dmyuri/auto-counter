"""Triagem, gravação e limpeza do envio de vídeos.

Critérios de `.spec/features/upload-videos/spec.md`, do lado da regra:
AC-027.1 (aceite por extensão e tamanho), AC-027.2 (extensão recusada),
AC-027.10 (limite de 1 GB em bytes), SUP-082 (gravação dentro do diretório de
dados), SUP-085 (nome igual não sobrescreve) e SUP-087 (limpeza dos órfãos).

Nada aqui aloca 1 GB: a triagem recebe o tamanho como número.
"""

import io

import pytest

from auto_counter.pipeline.envio import (
    EXTENSOES_ACEITAS,
    LIMITE_DE_BYTES,
    apagar_envios_orfaos,
    diretorio_de_envio,
    gravar_envio,
    triar,
)


@pytest.mark.parametrize("nome", ["a.mp4", "B.MOV", "c.Avi", "d.mkv"])
def test_AC_027_1_extensoes_aceitas_sem_diferenca_de_caixa(nome):
    assert triar(nome, 1234) is None


@pytest.mark.parametrize("nome", ["a.webm", "b.mp4.txt", "sem_extensao"])
def test_AC_027_2_outra_extensao_e_recusada_com_nome_e_as_quatro_extensoes(nome):
    mensagem = triar(nome, 1234)

    assert mensagem is not None
    assert nome in mensagem
    for extensao in (".mp4", ".mov", ".avi", ".mkv"):
        assert extensao in mensagem


def test_AC_027_10_exatamente_1_gb_e_aceito():
    assert LIMITE_DE_BYTES == 1_000_000_000
    assert triar("grande.mp4", 1_000_000_000) is None


def test_AC_027_10_um_byte_acima_de_1_gb_e_recusado_com_nome_e_limite():
    mensagem = triar("grande.mp4", 1_000_000_001)

    assert mensagem is not None
    assert "grande.mp4" in mensagem
    assert "1 GB" in mensagem


def test_extensao_e_conferida_antes_do_tamanho():
    mensagem = triar("grande.webm", 1_000_000_001)

    assert mensagem is not None
    assert "extensão" in mensagem
    assert "1 GB" not in mensagem


def test_extensoes_aceitas_sao_as_quatro_do_prototipo():
    assert EXTENSOES_ACEITAS == (".mp4", ".mov", ".avi", ".mkv")


def test_SUP_082_gravar_envio_grava_os_bytes_dentro_do_data_dir(tmp_path):
    data_dir = tmp_path / "data"
    conteudo = b"\x00\x01video" * 300_000  # mais de um pedaço de 1 MiB

    caminho = gravar_envio(data_dir, "Trecho.MP4", io.BytesIO(conteudo))

    assert caminho.is_absolute()
    assert caminho.parent == (data_dir / "envios").resolve()
    assert caminho.parent == diretorio_de_envio(data_dir).resolve()
    assert caminho.suffix == ".mp4"
    assert caminho.read_bytes() == conteudo


def test_SUP_085_dois_envios_de_mesmo_nome_nao_se_sobrescrevem(tmp_path):
    data_dir = tmp_path / "data"

    primeiro = gravar_envio(data_dir, "clipe.mp4", io.BytesIO(b"um"))
    segundo = gravar_envio(data_dir, "clipe.mp4", io.BytesIO(b"dois"))

    assert primeiro != segundo
    assert primeiro.read_bytes() == b"um"
    assert segundo.read_bytes() == b"dois"


def test_SUP_087_apagar_envios_orfaos_mantem_so_os_indicados(tmp_path):
    data_dir = tmp_path / "data"
    mantido = gravar_envio(data_dir, "a.mp4", io.BytesIO(b"a"))
    orfao = gravar_envio(data_dir, "b.mp4", io.BytesIO(b"b"))
    fora = data_dir / "banco.sqlite"
    fora.write_bytes(b"nao tocar")

    apagar_envios_orfaos(data_dir, [mantido])

    assert mantido.exists()
    assert not orfao.exists()
    assert fora.read_bytes() == b"nao tocar"


def test_SUP_087_apagar_envios_orfaos_sem_diretorio_nao_falha(tmp_path):
    apagar_envios_orfaos(tmp_path / "data", [])

    assert not (tmp_path / "data" / "envios").exists()

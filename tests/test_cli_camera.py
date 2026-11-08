"""Comandos `camera list` e `camera preview` na CLI — T-09.

Critérios cobertos, de `.spec/features/configuracao-camera/spec.md`:
AC-001.1 (a lista mostra exatamente as câmeras do registro, cada uma com id,
nome e os dois rótulos de sentido) e AC-002.1 (o preview grava o PNG com a
linha e os rótulos). Aparecem também os desfechos que a CLI herda de outros
critérios já implementados e que aqui só precisam virar mensagem legível e
código de saída: AC-001.3 (id duplicado derruba o registro inteiro) e
AC-002.2 (linha fora do frame não gera PNG).

Nenhum teste daqui toca a rede: o registro é um diretório temporário montado
a partir de `tests/fixtures/cameras/`, e o download do clipe (T-07) é
substituído por um dublê que devolve um frame sintético. Que o PNG mostra
mesmo a via da 000013 é conferido por olho humano em T-10.
"""

import shutil
from pathlib import Path

import cv2
import numpy as np
import pytest
from typer.testing import CliRunner

from auto_counter.cameras.frame import FrameDaCamera, FrameIndisponivelError
from auto_counter.cli import app

FIXTURES = Path(__file__).parent / "fixtures" / "cameras"

LARGURA_DO_FRAME = 1280
ALTURA_DO_FRAME = 720
CINZA_DE_FUNDO = 90


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def diretorio_com(tmp_path):
    """Monta um diretório de registro com os YAMLs de fixture pedidos."""

    def monta(*nomes: str) -> Path:
        destino = tmp_path / "cameras"
        destino.mkdir(exist_ok=True)
        for nome in nomes:
            shutil.copy(FIXTURES / nome, destino / nome)
        return destino

    return monta


@pytest.fixture
def frame_dublê(monkeypatch):
    """Substitui o download do clipe por um frame sintético (sem rede).

    Devolve a lista das câmeras para as quais o frame foi pedido, para que o
    teste possa provar que a rede nem foi cogitada quando não devia.
    """
    pedidos = []

    def monta(erro: Exception | None = None):
        def falso_primeiro_frame(camera, **_):
            pedidos.append(camera.id)
            if erro is not None:
                raise erro
            imagem = np.full(
                (ALTURA_DO_FRAME, LARGURA_DO_FRAME, 3), CINZA_DE_FUNDO, dtype=np.uint8
            )
            return FrameDaCamera(
                imagem=imagem, largura=LARGURA_DO_FRAME, altura=ALTURA_DO_FRAME
            )

        monkeypatch.setattr(
            "auto_counter.cli.primeiro_frame", falso_primeiro_frame
        )
        return pedidos

    return monta


def test_AC_001_1_camera_list_mostra_as_cameras_do_registro(
    runner, diretorio_com
):
    diretorio = diretorio_com("valida_000013.yaml", "valida_000042.yaml")

    resultado = runner.invoke(
        app, ["camera", "list", "--config-dir", str(diretorio)]
    )

    assert resultado.exit_code == 0, resultado.output
    # Cada câmera aparece com id, nome e os dois rótulos de sentido.
    for trecho in (
        "000013",
        "Via de teste - camera 13",
        "sentido A",
        "sentido B",
        "000042",
        "Via de teste - camera 42",
        "subindo",
        "descendo",
    ):
        assert trecho in resultado.output, f"'{trecho}' não apareceu na listagem"


def test_AC_001_1_camera_list_informa_as_rejeicoes_com_arquivo_e_motivo(
    runner, diretorio_com
):
    # Arquivo inválido é rejeição isolada (AC-001.2): a câmera válida continua
    # listada, e o motivo da recusa aparece junto com o nome do arquivo.
    diretorio = diretorio_com("valida_000013.yaml", "sem_linha.yaml")

    resultado = runner.invoke(
        app, ["camera", "list", "--config-dir", str(diretorio)]
    )

    assert resultado.exit_code == 0, resultado.output
    assert "000013" in resultado.output
    assert "sem_linha.yaml" in resultado.output
    assert "linha" in resultado.output


def test_AC_001_3_camera_list_falha_com_saida_nao_zero_quando_ha_id_duplicado(
    runner, diretorio_com
):
    diretorio = diretorio_com("valida_000013.yaml", "duplicada_000013.yaml")

    resultado = runner.invoke(
        app, ["camera", "list", "--config-dir", str(diretorio)]
    )

    assert resultado.exit_code != 0
    assert "000013" in resultado.output
    # Erro tratado vira mensagem legível, nunca traceback (CLAUDE.md).
    assert resultado.exception is None or isinstance(resultado.exception, SystemExit)
    assert "Traceback" not in resultado.output
    # Nenhuma câmera é disponibilizada quando o registro inteiro falha.
    assert "Via de teste - camera 13" not in resultado.output


def test_AC_002_1_camera_preview_grava_o_png_no_caminho_pedido(
    runner, diretorio_com, frame_dublê, tmp_path
):
    diretorio = diretorio_com("valida_000013.yaml")
    frame_dublê()
    destino = tmp_path / "saida" / "preview.png"

    resultado = runner.invoke(
        app,
        [
            "camera",
            "preview",
            "000013",
            "--config-dir",
            str(diretorio),
            "--out",
            str(destino),
        ],
    )

    assert resultado.exit_code == 0, resultado.output
    assert destino.exists(), "o PNG não foi gravado no caminho pedido"
    imagem = cv2.imread(str(destino))
    assert imagem is not None, "o arquivo gravado não é um PNG legível"
    assert imagem.shape == (ALTURA_DO_FRAME, LARGURA_DO_FRAME, 3)
    # A linha foi desenhada: há pixel diferente do fundo sintético.
    assert (imagem != CINZA_DE_FUNDO).any()
    assert str(destino) in resultado.output


def test_AC_002_1_camera_preview_sem_out_usa_o_caminho_padrao_no_data_dir(
    runner, diretorio_com, frame_dublê, tmp_path, monkeypatch
):
    # Padrão documentado: `<data_dir>/previews/<id>.png`, com o data dir vindo
    # de AUTO_COUNTER_DATA_DIR.
    diretorio = diretorio_com("valida_000013.yaml")
    frame_dublê()
    data_dir = tmp_path / "dados"
    monkeypatch.setenv("AUTO_COUNTER_DATA_DIR", str(data_dir))

    resultado = runner.invoke(
        app, ["camera", "preview", "000013", "--config-dir", str(diretorio)]
    )

    assert resultado.exit_code == 0, resultado.output
    esperado = data_dir / "previews" / "000013.png"
    assert esperado.exists(), f"o PNG não foi gravado em {esperado}"
    assert cv2.imread(str(esperado)) is not None


def test_AC_002_1_camera_preview_com_id_fora_do_registro_falha_sem_tocar_a_rede(
    runner, diretorio_com, frame_dublê, tmp_path
):
    diretorio = diretorio_com("valida_000013.yaml")
    pedidos = frame_dublê()

    resultado = runner.invoke(
        app, ["camera", "preview", "000999", "--config-dir", str(diretorio)]
    )

    assert resultado.exit_code != 0
    assert "000999" in resultado.output
    assert pedidos == [], "id inexistente não pode chegar a baixar clipe"
    assert "Traceback" not in resultado.output


def test_AC_002_1_camera_preview_com_falha_de_frame_vira_mensagem_e_saida_nao_zero(
    runner, diretorio_com, frame_dublê, tmp_path
):
    diretorio = diretorio_com("valida_000013.yaml")
    frame_dublê(FrameIndisponivelError("câmera 000013: o servidor respondeu 404"))
    destino = tmp_path / "preview.png"

    resultado = runner.invoke(
        app,
        [
            "camera",
            "preview",
            "000013",
            "--config-dir",
            str(diretorio),
            "--out",
            str(destino),
        ],
    )

    assert resultado.exit_code != 0
    assert "404" in resultado.output
    assert "Traceback" not in resultado.output
    assert not destino.exists()


def test_AC_002_2_camera_preview_com_linha_fora_do_frame_nao_gera_png(
    runner, diretorio_com, frame_dublê, tmp_path
):
    # A câmera 000042 tem p2.y = 700, válido em 1280x720; para provar a
    # rejeição, o frame devolvido é menor do que a linha calibrada.
    diretorio = diretorio_com("valida_000042.yaml")

    def frame_pequeno(camera, **_):
        imagem = np.full((240, 320, 3), CINZA_DE_FUNDO, dtype=np.uint8)
        return FrameDaCamera(imagem=imagem, largura=320, altura=240)

    import auto_counter.cli as cli_modulo

    original = cli_modulo.primeiro_frame
    cli_modulo.primeiro_frame = frame_pequeno
    destino = tmp_path / "preview.png"
    try:
        resultado = runner.invoke(
            app,
            [
                "camera",
                "preview",
                "000042",
                "--config-dir",
                str(diretorio),
                "--out",
                str(destino),
            ],
        )
    finally:
        cli_modulo.primeiro_frame = original

    assert resultado.exit_code != 0
    assert "320" in resultado.output and "240" in resultado.output
    assert not destino.exists(), "linha fora do frame não pode gerar PNG"
    assert "Traceback" not in resultado.output


def test_AC_031_5_camera_list_mostra_000012_e_000013_com_os_nomes(runner):
    """O registro versionado de verdade lista as duas câmeras, cada uma na sua linha."""
    diretorio = Path(__file__).resolve().parents[1] / "config" / "cameras"

    resultado = runner.invoke(
        app, ["camera", "list", "--config-dir", str(diretorio)]
    )

    assert resultado.exit_code == 0, resultado.output
    linhas = resultado.output.splitlines()
    linha_000012 = [l for l in linhas if "000012" in l]
    linha_000013 = [l for l in linhas if "000013" in l]
    assert len(linha_000012) == 1, resultado.output
    assert len(linha_000013) == 1, resultado.output
    assert "Praia x Mariz Barros" in linha_000012[0]
    assert "Praça Getúlio Vargas" in linha_000013[0]

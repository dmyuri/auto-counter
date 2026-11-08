"""Leitura da imagem de prévia da câmera — T-04 de `layout-interface`.

Critério coberto, de `.spec/features/layout-interface/spec.md`: AC-020.2 (o
cartão mostra a imagem indicada; sem campo, arquivo ausente ou que não abre, o
resultado é `None`, que a interface mostra como "sem prévia"; a câmera nunca é
acessada para obter a prévia). Origem do campo: SUP-066.

Nada aqui toca a rede nem grava fora de `tmp_path`. As imagens são geradas em
`tmp_path` com `cv2.imencode`.
"""

from pathlib import Path

import cv2
import httpx
import numpy as np

from auto_counter.cameras.model import Camera
from auto_counter.cameras.registry import carregar_registro
from auto_counter.pipeline.cameras import previa_da_camera

RAIZ = Path(__file__).resolve().parents[1]

CAMERA = {
    "id": "000013",
    "nome": "Camera de exemplo",
    "sentido_a": "sentido A",
    "sentido_b": "sentido B",
    "linha": {"p1": {"x": 120, "y": 400}, "p2": {"x": 1160, "y": 420}},
}


def camera_com(preview: str | None) -> Camera:
    return Camera(**CAMERA, preview=preview)


def png_em(caminho: Path) -> bytes:
    """Grava um PNG válido em `caminho` e devolve os bytes gravados."""
    imagem = np.full((12, 16, 3), 127, dtype=np.uint8)
    ok, codificada = cv2.imencode(".png", imagem)
    assert ok
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_bytes(codificada.tobytes())
    return caminho.read_bytes()


def test_AC_020_2_preview_que_abre_devolve_os_bytes_do_arquivo(tmp_path):
    gravados = png_em(tmp_path / "x.png")

    assert previa_da_camera(camera_com("x.png"), tmp_path) == gravados


def test_AC_020_2_sem_preview_devolve_none(tmp_path):
    assert previa_da_camera(camera_com(None), tmp_path) is None


def test_AC_020_2_preview_inexistente_devolve_none(tmp_path):
    assert previa_da_camera(camera_com("nao_existe.png"), tmp_path) is None


def test_AC_020_2_preview_que_nao_e_imagem_devolve_none(tmp_path):
    (tmp_path / "texto.png").write_bytes(b"isto nao e uma imagem")

    assert previa_da_camera(camera_com("texto.png"), tmp_path) is None


def test_AC_020_2_preview_que_e_diretorio_devolve_none(tmp_path):
    (tmp_path / "pasta.png").mkdir()

    assert previa_da_camera(camera_com("pasta.png"), tmp_path) is None


def test_AC_020_2_preview_e_resolvido_relativo_ao_diretorio_de_configuracao(tmp_path):
    config_dir = tmp_path / "config"
    gravados = png_em(config_dir / "previas" / "x.png")

    assert previa_da_camera(camera_com("previas/x.png"), config_dir) == gravados
    # O mesmo caminho relativo, a partir de outro diretório, não acha nada.
    assert previa_da_camera(camera_com("previas/x.png"), tmp_path) is None


def test_AC_020_2_previa_da_000013_do_registro_versionado_abre():
    diretorio = RAIZ / "config" / "cameras"
    registro = carregar_registro(diretorio)
    camera = {c.id: c for c in registro.cameras}["000013"]

    previa = previa_da_camera(camera, diretorio)

    assert previa is not None
    assert previa == (diretorio / camera.preview).read_bytes()


def test_AC_020_2_leitura_da_previa_nao_toca_a_rede(tmp_path, monkeypatch):
    def proibido(self, *args, **kwargs):
        raise AssertionError("a leitura da prévia não pode acessar a rede")

    monkeypatch.setattr(httpx.Client, "send", proibido)
    png_em(tmp_path / "x.png")

    assert previa_da_camera(camera_com("x.png"), tmp_path) is not None
    assert previa_da_camera(camera_com("nao_existe.png"), tmp_path) is None


def test_AC_032_2_previa_da_000012_do_registro_versionado_abre(monkeypatch):
    def proibido(self, *args, **kwargs):
        raise AssertionError("a leitura da prévia não pode acessar a rede")

    monkeypatch.setattr(httpx.Client, "send", proibido)
    diretorio = RAIZ / "config" / "cameras"
    registro = carregar_registro(diretorio)
    camera = {c.id: c for c in registro.cameras}["000012"]

    previa = previa_da_camera(camera, diretorio)

    assert previa is not None
    assert previa == (diretorio / camera.preview).read_bytes()

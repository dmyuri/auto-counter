"""Montagem da URL do clipe a partir da variável de ambiente — T-04.

Critérios cobertos, de `.spec/features/configuracao-camera/spec.md`:
AC-001.4 (a URL é `<base_url>/<id>/last_video.mp4`, com os zeros à esquerda do
id preservados) e AC-001.5 (sem a variável de ambiente da base URL a montagem
falha com erro explícito, e nenhuma URL embutida no código serve de padrão).

Nenhum teste aqui lê o `.env` real nem toca a rede: a variável é manipulada
com `monkeypatch`, e a montagem da URL acontece antes de qualquer requisição.
"""

import inspect
import re

import pytest

from auto_counter.cameras import url as modulo_url
from auto_counter.cameras.model import Camera
from auto_counter.cameras.url import (
    VARIAVEL_BASE_URL,
    BaseUrlAusenteError,
    url_do_clipe,
)


@pytest.fixture
def camera_000013() -> Camera:
    """A câmera do MVP, com id string de zeros à esquerda (SUP-001)."""
    return Camera(
        resolucao={"largura": 1280, "altura": 720},
        id="000013",
        nome="Local de teste",
        sentido_a="sentido A",
        sentido_b="sentido B",
        linha={"p1": {"x": 100, "y": 400}, "p2": {"x": 1180, "y": 400}},
    )


def test_AC_001_4_url_do_clipe_preserva_zeros_a_esquerda_do_id(
    monkeypatch, camera_000013
):
    monkeypatch.setenv(VARIAVEL_BASE_URL, "https://exemplo.invalido/videos")

    assert (
        url_do_clipe(camera_000013)
        == "https://exemplo.invalido/videos/000013/last_video.mp4"
    )


@pytest.mark.parametrize(
    "base",
    ["https://exemplo.invalido/videos/", "https://exemplo.invalido/videos///"],
)
def test_AC_001_4_barra_final_na_base_url_nao_gera_barra_dupla(
    monkeypatch, camera_000013, base
):
    monkeypatch.setenv(VARIAVEL_BASE_URL, base)

    assert (
        url_do_clipe(camera_000013)
        == "https://exemplo.invalido/videos/000013/last_video.mp4"
    )


@pytest.mark.parametrize("valor", [None, "", "   "])
def test_AC_001_5_base_url_ausente_falha_com_erro_explicito(
    monkeypatch, camera_000013, valor
):
    if valor is None:
        monkeypatch.delenv(VARIAVEL_BASE_URL, raising=False)
    else:
        monkeypatch.setenv(VARIAVEL_BASE_URL, valor)

    with pytest.raises(BaseUrlAusenteError) as erro:
        url_do_clipe(camera_000013)

    assert VARIAVEL_BASE_URL in str(erro.value)


def test_AC_001_5_nenhuma_url_padrao_embutida_no_codigo(monkeypatch, camera_000013):
    # Duas provas: o código-fonte do módulo não traz nenhuma URL literal, e sem
    # a variável de ambiente não sobra nada que possa servir de padrão.
    fonte = inspect.getsource(modulo_url)
    assert not re.search(r"https?://", fonte)

    monkeypatch.delenv(VARIAVEL_BASE_URL, raising=False)
    with pytest.raises(BaseUrlAusenteError):
        url_do_clipe(camera_000013)

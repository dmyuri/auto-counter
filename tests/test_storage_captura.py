"""Ligação entre `capture.capturar` e a linha de sessão no banco — T-04.

Comportamento em `.spec/features/persistencia-resultados/spec.md`: AC-008.1,
na parte de D-1 que `interface-sessao` (AC-012.4) depende — o registro de
sessão existe **desde o início da captura**, não só depois do processamento.

Reusa os dublês de `tests.test_capture_session` (relógio, espera e servidor
HTTP falsos): são os mesmos que provam `captura-clipes`, e duplicá-los aqui
testaria menos, não mais. Nenhum teste toca a rede nem grava banco dentro do
repositório — tudo em `tmp_path`.
"""

import sqlite3

import pytest

from auto_counter.cameras.url import VARIAVEL_BASE_URL
from auto_counter.capture.manifest import diretorio_da_sessao
from auto_counter.capture.manifest import ler as ler_manifest
from auto_counter.capture.session import capturar
from auto_counter.capture.status import StatusDaSessao
from auto_counter.storage.connection import NOME_DO_ARQUIVO_DO_BANCO, conectar
from auto_counter.storage.sessions import PersistenciaDaCaptura, ler_sessao
from tests.test_capture_session import (
    BASE_URL,
    ID_CAMERA,
    DormirFalso,
    RelogioFalso,
    ServidorFalso,
    camera,  # noqa: F401  (fixture reusada)
    clipes_legiveis,  # noqa: F401  (fixture reusada)
)


@pytest.fixture(autouse=True)
def base_url_no_ambiente(monkeypatch):
    """A URL vem de `cameras.url.url_do_clipe`, que lê o ambiente — mesma
    base dublê de `tests.test_capture_session`."""
    monkeypatch.setenv(VARIAVEL_BASE_URL, BASE_URL)


class _Espia:
    """Decora `PersistenciaDaCaptura`, registrando o estado do banco e do
    manifest **no instante exato** de cada chamada — é isso que prova a
    ordem exigida por D-1, e não só o estado final."""

    def __init__(self, real: PersistenciaDaCaptura, data_dir, conexao: sqlite3.Connection):
        self._real = real
        self._data_dir = data_dir
        self._conexao = conexao
        self.na_abertura: list[tuple[dict, tuple[int, ...], object]] = []
        self.no_fechamento: list[dict] = []

    def sessao_aberta(self, **kwargs) -> None:
        self._real.sessao_aberta(**kwargs)
        dir_sessao = diretorio_da_sessao(self._data_dir, kwargs["id_sessao"])
        minutos_ja_capturados = tuple(
            item.minuto for item in ler_manifest(dir_sessao).minutos_capturados
        )
        # A leitura é feita AGORA, dentro do próprio gancho — é o que prova o
        # estado "no instante da abertura", e não o estado final depois que
        # `capturar` já terminou a sessão inteira.
        sessao_no_momento = ler_sessao(self._conexao, kwargs["id_sessao"])
        self.na_abertura.append((dict(kwargs), minutos_ja_capturados, sessao_no_momento))

    def captura_fechada(self, **kwargs) -> None:
        self._real.captura_fechada(**kwargs)
        self.no_fechamento.append(dict(kwargs))


def test_AC_008_1_a_linha_da_sessao_existe_desde_o_inicio_da_captura(
    camera, tmp_path, clipes_legiveis
):
    """A linha nasce antes de qualquer minuto ser resolvido, e com status
    nulo — momento 1 de D-1, não o desfecho."""
    data_dir = tmp_path / "data"
    relogio = RelogioFalso()
    servidor = ServidorFalso(relogio, [(0.0, "clipe-a")], clipes_legiveis("clipe-a"))

    with conectar(data_dir) as conexao:
        espia = _Espia(PersistenciaDaCaptura(conexao, camera=camera), data_dir, conexao)

        capturar(
            camera,
            1,
            data_dir=data_dir,
            cliente=servidor.cliente(),
            agora=relogio.agora,
            dormir=DormirFalso(relogio),
            persistencia=espia,
        )

        assert len(espia.na_abertura) == 1
        kwargs, minutos_ja_capturados, sessao_no_momento = espia.na_abertura[0]

        # Nenhum minuto tinha sido capturado ainda quando a linha abriu.
        assert minutos_ja_capturados == ()
        assert kwargs["id_camera"] == ID_CAMERA
        assert kwargs["duracao_pedida"] == 1

        # E o registro já existia no banco, com status nulo — ainda em
        # captura, não o desfecho que só `fechar_captura` vai gravar depois.
        assert sessao_no_momento is not None
        assert sessao_no_momento.id_camera == ID_CAMERA
        assert sessao_no_momento.duracao_pedida == 1
        assert sessao_no_momento.status is None
        assert sessao_no_momento.duracao_real is None
        assert sessao_no_momento.sentido_a == camera.sentido_a
        assert sessao_no_momento.sentido_b == camera.sentido_b


def test_AC_010_4_a_captura_grava_o_nome_da_camera_na_sessao(
    camera, tmp_path, clipes_legiveis
):
    data_dir = tmp_path / "data"
    relogio = RelogioFalso()
    servidor = ServidorFalso(relogio, [(0.0, "clipe-a")], clipes_legiveis("clipe-a"))

    with conectar(data_dir) as conexao:
        capturar(
            camera,
            1,
            data_dir=data_dir,
            cliente=servidor.cliente(),
            agora=relogio.agora,
            dormir=DormirFalso(relogio),
            persistencia=PersistenciaDaCaptura(conexao, camera=camera),
        )
        id_sessao = conexao.execute("SELECT id_sessao FROM sessao").fetchone()[0]
        sessao = ler_sessao(conexao, id_sessao)

    assert sessao.nome_camera == camera.nome


def test_AC_008_1_o_fim_da_captura_grava_periodo_status_e_duracao_real(
    camera, tmp_path, clipes_legiveis
):
    data_dir = tmp_path / "data"
    relogio = RelogioFalso()
    servidor = ServidorFalso(
        relogio,
        [(0.0, "clipe-a"), (60.0, "clipe-b")],
        clipes_legiveis("clipe-a", "clipe-b"),
    )

    with conectar(data_dir) as conexao:
        persistencia = PersistenciaDaCaptura(conexao, camera=camera)

        resultado = capturar(
            camera,
            2,
            data_dir=data_dir,
            cliente=servidor.cliente(),
            agora=relogio.agora,
            dormir=DormirFalso(relogio),
            persistencia=persistencia,
        )

        sessao = ler_sessao(conexao, resultado.id_sessao)

    assert sessao.status is StatusDaSessao.COMPLETA
    assert sessao.duracao_real == resultado.duracao_real == 2
    assert sessao.inicio == resultado.inicio
    assert sessao.fim == resultado.fim
    assert sessao.encerrada_pelo_usuario is False
    assert sessao.minutos_perdidos == ()


def test_capturar_sem_observador_nao_toca_banco_nenhum(
    camera, tmp_path, clipes_legiveis
):
    """`persistencia=None` (o padrão) é D-2: nenhum arquivo de banco nasce."""
    data_dir = tmp_path / "data"
    relogio = RelogioFalso()
    servidor = ServidorFalso(relogio, [(0.0, "clipe-a")], clipes_legiveis("clipe-a"))

    capturar(
        camera,
        1,
        data_dir=data_dir,
        cliente=servidor.cliente(),
        agora=relogio.agora,
        dormir=DormirFalso(relogio),
    )

    assert not (data_dir / NOME_DO_ARQUIVO_DO_BANCO).exists()


def test_falha_de_banco_na_captura_avisa_mas_nao_interrompe_a_sessao(
    camera, tmp_path, clipes_legiveis
):
    """Um banco sem o schema aplicado faz `abrir_sessao`/`fechar_captura`
    falharem — e mesmo assim a sessão se completa normalmente (`CLAUDE.md`:
    falha de captura não pode virar exceção crua que derruba a execução)."""
    data_dir = tmp_path / "data"
    relogio = RelogioFalso()
    servidor = ServidorFalso(relogio, [(0.0, "clipe-a")], clipes_legiveis("clipe-a"))

    # Conexão deliberadamente sem migration aplicada: a tabela `sessao` não
    # existe, então qualquer INSERT/UPDATE nela falha.
    conexao_sem_schema = sqlite3.connect(":memory:")
    avisos: list[str] = []
    persistencia = PersistenciaDaCaptura(
        conexao_sem_schema, camera=camera, aviso=avisos.append
    )

    resultado = capturar(
        camera,
        1,
        data_dir=data_dir,
        cliente=servidor.cliente(),
        agora=relogio.agora,
        dormir=DormirFalso(relogio),
        persistencia=persistencia,
    )

    assert resultado.status is StatusDaSessao.COMPLETA
    assert sorted((data_dir / "sessions").glob("*/*.mp4"))  # o clipe foi gravado

    # Dois avisos: um de `sessao_aberta`, um de `captura_fechada`.
    assert len(avisos) == 2
    assert all("banco" in aviso for aviso in avisos)
    assert all(resultado.id_sessao in aviso for aviso in avisos)

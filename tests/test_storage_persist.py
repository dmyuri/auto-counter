"""Persistir a sessão inteira, de uma vez e sem duplicar — T-07.

Comportamento em `.spec/features/persistencia-resultados/spec.md`: AC-008.1
e AC-008.5.

Os arquivos de entrada (`manifest.json`, `eventos.json`) são construídos com
as classes reais de `captura-clipes` e `contagem-veiculos` — não dublês —
porque `persistir_sessao` lê exatamente o que aquelas features gravam.

Nenhum teste toca a rede nem grava banco dentro do repositório: tudo em
`tmp_path`.
"""

from datetime import datetime, timedelta, timezone

import pytest

from auto_counter.cameras.model import Camera
from auto_counter.capture.manifest import ManifestDaSessao, diretorio_da_sessao
from auto_counter.capture.status import classificar
from auto_counter.counting.config import Categoria, ConfiguracaoDoProcessamento
from auto_counter.counting.events import Evento, MinutoNaoProcessado, RegistroDeEventos
from auto_counter.storage.connection import conectar
from auto_counter.storage.events import contar_eventos
from auto_counter.storage.minutes import ler_agregados
from auto_counter.storage.persist import (
    EventosAusentesError,
    SessaoAindaEmCapturaError,
    persistir_sessao,
)
from auto_counter.storage.sessions import ler_sessao

ID_CAMERA = "000013"
ID_SESSAO = "000013-20260101T080000Z"
SENTIDO_A = "Icaraí"
SENTIDO_B = "Centro"

LAST_MODIFIED_BASE = datetime(2026, 1, 1, 7, 30, 0, tzinfo=timezone.utc)
VERSAO_DO_MODELO = "yolo11n.onnx@abc123def456"


def camera() -> Camera:
    return Camera(
        id=ID_CAMERA,
        nome="Praça Exemplo",
        sentido_a=SENTIDO_A,
        sentido_b=SENTIDO_B,
        linha={"p1": {"x": 0, "y": 360}, "p2": {"x": 1279, "y": 360}},
    )


def _evento(*, minuto: int, id_de_rastreio: str, sentido: str = SENTIDO_A) -> Evento:
    return Evento(
        timestamp=LAST_MODIFIED_BASE + timedelta(minutes=minuto, seconds=10),
        categoria=Categoria.CARRO,
        sentido=sentido,
        id_de_rastreio=id_de_rastreio,
        confianca=0.9,
        minuto=minuto,
        indice_do_frame=5,
        posicao_na_linha=0.5,
    )


def _criar_manifest_aberto(tmp_path, *, duracao_pedida: int, id_sessao: str = ID_SESSAO):
    """Cria o manifest com `duracao_pedida` minutos capturados, mas sem
    fechar a sessão (simula captura ainda em andamento)."""
    dir_sessao = diretorio_da_sessao(tmp_path, id_sessao)
    manifest = ManifestDaSessao.criar(
        dir_sessao,
        id_sessao=id_sessao,
        id_camera=ID_CAMERA,
        duracao_pedida=duracao_pedida,
    )
    for minuto in range(1, duracao_pedida + 1):
        manifest.registrar_minuto(
            minuto,
            etag=f"etag-{minuto}",
            last_modified=LAST_MODIFIED_BASE + timedelta(minutes=minuto),
            relogio_local=LAST_MODIFIED_BASE + timedelta(minutes=minuto),
        )
    return manifest, dir_sessao


def _criar_sessao_completa(
    tmp_path,
    *,
    id_sessao: str = ID_SESSAO,
    duracao_pedida: int = 2,
    eventos: tuple[Evento, ...] = (),
    minutos_processados: tuple[int, ...] | None = None,
    minutos_nao_processados: tuple[MinutoNaoProcessado, ...] = (),
):
    """Monta, em disco, manifest + eventos.json de uma sessão já concluída e
    processada — a entrada de verdade de `persistir_sessao`."""
    manifest, dir_sessao = _criar_manifest_aberto(
        tmp_path, duracao_pedida=duracao_pedida, id_sessao=id_sessao
    )
    resultado_status = classificar(duracao_pedida, [])
    manifest.fechar(resultado_status, duracao_real=duracao_pedida, encerrada_pelo_usuario=False)

    if minutos_processados is None:
        minutos_processados = tuple(range(1, duracao_pedida + 1))

    registro = RegistroDeEventos(
        id_sessao=id_sessao,
        id_camera=ID_CAMERA,
        configuracao=ConfiguracaoDoProcessamento(),
        versao_do_modelo=VERSAO_DO_MODELO,
        minutos_processados=minutos_processados,
        minutos_nao_processados=minutos_nao_processados,
        eventos=eventos,
    )
    registro.gravar(dir_sessao)

    return dir_sessao, manifest, registro


def _dump_das_tabelas(conexao, id_sessao: str) -> tuple:
    """Dump determinístico das três tabelas daquela sessão — para comparar
    "o resultado final é igual ao da primeira execução" de verdade."""
    sessao = ler_sessao(conexao, id_sessao)
    eventos = conexao.execute(
        "SELECT * FROM evento WHERE id_sessao = ? ORDER BY id_de_rastreio, sentido",
        (id_sessao,),
    ).fetchall()
    agregados = ler_agregados(conexao, id_sessao)
    return (
        sessao,
        tuple(tuple(linha) for linha in eventos),
        agregados,
    )


def test_AC_008_1_persistir_grava_a_sessao_com_todos_os_campos_do_manifest(tmp_path):
    eventos = (
        _evento(minuto=1, id_de_rastreio="1:1", sentido=SENTIDO_A),
        _evento(minuto=2, id_de_rastreio="2:1", sentido=SENTIDO_B),
    )
    dir_sessao, manifest, registro = _criar_sessao_completa(
        tmp_path, duracao_pedida=2, eventos=eventos
    )

    with conectar(tmp_path) as conexao:
        persistir_sessao(conexao, dir_sessao, camera=camera())
        sessao = ler_sessao(conexao, ID_SESSAO)

    assert sessao is not None
    assert sessao.id_camera == ID_CAMERA
    assert sessao.inicio == manifest.inicio
    assert sessao.fim == manifest.fim
    assert sessao.duracao_pedida == 2
    assert sessao.duracao_real == 2
    assert sessao.encerrada_pelo_usuario is False
    assert sessao.status is manifest.status
    assert sessao.minutos_perdidos_quantidade == 0
    assert sessao.minutos_perdidos == ()
    assert sessao.versao_do_modelo == VERSAO_DO_MODELO
    assert sessao.amostragem == registro.configuracao.amostragem
    assert sessao.limiar_de_confianca == registro.configuracao.limiar_de_confianca
    assert sessao.sentido_a == SENTIDO_A
    assert sessao.sentido_b == SENTIDO_B


def test_AC_008_5_persistir_a_mesma_sessao_duas_vezes_nao_duplica_eventos(tmp_path):
    eventos = (
        _evento(minuto=1, id_de_rastreio="1:1"),
        _evento(minuto=2, id_de_rastreio="2:1"),
    )
    dir_sessao, _, _ = _criar_sessao_completa(tmp_path, duracao_pedida=2, eventos=eventos)

    with conectar(tmp_path) as conexao:
        persistir_sessao(conexao, dir_sessao, camera=camera())
        persistir_sessao(conexao, dir_sessao, camera=camera())

        assert contar_eventos(conexao, ID_SESSAO) == 2


def test_AC_008_5_persistir_a_mesma_sessao_duas_vezes_nao_duplica_agregados(tmp_path):
    dir_sessao, _, _ = _criar_sessao_completa(tmp_path, duracao_pedida=3)

    with conectar(tmp_path) as conexao:
        persistir_sessao(conexao, dir_sessao, camera=camera())
        persistir_sessao(conexao, dir_sessao, camera=camera())

        assert len(ler_agregados(conexao, ID_SESSAO)) == 3


def test_AC_008_5_a_segunda_persistencia_produz_exatamente_o_mesmo_resultado(tmp_path):
    eventos = (
        _evento(minuto=1, id_de_rastreio="1:1", sentido=SENTIDO_A),
        _evento(minuto=1, id_de_rastreio="1:2", sentido=SENTIDO_B),
        _evento(minuto=2, id_de_rastreio="2:1", sentido=SENTIDO_A),
    )
    dir_sessao, _, _ = _criar_sessao_completa(tmp_path, duracao_pedida=2, eventos=eventos)

    with conectar(tmp_path) as conexao:
        persistir_sessao(conexao, dir_sessao, camera=camera())
        dump_depois_da_primeira = _dump_das_tabelas(conexao, ID_SESSAO)

        persistir_sessao(conexao, dir_sessao, camera=camera())
        dump_depois_da_segunda = _dump_das_tabelas(conexao, ID_SESSAO)

    assert dump_depois_da_segunda == dump_depois_da_primeira


def test_AC_008_5_reprocessamento_com_menos_eventos_nao_deixa_resto_da_primeira(tmp_path):
    eventos_da_primeira = (
        _evento(minuto=1, id_de_rastreio="1:1"),
        _evento(minuto=1, id_de_rastreio="1:2"),
        _evento(minuto=2, id_de_rastreio="2:1"),
    )
    dir_sessao, _, registro = _criar_sessao_completa(
        tmp_path, duracao_pedida=2, eventos=eventos_da_primeira
    )

    with conectar(tmp_path) as conexao:
        persistir_sessao(conexao, dir_sessao, camera=camera())
        assert contar_eventos(conexao, ID_SESSAO) == 3

        # "Reprocessamento" que resultou em menos eventos (ex.: limiar mais
        # estrito). Regrava o eventos.json por cima, com um evento só.
        registro_reduzido = RegistroDeEventos(
            id_sessao=registro.id_sessao,
            id_camera=registro.id_camera,
            configuracao=registro.configuracao,
            versao_do_modelo=registro.versao_do_modelo,
            minutos_processados=registro.minutos_processados,
            minutos_nao_processados=registro.minutos_nao_processados,
            eventos=(_evento(minuto=1, id_de_rastreio="1:1"),),
        )
        registro_reduzido.gravar(dir_sessao)

        persistir_sessao(conexao, dir_sessao, camera=camera())

        assert contar_eventos(conexao, ID_SESSAO) == 1


def test_falha_no_meio_da_persistencia_nao_deixa_sessao_meio_gravada(tmp_path, monkeypatch):
    eventos = (_evento(minuto=1, id_de_rastreio="1:1"),)
    dir_sessao, _, _ = _criar_sessao_completa(tmp_path, duracao_pedida=1, eventos=eventos)

    def _gravar_agregados_com_falha(*args, **kwargs):
        raise RuntimeError("falha simulada de gravação dos agregados")

    monkeypatch.setattr(
        "auto_counter.storage.persist.gravar_agregados", _gravar_agregados_com_falha
    )

    with conectar(tmp_path) as conexao:
        with pytest.raises(RuntimeError, match="falha simulada"):
            persistir_sessao(conexao, dir_sessao, camera=camera())

        # Nada da transação sobrou: nem a sessão, nem o evento que já tinha
        # sido gravado antes do ponto de falha.
        assert ler_sessao(conexao, ID_SESSAO) is None
        assert contar_eventos(conexao, ID_SESSAO) == 0
        assert len(ler_agregados(conexao, ID_SESSAO)) == 0


def test_sessao_ainda_em_captura_e_recusada_com_erro_explicito(tmp_path):
    _, dir_sessao = _criar_manifest_aberto(tmp_path, duracao_pedida=3)
    # Nenhum `manifest.fechar(...)`: a sessão ainda está em captura.

    with conectar(tmp_path) as conexao:
        with pytest.raises(SessaoAindaEmCapturaError, match=ID_SESSAO):
            persistir_sessao(conexao, dir_sessao, camera=camera())


def test_eventos_ausentes_e_erro_citando_o_caminho_e_pedindo_processamento(tmp_path):
    manifest, dir_sessao = _criar_manifest_aberto(tmp_path, duracao_pedida=1)
    resultado_status = classificar(1, [])
    manifest.fechar(resultado_status, duracao_real=1, encerrada_pelo_usuario=False)
    # Nenhum eventos.json: a sessão foi capturada, mas não processada ainda.

    with conectar(tmp_path) as conexao:
        with pytest.raises(EventosAusentesError, match="eventos.json"):
            persistir_sessao(conexao, dir_sessao, camera=camera())

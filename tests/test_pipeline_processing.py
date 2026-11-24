"""Processar, persistir e descartar fora da CLI — T-09.

Critérios cobertos, de `.spec/features/interface-sessao/spec.md`:

- AC-012.5 — encerrar no processamento cancela a contagem: nada é gravado no
  banco, os vídeos permanecem em disco e a sessão pode ser reprocessada;
- SUP-038 — a sequência de `session process` vive na camada de aplicação, e a
  ordem (persistir antes de descartar) continua a mesma.

Os dublês e a montagem de sessão são os de `tests.test_cli_process` e
`tests.test_counting_session`. Nada aqui toca a rede nem carrega o `.onnx`.
"""

import pytest

from auto_counter.counting.config import ConfiguracaoDoProcessamento
from auto_counter.counting.events import NOME_DO_ARQUIVO_DE_EVENTOS
from auto_counter.counting.model import ModeloAusenteError
from auto_counter.counting.session import ProcessamentoCancelado
from auto_counter.pipeline.processing import (
    PersistenciaFalhouError,
    conferir_modelo,
    persistir_e_descartar,
    processar,
)
from auto_counter.storage.connection import caminho_do_banco, conectar
from auto_counter.storage.events import contar_eventos
from auto_counter.storage.minutes import ler_agregados
from auto_counter.storage.sessions import ler_sessao
from auto_counter.pipeline.state import NOME_DO_ESTADO
from tests.test_cli_process import (  # noqa: F401  (fixtures usadas por nome)
    ID_SESSAO,
    DetectorDuble,
    data_dir,
    detector,
    modelo,
    monta_sessao,
    processa,
    registro,
    runner,
    videos,
)
from tests.test_counting_session import ParadaDuble, camera


def config() -> ConfiguracaoDoProcessamento:
    return ConfiguracaoDoProcessamento(amostragem=3)


def roda_processar(dir_sessao, **extra):
    return processar(
        dir_sessao,
        camera=camera(),
        detector=DetectorDuble(),
        config=config(),
        versao_do_modelo="yolo11n.onnx@0123456789ab",
        **extra,
    )


def test_AC_012_5_cancelamento_nao_grava_nada_no_banco(data_dir):
    dir_sessao = monta_sessao(data_dir)
    parada = ParadaDuble()
    parada.pedida = True

    with pytest.raises(ProcessamentoCancelado):
        roda_processar(dir_sessao, parada=parada)

    assert not caminho_do_banco(data_dir).exists()


def test_AC_012_5_cancelamento_mantem_os_videos_da_sessao(data_dir):
    dir_sessao = monta_sessao(data_dir)
    parada = ParadaDuble()

    def ao_resolver(minuto: int) -> None:
        parada.pedida = True

    with pytest.raises(ProcessamentoCancelado):
        roda_processar(dir_sessao, parada=parada, ao_resolver_minuto=ao_resolver)

    assert videos(dir_sessao) == ["minuto-01.mp4", "minuto-02.mp4"]
    assert (dir_sessao / "manifest.json").is_file()


def test_AC_012_5_cancelamento_apaga_o_eventos_json_parcial(data_dir):
    dir_sessao = monta_sessao(data_dir)
    parada = ParadaDuble()

    def ao_resolver(minuto: int) -> None:
        # O minuto 1 já gravou o `eventos.json`; a parada chega em seguida.
        assert (dir_sessao / NOME_DO_ARQUIVO_DE_EVENTOS).is_file()
        parada.pedida = True

    with pytest.raises(ProcessamentoCancelado):
        roda_processar(dir_sessao, parada=parada, ao_resolver_minuto=ao_resolver)

    assert not (dir_sessao / NOME_DO_ARQUIVO_DE_EVENTOS).exists()


def test_AC_012_5_sessao_cancelada_pode_ser_reprocessada_depois(data_dir):
    dir_sessao = monta_sessao(data_dir)
    parada = ParadaDuble()
    parada.pedida = True
    with pytest.raises(ProcessamentoCancelado):
        roda_processar(dir_sessao, parada=parada)

    resultado = roda_processar(dir_sessao)
    persistido = persistir_e_descartar(
        data_dir, dir_sessao, camera=camera(), manter_videos=False
    )

    assert resultado.minutos_processados == (1, 2)
    assert persistido.resumo.minutos_capturados == 2
    with conectar(data_dir) as conexao:
        assert ler_sessao(conexao, ID_SESSAO) is not None
        assert contar_eventos(conexao, ID_SESSAO) == 0
        assert len(ler_agregados(conexao, ID_SESSAO)) == 2


def test_processamento_com_sucesso_persiste_e_descarta_na_ordem_de_hoje(data_dir):
    dir_sessao = monta_sessao(data_dir)
    visto_na_persistencia = []

    def persistir_observando(conexao, dir_, *, camera):
        # No momento de gravar, os vídeos ainda estão lá (D-3).
        visto_na_persistencia.append(videos(dir_))
        from auto_counter.storage.persist import persistir_sessao

        return persistir_sessao(conexao, dir_, camera=camera)

    roda_processar(dir_sessao)
    persistido = persistir_e_descartar(
        data_dir,
        dir_sessao,
        camera=camera(),
        manter_videos=False,
        persistir=persistir_observando,
    )

    assert visto_na_persistencia == [["minuto-01.mp4", "minuto-02.mp4"]]
    assert videos(dir_sessao) == []
    assert persistido.videos_apagados == 2
    assert persistido.banco == caminho_do_banco(data_dir)


def test_manter_videos_preserva_os_clipes_e_informa_none(data_dir):
    dir_sessao = monta_sessao(data_dir, manter_videos=True)
    roda_processar(dir_sessao)

    persistido = persistir_e_descartar(
        data_dir, dir_sessao, camera=camera(), manter_videos=True
    )

    assert persistido.videos_apagados is None
    assert videos(dir_sessao) == ["minuto-01.mp4", "minuto-02.mp4"]


def test_falha_na_persistencia_nao_apaga_os_videos(data_dir):
    dir_sessao = monta_sessao(data_dir)
    roda_processar(dir_sessao)

    def com_falha(*args, **kwargs):
        raise RuntimeError("falha simulada de banco")

    with pytest.raises(PersistenciaFalhouError, match="falha simulada de banco"):
        persistir_e_descartar(
            data_dir,
            dir_sessao,
            camera=camera(),
            manter_videos=False,
            persistir=com_falha,
        )

    assert videos(dir_sessao) == ["minuto-01.mp4", "minuto-02.mp4"]


def test_conferir_modelo_devolve_o_caminho_e_a_versao(data_dir, modelo):
    caminho, versao = conferir_modelo(data_dir)

    assert caminho == modelo
    assert versao.startswith("yolo11n.onnx@")


def test_conferir_modelo_ausente_levanta_modelo_ausente(data_dir):
    with pytest.raises(ModeloAusenteError):
        conferir_modelo(data_dir)


def test_AC_016_2_processar_repassa_os_ganchos_a_processar_sessao(
    data_dir, monkeypatch
):
    recebidos = {}

    def espiao(dir_sessao, **kwargs):
        recebidos.update(kwargs)

    monkeypatch.setattr("auto_counter.pipeline.processing.processar_sessao", espiao)

    def aceitar(minuto, evento):
        pass

    def descartar(minuto):
        pass

    roda_processar(
        monta_sessao(data_dir),
        ao_aceitar_evento=aceitar,
        ao_descartar_minuto=descartar,
    )

    assert recebidos["ao_aceitar_evento"] is aceitar
    assert recebidos["ao_descartar_minuto"] is descartar


def test_AC_016_2_sem_ganchos_processar_nao_passa_nada(data_dir, monkeypatch):
    recebidos = {}

    def espiao(dir_sessao, **kwargs):
        recebidos.update(kwargs)

    monkeypatch.setattr("auto_counter.pipeline.processing.processar_sessao", espiao)

    roda_processar(monta_sessao(data_dir))

    assert recebidos["ao_aceitar_evento"] is None
    assert recebidos["ao_descartar_minuto"] is None


def test_session_process_continua_sem_anotar_quantidades(
    runner, registro, data_dir, modelo, detector
):
    """`session process` não passa ganchos: nenhum estado é gravado (Fora de escopo)."""
    monta_sessao(data_dir)

    resultado = processa(runner, registro)

    assert resultado.exit_code == 0, resultado.output
    assert not (data_dir / NOME_DO_ESTADO).exists()


def test_AC_022_6_processar_repassa_ao_iniciar_minuto_a_processar_sessao(
    data_dir, monkeypatch
):
    recebidos = {}

    def espiao(dir_sessao, **kwargs):
        recebidos.update(kwargs)

    monkeypatch.setattr("auto_counter.pipeline.processing.processar_sessao", espiao)

    def iniciar(minuto):
        pass

    roda_processar(monta_sessao(data_dir), ao_iniciar_minuto=iniciar)

    assert recebidos["ao_iniciar_minuto"] is iniciar


def test_AC_022_6_sem_o_gancho_processar_nao_passa_ao_iniciar_minuto(
    data_dir, monkeypatch
):
    recebidos = {}

    def espiao(dir_sessao, **kwargs):
        recebidos.update(kwargs)

    monkeypatch.setattr("auto_counter.pipeline.processing.processar_sessao", espiao)

    roda_processar(monta_sessao(data_dir))

    assert recebidos["ao_iniciar_minuto"] is None


def test_session_process_continua_sem_gravar_tm(
    runner, registro, data_dir, modelo, detector
):
    """`session process` não passa o gancho: o estado, com Tm, nunca é gravado."""
    monta_sessao(data_dir)

    resultado = processa(runner, registro)

    assert resultado.exit_code == 0, resultado.output
    assert not (data_dir / NOME_DO_ESTADO).exists()

"""Orquestração da sessão completa — T-10.

Critérios cobertos, de `.spec/features/interface-sessao/spec.md`:

- AC-011.4 — a sessão vai da captura ao XLSX sem a interface web;
- AC-012.1 e AC-012.2 — o estado acompanha cada minuto e a mudança de fase;
- AC-012.3 — o estado final traz o status gravado no banco e a planilha;
- AC-012.5 — encerrar no processamento termina cancelado, com os vídeos mantidos;
- AC-012.6 — sessão sem clipe processável termina sem planilha, com o status.

E, de `captura-clipes`, AC-003.6: encerrar na captura segue para o
processamento. Servidor, relógio, espera e detector são dublês; nada aqui toca a
rede nem grava fora de `tmp_path`.
"""

import pytest

from auto_counter.cameras.model import Camera
from auto_counter.capture.status import StatusDaSessao
from auto_counter.counting.model import ModeloAusenteError
from auto_counter.pipeline.run import executar_sessao
from auto_counter.pipeline.state import Fase, ler_estado
from auto_counter.pipeline.stop import (
    NOME_DO_PEDIDO,
    ParadaPorArquivo,
    pedir_parada,
)
from auto_counter.storage.connection import conectar
from auto_counter.storage.minutes import ler_agregados
from auto_counter.storage.sessions import ler_sessao
from tests.test_capture_interrupt import (
    ParadaFalsa,
    servidor_de_um_clipe_por_minuto,
)
from tests.test_capture_session import (  # noqa: F401  (fixtures usadas por nome)
    LIXO,
    DormirFalso,
    RelogioFalso,
    ServidorFalso,
    base_url_no_ambiente,
    clipes_legiveis,
)
from tests.test_cli_process import (  # noqa: F401  (fixtures usadas por nome)
    ID_CAMERA,
    DetectorDuble,
    data_dir,
    modelo,
    videos,
)
from tests.test_counting_session import ParadaDuble


def camera() -> Camera:
    """Câmera cuja linha cabe nos quadros 320x240 dos clipes dublê."""
    return Camera(
        id=ID_CAMERA,
        nome="Praça Renascença",
        sentido_a="CENTRO",
        sentido_b="ICARAI",
        linha={"p1": {"x": 0, "y": 120}, "p2": {"x": 319, "y": 120}},
    )


class ParadaNunca:
    def foi_pedida(self) -> bool:
        return False


class DormirObservador(DormirFalso):
    """Fotografa o estado da sessão a cada espera da captura."""

    def __init__(self, relogio, data_dir):
        super().__init__(relogio)
        self._data_dir = data_dir
        self.fotos = []

    def __call__(self, segundos: float) -> None:
        self.fotos.append(ler_estado(self._data_dir))
        super().__call__(segundos)


def executa(
    data_dir,
    servidor,
    relogio,
    *,
    minutos=2,
    dormir=None,
    criar_detector=None,
    criar_parada=None,
    manter_videos=False,
):
    detectores = []

    def detector_padrao(caminho, config):
        detectores.append(DetectorDuble())
        return detectores[-1]

    estado = executar_sessao(
        camera(),
        minutos,
        data_dir=data_dir,
        cliente=servidor.cliente(),
        agora=relogio.agora,
        dormir=dormir or DormirFalso(relogio),
        criar_detector=criar_detector or detector_padrao,
        criar_parada=criar_parada or ParadaNunca,
        manter_videos=manter_videos,
        pid=4242,
    )
    return estado, detectores


def dir_da_sessao(data_dir):
    sessoes = sorted((data_dir / "sessions").iterdir())
    assert len(sessoes) == 1
    return sessoes[0]


def test_AC_011_4_a_sessao_completa_termina_com_o_xlsx_no_diretorio_de_dados(
    data_dir, modelo, clipes_legiveis
):
    relogio = RelogioFalso()
    servidor = servidor_de_um_clipe_por_minuto(relogio, clipes_legiveis, 2)

    estado, _ = executa(data_dir, servidor, relogio)

    assert estado.fase is Fase.CONCLUIDA
    xlsx = list(data_dir.glob("*.xlsx"))
    assert len(xlsx) == 1
    assert estado.planilha == str(xlsx[0])
    assert xlsx[0].name.startswith("000013_")
    # Sem `--keep-clips`, os vídeos foram embora depois do processamento.
    assert videos(dir_da_sessao(data_dir)) == []


def test_AC_012_1_o_estado_acompanha_cada_minuto_capturado_ou_perdido(
    data_dir, modelo, clipes_legiveis
):
    relogio = RelogioFalso()
    # Minuto 2 perdido; o minuto 3 pega o clipe publicado em t=100.
    servidor = ServidorFalso(
        relogio,
        [(0.0, "clipe-a"), (100.0, "clipe-c")],
        clipes_legiveis("clipe-a", "clipe-c"),
    )
    dormir = DormirObservador(relogio, data_dir)

    estado, _ = executa(data_dir, servidor, relogio, minutos=3, dormir=dormir)

    # No meio da captura, o estado já mostrava o minuto 1 capturado.
    assert any(
        foto is not None
        and foto.fase is Fase.CAPTURA
        and foto.minutos_capturados == (1,)
        for foto in dormir.fotos
    )
    final = ler_estado(data_dir)
    assert final.minutos_capturados == (1, 3)
    assert final.minutos_perdidos == (2,)
    assert final.duracao_pedida == 3
    assert estado.fase is Fase.CONCLUIDA
    # 1 minuto perdido em 3 pedidos passa dos 20%: INVALIDA, e mesmo assim há planilha.
    assert estado.status == "INVALIDA"


def test_AC_012_2_o_estado_passa_de_captura_a_processamento(
    data_dir, modelo, clipes_legiveis
):
    relogio = RelogioFalso()
    servidor = servidor_de_um_clipe_por_minuto(relogio, clipes_legiveis, 2)
    visto = []

    def criar_detector(caminho, config):
        visto.append(ler_estado(data_dir))
        return DetectorDuble()

    estado, _ = executa(data_dir, servidor, relogio, criar_detector=criar_detector)

    assert visto[0].fase is Fase.PROCESSAMENTO
    assert visto[0].minutos_a_processar == 2
    assert visto[0].minutos_capturados == (1, 2)
    final = ler_estado(data_dir)
    assert final.minutos_processados == 2
    assert estado.fase is Fase.CONCLUIDA


def test_AC_012_3_o_estado_final_traz_o_status_do_banco_e_o_caminho_da_planilha(
    data_dir, modelo, clipes_legiveis
):
    relogio = RelogioFalso()
    servidor = servidor_de_um_clipe_por_minuto(relogio, clipes_legiveis, 2)

    estado, _ = executa(data_dir, servidor, relogio)

    with conectar(data_dir) as conexao:
        gravada = ler_sessao(conexao, estado.id_sessao)
    assert estado.status == gravada.status.value == "COMPLETA"
    assert estado.planilha.endswith(".xlsx")
    assert ler_estado(data_dir) == estado


def test_AC_003_6_encerrar_na_captura_nao_cancela_o_processamento(
    data_dir, modelo, clipes_legiveis
):
    relogio = RelogioFalso()
    servidor = servidor_de_um_clipe_por_minuto(relogio, clipes_legiveis, 5)
    # A parada chega no meio da janela do minuto 3: duração real 2.
    fabricas = iter([lambda: ParadaFalsa(relogio, segundo=80.0), ParadaNunca])

    estado, detectores = executa(
        data_dir,
        servidor,
        relogio,
        minutos=5,
        criar_parada=lambda: next(fabricas)(),
    )

    assert estado.fase is Fase.CONCLUIDA
    assert estado.minutos_capturados == (1, 2)
    assert detectores[0].chamadas > 0
    with conectar(data_dir) as conexao:
        gravada = ler_sessao(conexao, estado.id_sessao)
    assert gravada.duracao_real == 2
    assert gravada.encerrada_pelo_usuario is True


def test_AC_012_5_encerrar_no_processamento_termina_cancelado_com_videos_mantidos(
    data_dir, modelo, clipes_legiveis
):
    relogio = RelogioFalso()
    servidor = servidor_de_um_clipe_por_minuto(relogio, clipes_legiveis, 2)
    pedida = ParadaDuble()
    pedida.pedida = True
    fabricas = iter([ParadaNunca, lambda: pedida])

    estado, _ = executa(
        data_dir,
        servidor,
        relogio,
        criar_parada=lambda: next(fabricas)(),
    )

    assert estado.fase is Fase.PROCESSAMENTO_CANCELADO
    assert estado.planilha is None
    assert "session process" in estado.mensagem
    assert estado.id_sessao in estado.mensagem
    assert videos(dir_da_sessao(data_dir)) == ["minuto-01.mp4", "minuto-02.mp4"]
    assert list(data_dir.glob("*.xlsx")) == []
    with conectar(data_dir) as conexao:
        assert ler_agregados(conexao, estado.id_sessao) == ()


def test_AC_012_6_sessao_sem_minuto_capturado_termina_sem_planilha_com_status(
    data_dir, modelo, clipes_legiveis
):
    relogio = RelogioFalso()
    servidor = servidor_de_um_clipe_por_minuto(relogio, clipes_legiveis, 2)
    pedida = ParadaDuble()
    pedida.pedida = True

    estado, detectores = executa(
        data_dir, servidor, relogio, criar_parada=lambda: pedida
    )

    assert estado.fase is Fase.SEM_PLANILHA
    assert estado.status == StatusDaSessao.INVALIDA.value
    assert estado.planilha is None
    assert "não há planilha" in estado.mensagem
    assert detectores == []
    assert list(data_dir.glob("*.xlsx")) == []


def test_AC_012_6_sessao_com_todos_os_clipes_ilegiveis_termina_sem_planilha(
    data_dir, modelo
):
    relogio = RelogioFalso()
    servidor = ServidorFalso(
        relogio, [(0.0, "ruim-a"), (60.0, "ruim-b")], {"ruim-a": LIXO, "ruim-b": LIXO}
    )

    estado, detectores = executa(data_dir, servidor, relogio)

    assert estado.fase is Fase.SEM_PLANILHA
    assert estado.status == "INVALIDA"
    assert estado.minutos_perdidos == (1, 2)
    assert detectores == []


def test_AC_012_6_clipes_que_somem_antes_do_processamento_terminam_sem_planilha(
    data_dir, modelo, clipes_legiveis
):
    relogio = RelogioFalso()
    servidor = servidor_de_um_clipe_por_minuto(relogio, clipes_legiveis, 2)

    def criar_detector(caminho, config):
        for clipe in dir_da_sessao(data_dir).glob("*.mp4"):
            clipe.unlink()
        return DetectorDuble()

    estado, _ = executa(data_dir, servidor, relogio, criar_detector=criar_detector)

    assert estado.fase is Fase.SEM_PLANILHA
    assert estado.status == "COMPLETA"
    assert list(data_dir.glob("*.xlsx")) == []


def test_modelo_ausente_falha_antes_de_qualquer_requisicao(data_dir, clipes_legiveis):
    relogio = RelogioFalso()
    servidor = servidor_de_um_clipe_por_minuto(relogio, clipes_legiveis, 2)

    with pytest.raises(ModeloAusenteError):
        executa(data_dir, servidor, relogio)

    assert servidor.pedidos == []
    estado = ler_estado(data_dir)
    assert estado.fase is Fase.FALHOU
    assert estado.mensagem


def test_pedido_de_parada_antigo_nao_encerra_a_sessao_nova(
    data_dir, modelo, clipes_legiveis
):
    relogio = RelogioFalso()
    servidor = servidor_de_um_clipe_por_minuto(relogio, clipes_legiveis, 2)
    pedir_parada(data_dir)

    estado, _ = executa(
        data_dir,
        servidor,
        relogio,
        criar_parada=lambda: ParadaPorArquivo(data_dir),
    )

    assert estado.fase is Fase.CONCLUIDA
    assert estado.minutos_capturados == (1, 2)
    assert not (data_dir / NOME_DO_PEDIDO).exists()


def test_falha_inesperada_termina_o_estado_como_falhou_e_relevanta(
    data_dir, modelo, clipes_legiveis
):
    relogio = RelogioFalso()
    servidor = servidor_de_um_clipe_por_minuto(relogio, clipes_legiveis, 2)

    def criar_detector(caminho, config):
        raise RuntimeError("detector quebrou")

    with pytest.raises(RuntimeError, match="detector quebrou"):
        executa(data_dir, servidor, relogio, criar_detector=criar_detector)

    estado = ler_estado(data_dir)
    assert estado.fase is Fase.FALHOU
    assert "detector quebrou" in estado.mensagem
    assert estado.id_sessao is not None
    # O processamento falhou, então os vídeos continuam para um novo processamento.
    assert len(videos(dir_da_sessao(data_dir))) == 2


def test_duracao_fora_do_intervalo_nao_toca_estado_nem_rede(
    data_dir, modelo, clipes_legiveis
):
    from auto_counter.capture.duration import DuracaoForaDoIntervaloError

    relogio = RelogioFalso()
    servidor = servidor_de_um_clipe_por_minuto(relogio, clipes_legiveis, 2)

    with pytest.raises(DuracaoForaDoIntervaloError):
        executa(data_dir, servidor, relogio, minutos=16)

    assert servidor.pedidos == []
    assert ler_estado(data_dir) is None

"""Orquestração da sessão completa — T-10.

Critérios cobertos, de `.spec/features/interface-sessao/spec.md`:

- AC-011.4 — a sessão vai da captura ao XLSX sem a interface web;
- AC-012.1 e AC-012.2 — o estado acompanha cada minuto e a mudança de fase;
- AC-012.3 — o estado final traz o status gravado no banco e a planilha;
- AC-012.5 — encerrar no processamento termina cancelado, com os vídeos mantidos;
- AC-012.7 — encerrar na captura pela interface cancela a sessão inteira;
- AC-012.6 — sessão sem clipe processável termina sem planilha, com o status.

E, de `captura-clipes`, AC-003.6: a interrupção por Ctrl+C na captura segue
para o processamento. Servidor, relógio, espera e detector são dublês; nada aqui toca a
rede nem grava fora de `tmp_path`.
"""

from collections import Counter
from pathlib import Path

import numpy as np
import pytest
import supervision as sv

from auto_counter.cameras.model import Camera
from auto_counter.capture.status import StatusDaSessao
from auto_counter.counting.config import Categoria
from auto_counter.counting.model import ModeloAusenteError
from auto_counter.counting.sampling import (
    MOTIVO_NAO_ABRE,
    AmostragemDoClipe,
    FrameAmostrado,
)
from auto_counter.pipeline.run import executar_sessao
from auto_counter.pipeline.state import (
    MENSAGEM_SESSAO_CANCELADA,
    AnotadorDoEstado,
    Fase,
    ler_estado,
)
from auto_counter.pipeline.stop import (
    NOME_DO_PEDIDO,
    ParadaPorArquivo,
    pedir_parada,
)
from auto_counter.storage.connection import conectar
from auto_counter.storage.events import ler_eventos
from auto_counter.storage.minutes import ler_agregados
from auto_counter.storage.sessions import ler_sessao
from tests.test_capture_interrupt import (
    ParadaFalsa,
    servidor_de_um_clipe_por_minuto,
)
from tests.test_capture_session import (  # noqa: F401  (fixtures usadas por nome)
    INICIO as INICIO_DA_SESSAO,
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
from tests.test_counting_session import (
    CLASSE_COCO_POR_CATEGORIA,
    ByteTrackDuble,
    ParadaDuble,
    ParadaPedidaDepoisDeNChamadas,
)


def camera() -> Camera:
    """Câmera cuja linha cabe nos quadros 320x240 dos clipes dublê."""
    return Camera(
        resolucao={"largura": 320, "altura": 240},
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
    # A parada vem de um objeto em memória, e não do arquivo de pedido: é o
    # Ctrl+C no terminal. Só o botão da interface cria o arquivo, e esse caminho
    # cancela a sessão (AC-012.7, abaixo).
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


def test_AC_012_5_parada_no_ultimo_clipe_termina_cancelado_sem_planilha(
    data_dir, modelo, clipes_legiveis
):
    """O pedido chega com o único clipe da sessão já em análise (SUP-108).

    Antes, só se consultava a parada entre clipes: o pedido era ignorado e a
    sessão terminava concluída, com planilha e eventos no banco.
    """
    relogio = RelogioFalso()
    servidor = servidor_de_um_clipe_por_minuto(relogio, clipes_legiveis, 1)
    detector = DetectorDuble()
    fabricas = iter(
        [ParadaNunca, lambda: ParadaPedidaDepoisDeNChamadas(detector, chamadas=1)]
    )

    estado, _ = executa(
        data_dir,
        servidor,
        relogio,
        minutos=1,
        criar_detector=lambda caminho, config: detector,
        criar_parada=lambda: next(fabricas)(),
    )

    assert estado.fase is Fase.PROCESSAMENTO_CANCELADO
    assert estado.planilha is None
    assert detector.chamadas == 1
    assert videos(dir_da_sessao(data_dir)) == ["minuto-01.mp4"]
    assert list(data_dir.glob("*.xlsx")) == []
    with conectar(data_dir) as conexao:
        assert ler_agregados(conexao, estado.id_sessao) == ()
        assert ler_eventos(conexao, estado.id_sessao) == ()


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


CATEGORIAS_POR_CLIPE = (
    Categoria.CARRO,
    Categoria.ONIBUS,
    Categoria.CAMINHAO,
    Categoria.MOTO,
)
FRAMES_ANALISADOS_POR_CLIPE = 10
"""Clipes dublê de 30 quadros, amostragem 3."""


class DetectorQueCruza:
    """Um veículo cruza a linha por clipe, com categoria própria de cada clipe.

    Os 10 frames analisados de cada clipe chegam em sequência: os três primeiros
    ficam acima da linha (y = 120) e os demais abaixo, então há um cruzamento por
    clipe. Categorias diferentes por clipe impedem a deduplicação da emenda.
    """

    def __init__(self) -> None:
        self.chamadas = 0

    def detectar(self, frame) -> sv.Detections:
        clipe, posicao = divmod(self.chamadas, FRAMES_ANALISADOS_POR_CLIPE)
        self.chamadas += 1
        categoria = CATEGORIAS_POR_CLIPE[clipe % len(CATEGORIAS_POR_CLIPE)]
        y = 100.0 if posicao < 3 else 140.0
        return sv.Detections(
            xyxy=np.array([[155.0, y - 20.0, 165.0, y]], dtype=np.float32),
            confidence=np.array([0.9], dtype=np.float32),
            class_id=np.array([CLASSE_COCO_POR_CATEGORIA[categoria]], dtype=int),
            data={"categoria": np.array([categoria.value])},
        )


@pytest.fixture
def rastreador_duble(monkeypatch):
    """O `ByteTrack` real é trocado pelo dublê: o foco aqui é o estado."""
    monkeypatch.setattr("auto_counter.counting.tracking.sv.ByteTrack", ByteTrackDuble)


def executa_com_cruzamentos(data_dir, relogio, clipes_legiveis, *, minutos=3, **extra):
    servidor = servidor_de_um_clipe_por_minuto(relogio, clipes_legiveis, minutos)
    return executa(
        data_dir,
        servidor,
        relogio,
        minutos=minutos,
        criar_detector=lambda caminho, config: DetectorQueCruza(),
        **extra,
    )


def contagem_do_banco(data_dir, id_sessao) -> dict[str, int]:
    with conectar(data_dir) as conexao:
        por_categoria = Counter(e.categoria for e in ler_eventos(conexao, id_sessao))
    return {c.value: por_categoria.get(c, 0) for c in Categoria}


def test_AC_016_2_estado_em_disco_sobe_a_cada_evento_aceito(
    data_dir, modelo, clipes_legiveis, rastreador_duble, monkeypatch
):
    relogio = RelogioFalso()
    fotos = []
    original = AnotadorDoEstado.evento_aceito

    def espiao(self, minuto, categoria):
        original(self, minuto, categoria)
        quantidades = ler_estado(data_dir).quantidades
        fotos.append((sum(quantidades.values()), quantidades[categoria.value]))

    monkeypatch.setattr(AnotadorDoEstado, "evento_aceito", espiao)

    executa_com_cruzamentos(data_dir, relogio, clipes_legiveis)

    assert [total for total, _ in fotos] == [1, 2, 3]
    assert all(da_categoria == 1 for _, da_categoria in fotos)


def test_AC_016_4_quantidades_finais_iguais_aos_eventos_gravados_no_banco(
    data_dir, modelo, clipes_legiveis, rastreador_duble
):
    relogio = RelogioFalso()

    estado, _ = executa_com_cruzamentos(data_dir, relogio, clipes_legiveis)

    assert estado.fase is Fase.CONCLUIDA
    banco = contagem_do_banco(data_dir, estado.id_sessao)
    assert sum(banco.values()) == 3
    assert estado.quantidades == banco
    assert ler_estado(data_dir).quantidades == banco


class AmostragemQueFalhaNoFim(AmostragemDoClipe):
    """Entrega os 10 frames amostrados do clipe e então falha."""

    def __iter__(self):
        self.fps = 30.0
        for indice in range(0, 30, 3):
            self.total_de_frames = indice + 1
            yield FrameAmostrado(
                indice=indice, imagem=np.zeros((240, 320, 3), dtype=np.uint8)
            )
        self.motivo = MOTIVO_NAO_ABRE


def test_AC_016_8_clipe_que_falha_no_meio_desconta_do_estado_de_ponta_a_ponta(
    data_dir, modelo, clipes_legiveis, rastreador_duble, monkeypatch
):
    from auto_counter.counting import sampling

    real = sampling.frames_amostrados
    vistos = []

    def falha_no_minuto_2(caminho, amostragem):
        if Path(caminho).name == "minuto-02.mp4":
            return AmostragemQueFalhaNoFim(caminho, amostragem)
        return real(caminho, amostragem)

    monkeypatch.setattr(
        "auto_counter.counting.clip.frames_amostrados", falha_no_minuto_2
    )
    original = AnotadorDoEstado.evento_aceito

    def espiao(self, minuto, categoria):
        original(self, minuto, categoria)
        vistos.append(dict(ler_estado(data_dir).quantidades))

    monkeypatch.setattr(AnotadorDoEstado, "evento_aceito", espiao)

    estado, _ = executa_com_cruzamentos(data_dir, RelogioFalso(), clipes_legiveis)

    # O ônibus do minuto 2 chegou a aparecer na tela...
    assert any(q["ONIBUS"] == 1 for q in vistos)
    # ...e foi descontado: o estado final bate com o banco, sem ele.
    banco = contagem_do_banco(data_dir, estado.id_sessao)
    assert banco == {"CARRO": 1, "ONIBUS": 0, "CAMINHAO": 1, "MOTO": 0}
    assert estado.quantidades == banco


@pytest.mark.parametrize("encerramento_antecipado", [False, True])
def test_AC_017_2_iniciada_em_nao_muda_na_passagem_da_captura_para_o_processamento(
    data_dir, modelo, clipes_legiveis, encerramento_antecipado
):
    relogio = RelogioFalso()
    inicio = relogio.agora()
    dormir = DormirObservador(relogio, data_dir)
    visto = []

    def criar_detector(caminho, config):
        visto.append(ler_estado(data_dir))
        return DetectorDuble()

    if encerramento_antecipado:
        servidor = servidor_de_um_clipe_por_minuto(relogio, clipes_legiveis, 5)
        fabricas = iter([lambda: ParadaFalsa(relogio, segundo=80.0), ParadaNunca])
        extra = {"minutos": 5, "criar_parada": lambda: next(fabricas)()}
    else:
        servidor = servidor_de_um_clipe_por_minuto(relogio, clipes_legiveis, 2)
        extra = {"minutos": 2}

    estado, _ = executa(
        data_dir,
        servidor,
        relogio,
        dormir=dormir,
        criar_detector=criar_detector,
        **extra,
    )

    fases = {foto.fase for foto in dormir.fotos if foto is not None}
    assert Fase.CAPTURA in fases
    assert visto[0].fase is Fase.PROCESSAMENTO
    instantes = {foto.iniciada_em for foto in dormir.fotos if foto is not None}
    instantes |= {visto[0].iniciada_em, estado.iniciada_em}
    assert instantes == {inicio}


def test_AC_018_1_concluida_grava_terminada_em_do_relogio_injetado(
    data_dir, modelo, clipes_legiveis
):
    relogio = RelogioFalso()
    inicio = relogio.agora()
    servidor = servidor_de_um_clipe_por_minuto(relogio, clipes_legiveis, 2)

    estado, _ = executa(data_dir, servidor, relogio)

    assert estado.fase is Fase.CONCLUIDA
    assert estado.terminada_em == relogio.agora()
    assert estado.terminada_em > inicio
    assert ler_estado(data_dir).terminada_em == estado.terminada_em


def test_AC_018_3_cancelada_grava_terminada_em(data_dir, modelo, clipes_legiveis):
    relogio = RelogioFalso()
    servidor = servidor_de_um_clipe_por_minuto(relogio, clipes_legiveis, 2)
    pedida = ParadaDuble()
    pedida.pedida = True
    fabricas = iter([ParadaNunca, lambda: pedida])

    estado, _ = executa(
        data_dir, servidor, relogio, criar_parada=lambda: next(fabricas)()
    )

    assert estado.fase is Fase.PROCESSAMENTO_CANCELADO
    assert estado.terminada_em == relogio.agora()


def test_AC_018_3_sem_planilha_grava_terminada_em(data_dir, modelo, clipes_legiveis):
    relogio = RelogioFalso()
    servidor = servidor_de_um_clipe_por_minuto(relogio, clipes_legiveis, 2)
    pedida = ParadaDuble()
    pedida.pedida = True

    estado, _ = executa(data_dir, servidor, relogio, criar_parada=lambda: pedida)

    assert estado.fase is Fase.SEM_PLANILHA
    assert estado.terminada_em == relogio.agora()


# --- layout-interface: Tm e minutos com dado de ponta a ponta (T-05) ---


def test_AC_022_6_estado_grava_tm_quando_cada_minuto_comeca(
    data_dir, modelo, clipes_legiveis, rastreador_duble, monkeypatch
):
    relogio = RelogioFalso()
    fotos = []
    original = AnotadorDoEstado.minuto_iniciado

    def espiao(self):
        # O relógio só anda quando mandado: cada minuto começa num instante novo.
        relogio.avanca(7)
        original(self)
        fotos.append((ler_estado(data_dir).minuto_em_analise_desde, relogio.agora()))

    monkeypatch.setattr(AnotadorDoEstado, "minuto_iniciado", espiao)

    executa_com_cruzamentos(data_dir, relogio, clipes_legiveis, minutos=3)

    assert len(fotos) == 3
    assert all(gravado == do_relogio for gravado, do_relogio in fotos)
    assert len({gravado for gravado, _ in fotos}) == 3


def test_AC_022_3_estado_final_tem_k_e_v_iguais_aos_minutos_com_dado_e_ao_banco(
    data_dir, modelo, clipes_legiveis, rastreador_duble
):
    relogio = RelogioFalso()
    # Minuto 2 perdido na captura; o minuto 3 pega o clipe publicado em t=100.
    servidor = ServidorFalso(
        relogio,
        [(0.0, "clipe-a"), (100.0, "clipe-c")],
        clipes_legiveis("clipe-a", "clipe-c"),
    )

    estado, _ = executa(
        data_dir,
        servidor,
        relogio,
        minutos=3,
        criar_detector=lambda caminho, config: DetectorQueCruza(),
    )

    assert estado.fase is Fase.CONCLUIDA
    final = ler_estado(data_dir)
    assert final.minutos_perdidos == (2,)
    assert final.minutos_com_dado == 2
    banco = contagem_do_banco(data_dir, estado.id_sessao)
    assert final.veiculos_nos_minutos_com_dado == sum(banco.values()) == 2


def test_AC_022_3_clipe_que_falha_no_meio_fica_fora_de_k_de_ponta_a_ponta(
    data_dir, modelo, clipes_legiveis, rastreador_duble, monkeypatch
):
    from auto_counter.counting import sampling

    real = sampling.frames_amostrados

    def falha_no_minuto_2(caminho, amostragem):
        if Path(caminho).name == "minuto-02.mp4":
            return AmostragemQueFalhaNoFim(caminho, amostragem)
        return real(caminho, amostragem)

    monkeypatch.setattr(
        "auto_counter.counting.clip.frames_amostrados", falha_no_minuto_2
    )

    estado, _ = executa_com_cruzamentos(data_dir, RelogioFalso(), clipes_legiveis)

    final = ler_estado(data_dir)
    assert final.minutos_processados == 3
    assert final.minutos_com_dado == 2
    banco = contagem_do_banco(data_dir, estado.id_sessao)
    assert final.veiculos_nos_minutos_com_dado == sum(banco.values()) == 2


# --- download-clipes: manter_videos e clipes no estado de ponta a ponta (T-04) ---


def test_AC_024_2_com_a_opcao_os_clipes_ficam_e_o_estado_os_lista(
    data_dir, modelo, clipes_legiveis
):
    relogio = RelogioFalso()
    servidor = servidor_de_um_clipe_por_minuto(relogio, clipes_legiveis, 3)

    estado, _ = executa(data_dir, servidor, relogio, minutos=3, manter_videos=True)

    assert estado.fase is Fase.CONCLUIDA
    assert estado.manter_videos is True
    final = ler_estado(data_dir)
    assert final.manter_videos is True
    assert [c.minuto for c in final.clipes] == [1, 2, 3]
    for clipe in final.clipes:
        assert clipe.caminho.is_file()
    assert sorted(videos(dir_da_sessao(data_dir))) == [
        "minuto-01.mp4",
        "minuto-02.mp4",
        "minuto-03.mp4",
    ]


def test_AC_024_3_sem_a_opcao_nenhum_video_fica_e_o_estado_registra_false(
    data_dir, modelo, clipes_legiveis
):
    relogio = RelogioFalso()
    servidor = servidor_de_um_clipe_por_minuto(relogio, clipes_legiveis, 2)

    estado, _ = executa(data_dir, servidor, relogio)

    assert estado.fase is Fase.CONCLUIDA
    final = ler_estado(data_dir)
    assert final.manter_videos is False
    assert final.clipes is None
    assert videos(dir_da_sessao(data_dir)) == []


def test_AC_025_2_minuto_perdido_nao_entra_nos_clipes_do_estado(
    data_dir, modelo, clipes_legiveis
):
    relogio = RelogioFalso()
    # Minuto 2 perdido; o minuto 3 pega o clipe publicado em t=100.
    servidor = ServidorFalso(
        relogio,
        [(0.0, "clipe-a"), (100.0, "clipe-c")],
        clipes_legiveis("clipe-a", "clipe-c"),
    )

    estado, _ = executa(
        data_dir, servidor, relogio, minutos=3, manter_videos=True
    )

    assert estado.fase is Fase.CONCLUIDA
    final = ler_estado(data_dir)
    assert [c.minuto for c in final.clipes] == [1, 3]


def test_AC_025_6_processamento_cancelado_nao_grava_clipes(
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
        manter_videos=True,
    )

    assert estado.fase is Fase.PROCESSAMENTO_CANCELADO
    assert ler_estado(data_dir).clipes is None
    assert videos(dir_da_sessao(data_dir)) == ["minuto-01.mp4", "minuto-02.mp4"]


def test_AC_025_6_sem_planilha_nao_grava_clipes(data_dir, modelo, clipes_legiveis):
    relogio = RelogioFalso()
    servidor = servidor_de_um_clipe_por_minuto(relogio, clipes_legiveis, 2)
    pedida = ParadaDuble()
    pedida.pedida = True

    estado, _ = executa(
        data_dir, servidor, relogio, criar_parada=lambda: pedida, manter_videos=True
    )

    assert estado.fase is Fase.SEM_PLANILHA
    assert ler_estado(data_dir).clipes is None


def test_falha_ao_listar_clipes_nao_derruba_a_sessao(
    data_dir, modelo, clipes_legiveis, monkeypatch, capsys
):
    relogio = RelogioFalso()
    servidor = servidor_de_um_clipe_por_minuto(relogio, clipes_legiveis, 2)
    monkeypatch.setattr(
        "auto_counter.pipeline.run.clipes_mantidos",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("falha ao listar")),
    )

    estado, _ = executa(data_dir, servidor, relogio, manter_videos=True)

    assert estado.fase is Fase.CONCLUIDA
    assert estado.planilha is not None
    assert ler_estado(data_dir).clipes is None
    assert "aviso" in capsys.readouterr().err


# --- AC-012.7: parar na captura pela interface cancela a sessão inteira ---


class ParadaQueCriaOPedido:
    """O clique em "Parar antecipadamente" durante a captura.

    A partir de `segundo` no relógio falso, grava o arquivo de pedido, como faz
    `encerrar_sessao`, e a captura enxerga a parada como em `session run`, que
    consulta o arquivo.
    """

    def __init__(self, relogio, segundo, data_dir):
        self._relogio = relogio
        self._segundo = segundo
        self._data_dir = data_dir

    def foi_pedida(self) -> bool:
        if self._relogio.decorrido() >= self._segundo:
            pedir_parada(self._data_dir)
            return True
        return False


class PedidoQueChegaSemSerVistoPelaCaptura(ParadaQueCriaOPedido):
    """O clique que chega quando a captura já não vai mais consultar a parada."""

    def foi_pedida(self) -> bool:
        super().foi_pedida()
        return False


def cancela_na_captura(data_dir, clipes_legiveis, *, manter_videos=False, minutos=5):
    """Roda a sessão com o botão apertado no meio do minuto 3 da captura."""
    relogio = RelogioFalso()
    servidor = servidor_de_um_clipe_por_minuto(relogio, clipes_legiveis, minutos)
    chamadas_do_detector = []

    def criar_detector(caminho, config):
        chamadas_do_detector.append(caminho)
        return DetectorDuble()

    estado, _ = executa(
        data_dir,
        servidor,
        relogio,
        minutos=minutos,
        criar_detector=criar_detector,
        criar_parada=lambda: ParadaQueCriaOPedido(relogio, 80.0, data_dir),
        manter_videos=manter_videos,
    )
    return estado, chamadas_do_detector


def test_AC_012_7_parar_na_captura_pela_interface_nao_processa(
    data_dir, modelo, clipes_legiveis
):
    estado, chamadas_do_detector = cancela_na_captura(data_dir, clipes_legiveis)

    assert estado.fase is Fase.SESSAO_CANCELADA
    assert estado.planilha is None
    assert chamadas_do_detector == []
    assert list(data_dir.glob("*.xlsx")) == []
    with conectar(data_dir) as conexao:
        assert ler_agregados(conexao, estado.id_sessao) == ()


def test_AC_012_7_parar_na_captura_apaga_os_clipes_mesmo_com_manter_videos(
    data_dir, modelo, clipes_legiveis
):
    estado, _ = cancela_na_captura(data_dir, clipes_legiveis, manter_videos=True)

    sessao = dir_da_sessao(data_dir)
    assert estado.fase is Fase.SESSAO_CANCELADA
    assert videos(sessao) == []
    assert (sessao / "manifest.json").is_file()


def test_AC_012_7_parar_na_captura_marca_a_sessao_no_banco_sem_eventos(
    data_dir, modelo, clipes_legiveis
):
    estado, _ = cancela_na_captura(data_dir, clipes_legiveis)

    with conectar(data_dir) as conexao:
        gravada = ler_sessao(conexao, estado.id_sessao)
        eventos = ler_eventos(conexao, estado.id_sessao)
    assert gravada.cancelada_pelo_usuario is True
    assert eventos == ()


def test_AC_012_7_parar_na_captura_grava_terminada_em_e_a_mensagem(
    data_dir, modelo, clipes_legiveis
):
    cancela_na_captura(data_dir, clipes_legiveis)

    gravado = ler_estado(data_dir)
    assert gravado.fase is Fase.SESSAO_CANCELADA
    assert gravado.terminada_em is not None
    assert gravado.mensagem == MENSAGEM_SESSAO_CANCELADA
    assert gravado.id_sessao is not None


def test_AC_012_7_falha_ao_marcar_no_banco_so_avisa_e_cancela_assim_mesmo(
    data_dir, modelo, clipes_legiveis, monkeypatch, capsys
):
    def falha(conexao, id_sessao, **kwargs):
        raise RuntimeError("banco indisponível")

    monkeypatch.setattr("auto_counter.pipeline.run.marcar_sessao_cancelada", falha)

    estado, chamadas_do_detector = cancela_na_captura(data_dir, clipes_legiveis)

    assert estado.fase is Fase.SESSAO_CANCELADA
    assert chamadas_do_detector == []
    assert videos(dir_da_sessao(data_dir)) == []
    erro = capsys.readouterr().err
    assert "cancelada" in erro and "banco indisponível" in erro


def test_AC_012_7_pedido_que_chega_com_a_captura_ja_no_fim_cancela(
    data_dir, modelo, clipes_legiveis
):
    """A captura termina sozinha, sem ver a parada, e o arquivo já existe.

    Com 2 minutos o último clipe publica em 60 s do relógio falso, então o
    pedido a 50 s cai dentro da captura e ela não o enxerga.
    """
    relogio = RelogioFalso()
    servidor = servidor_de_um_clipe_por_minuto(relogio, clipes_legiveis, 2)

    estado, detectores = executa(
        data_dir,
        servidor,
        relogio,
        minutos=2,
        criar_parada=lambda: PedidoQueChegaSemSerVistoPelaCaptura(
            relogio, 50.0, data_dir
        ),
    )

    assert estado.fase is Fase.SESSAO_CANCELADA
    assert estado.minutos_capturados == (1, 2)
    assert detectores == []
    assert videos(dir_da_sessao(data_dir)) == []


# --- servidor-indisponivel: orquestração (T-06, D-10) ---


def servidor_que_cai(relogio, clipes_legiveis, *, desde=None):
    """Três clipes capturados e o servidor fora do ar a partir de `desde`."""
    from tests.test_capture_session import (
        FORA_DO_AR,
        PUBLICACOES_DOS_TRES_CLIPES,
        QUEDA_DEPOIS_DO_MINUTO_3,
        ServidorComFalhas,
    )

    return ServidorComFalhas(
        relogio,
        PUBLICACOES_DOS_TRES_CLIPES,
        clipes_legiveis("clipe-a", "clipe-b", "clipe-c"),
        indisponivel=[
            (QUEDA_DEPOIS_DO_MINUTO_3 if desde is None else desde, FORA_DO_AR, "conexao")
        ],
    )


def test_AC_033_6_sessao_encerrada_por_servidor_com_minuto_capturado_gera_planilha(
    data_dir, modelo, clipes_legiveis
):
    relogio = RelogioFalso()
    servidor = servidor_que_cai(relogio, clipes_legiveis)

    estado, detectores = executa(data_dir, servidor, relogio, minutos=15)

    assert estado.fase is Fase.CONCLUIDA
    assert estado.planilha is not None
    assert len(detectores) == 1
    assert estado.minutos_capturados == (1, 2, 3)
    assert estado.encerrada_por_servidor_indisponivel is True
    assert estado.servidor_indisponivel_desde is not None
    assert estado.status == StatusDaSessao.INVALIDA.value
    # O que o arquivo guarda é o mesmo que a função devolveu.
    em_disco = ler_estado(data_dir)
    assert em_disco.encerrada_por_servidor_indisponivel is True
    assert em_disco.servidor_indisponivel_desde == estado.servidor_indisponivel_desde
    # E a marca chegou ao banco pelo processamento (AC-036.2).
    with conectar(data_dir) as conexao:
        assert ler_sessao(conexao, estado.id_sessao).encerrada_por_servidor_indisponivel


def test_AC_033_8_sessao_encerrada_por_servidor_sem_minuto_termina_sem_planilha(
    data_dir, modelo, clipes_legiveis
):
    relogio = RelogioFalso()
    servidor = servidor_que_cai(relogio, clipes_legiveis, desde=0.0)

    estado, detectores = executa(data_dir, servidor, relogio, minutos=3)

    assert estado.fase is Fase.SEM_PLANILHA
    assert estado.planilha is None
    assert estado.status == StatusDaSessao.INVALIDA.value
    assert estado.encerrada_por_servidor_indisponivel is True
    # A primeira falha é a checagem imediata do comando, em T0.
    assert estado.servidor_indisponivel_desde == INICIO_DA_SESSAO
    assert detectores == []
    assert list(data_dir.glob("*.xlsx")) == []
    with conectar(data_dir) as conexao:
        assert ler_sessao(conexao, estado.id_sessao).encerrada_por_servidor_indisponivel


def test_AC_012_1_nao_tentados_entram_como_perdidos_no_estado(
    data_dir, modelo, clipes_legiveis
):
    relogio = RelogioFalso()
    servidor = servidor_que_cai(relogio, clipes_legiveis)

    estado, _ = executa(data_dir, servidor, relogio, minutos=15)

    assert estado.minutos_capturados == (1, 2, 3)
    assert estado.minutos_perdidos == tuple(range(4, 16))
    assert ler_estado(data_dir).minutos_perdidos == tuple(range(4, 16))


def test_AC_017_2_tempo_continua_de_t0_apos_encerramento_por_servidor(
    data_dir, modelo, clipes_legiveis
):
    relogio = RelogioFalso()
    inicio = relogio.agora()
    servidor = servidor_que_cai(relogio, clipes_legiveis)
    visto = []

    def criar_detector(caminho, config):
        visto.append(ler_estado(data_dir))
        return DetectorDuble()

    estado, _ = executa(
        data_dir, servidor, relogio, minutos=15, criar_detector=criar_detector
    )

    assert visto[0].fase is Fase.PROCESSAMENTO
    assert visto[0].iniciada_em == inicio
    assert estado.iniciada_em == inicio
    # O processamento começou depois do encerramento, e T0 não se mexeu.
    assert visto[0].encerrada_por_servidor_indisponivel is True
    assert estado.terminada_em >= inicio

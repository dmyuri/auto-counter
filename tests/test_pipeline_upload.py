"""Orquestração da sessão de upload — T-13 de `processamento-upload`.

Critérios cobertos, de `.spec/features/processamento-upload/spec.md`:

- AC-028.1 — N vídeos viram uma única sessão da câmera, que começa direto no
  processamento e termina com uma planilha;
- AC-028.3 e AC-028.10 — o estado em disco acompanha cada vídeo e as quantidades;
- AC-028.9 — o vídeo que falha fica "falhou" e a sessão conclui;
- AC-029.1 e AC-029.2 — parar cancela sem gravar e mantém os vídeos, com o
  vídeo em curso "interrompido", os anteriores concluídos e os seguintes na fila;
- AC-030.6 — a sessão concluída não deixa vídeo em `envios/` nem na sessão;
- AC-030.7 — arquivo inválido termina "falhou", sem criar o diretório da sessão.

Mais SUP-094 (nenhum vídeo legível termina sem planilha) e D-11, D-12 e D-15 do
`_tasks.md`. Vídeos gerados em `tmp_path`, detector e rastreador são dublês; nada
aqui toca a rede nem grava fora de `tmp_path`.
"""

from datetime import datetime, timezone

import cv2
import numpy as np
import pytest

from auto_counter.counting.model import ModeloAusenteError
from auto_counter.counting.sampling import MOTIVO_NAO_ABRE, AmostragemDoClipe
from auto_counter.pipeline.state import Fase, SituacaoDoVideo, ler_estado
from auto_counter.pipeline.upload import executar_upload
from auto_counter.storage.connection import conectar
from auto_counter.storage.events import ler_eventos
from auto_counter.storage.model import OrigemDaSessao
from auto_counter.storage.sessions import listar_sessoes, ler_sessao
from auto_counter.upload.manifest import NOME_DO_REGISTRO
from tests.test_cli_process import (  # noqa: F401  (fixtures usadas por nome)
    ID_CAMERA,
    data_dir,
    modelo,
)
from tests.test_counting_session import ParadaDuble
from tests.test_pipeline_run import (  # noqa: F401  (fixtures usadas por nome)
    DetectorQueCruza,
    ParadaNunca,
    camera,
    rastreador_duble,
)

T0 = datetime(2026, 11, 7, 14, 30, 0, tzinfo=timezone.utc)
ID_SESSAO = "000013-20261107T143000Z"
FRAMES_POR_VIDEO = 10
"""Vídeos de 10 quadros a 10 fps: 1 s, 1 minuto, 10 frames analisados."""


def escreve_video(caminho, *, quadros=FRAMES_POR_VIDEO, fps=10, lado=(320, 240)):
    largura, altura = lado
    escritor = cv2.VideoWriter(
        str(caminho), cv2.VideoWriter_fourcc(*"mp4v"), fps, (largura, altura)
    )
    assert escritor.isOpened()
    try:
        for _ in range(quadros):
            escritor.write(np.zeros((altura, largura, 3), dtype=np.uint8))
    finally:
        escritor.release()
    return caminho


def videos_em_envios(data_dir, quantos=2):
    """Vídeos já enviados pela interface: ficam em `envios/` com nome uuid."""
    pasta = data_dir / "envios"
    pasta.mkdir(parents=True, exist_ok=True)
    return (
        [escreve_video(pasta / f"uuid-{i}.mp4") for i in range(quantos)],
        [f"original-{i + 1}.mp4" for i in range(quantos)],
    )


class RelogioQueAvanca:
    """Cada leitura do relógio devolve 1 s a mais que a anterior."""

    def __init__(self):
        self.chamadas = 0

    def __call__(self) -> datetime:
        instante = T0.replace(second=self.chamadas % 60)
        self.chamadas += 1
        return instante


def executa(data_dir, arquivos, nomes, *, criar_detector=None, criar_parada=None,
            agora=None):
    return executar_upload(
        camera(),
        arquivos,
        nomes,
        data_dir=data_dir,
        agora=agora or (lambda: T0),
        criar_detector=criar_detector or (lambda caminho, config: DetectorQueCruza()),
        criar_parada=criar_parada or ParadaNunca,
        pid=4242,
    )


def dir_da_sessao(data_dir):
    return data_dir / "sessions" / ID_SESSAO


def test_AC_028_1_n_videos_viram_uma_sessao_da_camera_com_uma_planilha(
    data_dir, modelo, rastreador_duble
):
    arquivos, nomes = videos_em_envios(data_dir, 2)

    estado = executa(data_dir, arquivos, nomes)

    assert estado.fase is Fase.CONCLUIDA
    assert estado.id_sessao == ID_SESSAO
    assert estado.origem == "UPLOAD"
    with conectar(data_dir) as conexao:
        sessoes = listar_sessoes(conexao)
        gravada = ler_sessao(conexao, ID_SESSAO)
    assert len(sessoes) == 1
    assert gravada.id_camera == ID_CAMERA
    assert gravada.origem is OrigemDaSessao.UPLOAD
    assert [video.nome_original for video in gravada.videos] == nomes
    planilhas = list(data_dir.glob("*.xlsx"))
    assert len(planilhas) == 1
    assert estado.planilha == str(planilhas[0])
    assert planilhas[0].name.startswith(f"{ID_CAMERA}_20261107_")
    assert "_upload" in planilhas[0].name
    assert estado.status == gravada.status.value


def test_AC_028_1_sessao_comeca_direto_no_processamento(
    data_dir, modelo, rastreador_duble
):
    arquivos, nomes = videos_em_envios(data_dir, 2)
    vistos = []

    def criar_detector(caminho, config):
        vistos.append(ler_estado(data_dir))
        return DetectorQueCruza()

    executa(data_dir, arquivos, nomes, criar_detector=criar_detector)

    primeiro = vistos[0]
    assert primeiro.fase is Fase.PROCESSAMENTO
    assert primeiro.origem == "UPLOAD"
    assert primeiro.minutos_capturados == ()
    assert primeiro.minutos_a_processar == 2
    assert primeiro.duracao_pedida == 2


def test_AC_028_3_estado_em_disco_acompanha_cada_video(
    data_dir, modelo, rastreador_duble
):
    arquivos, nomes = videos_em_envios(data_dir, 2)
    vistos = []

    class DetectorObservador(DetectorQueCruza):
        def detectar(self, frame):
            if self.chamadas % FRAMES_POR_VIDEO == 0:
                vistos.append(
                    tuple(v.situacao for v in ler_estado(data_dir).videos)
                )
            return super().detectar(frame)

    estado = executa(
        data_dir, arquivos, nomes, criar_detector=lambda c, cfg: DetectorObservador()
    )

    fila, processando, concluido = (
        SituacaoDoVideo.FILA,
        SituacaoDoVideo.PROCESSANDO,
        SituacaoDoVideo.CONCLUIDO,
    )
    assert vistos[0] == (processando, fila)
    assert vistos[1] == (concluido, processando)
    assert tuple(v.situacao for v in estado.videos) == (concluido, concluido)
    assert [v.nome for v in ler_estado(data_dir).videos] == nomes


class AmostragemQueFalhaNoInicio(AmostragemDoClipe):
    """Não entrega frame nenhum: o vídeo falha no minuto 1 (D-4)."""

    def __iter__(self):
        self.fps = 10.0
        self.motivo = MOTIVO_NAO_ABRE
        yield from ()


def faz_falhar(monkeypatch, *, posicoes):
    """Troca a amostragem só dos vídeos `posicoes` (pelo nome no disco)."""
    from auto_counter.counting import sampling

    original = sampling.frames_amostrados_por_taxa
    nomes_que_falham = {f"video-{p:02d}.mp4" for p in posicoes}

    def amostragem(caminho, taxa):
        if caminho.name in nomes_que_falham:
            return AmostragemQueFalhaNoInicio(caminho, 1)
        return original(caminho, taxa)

    monkeypatch.setattr(
        "auto_counter.counting.video.frames_amostrados_por_taxa", amostragem
    )


def test_AC_028_9_video_que_falha_fica_falhou_e_a_sessao_conclui(
    data_dir, modelo, rastreador_duble, monkeypatch
):
    arquivos, nomes = videos_em_envios(data_dir, 2)
    faz_falhar(monkeypatch, posicoes=[1])

    estado = executa(data_dir, arquivos, nomes)

    assert estado.fase is Fase.CONCLUIDA
    assert tuple(v.situacao for v in estado.videos) == (
        SituacaoDoVideo.FALHOU,
        SituacaoDoVideo.CONCLUIDO,
    )
    # O minuto do vídeo que falhou conta como processado, mas sem dado.
    assert estado.minutos_processados == 2
    assert estado.minutos_com_dado == 1
    with conectar(data_dir) as conexao:
        gravada = ler_sessao(conexao, ID_SESSAO)
    assert gravada.minutos_perdidos == (1,)
    assert gravada.minutos_perdidos_quantidade == 1


def test_AC_028_10_quantidades_no_estado_iguais_aos_eventos_gravados(
    data_dir, modelo, rastreador_duble
):
    arquivos, nomes = videos_em_envios(data_dir, 2)

    estado = executa(data_dir, arquivos, nomes)

    with conectar(data_dir) as conexao:
        eventos = ler_eventos(conexao, ID_SESSAO)
    assert len(eventos) == 2
    assert sum(estado.quantidades.values()) == len(eventos)
    for categoria, quantos in estado.quantidades.items():
        assert quantos == sum(1 for e in eventos if e.categoria.value == categoria)
    assert estado.minutos_com_dado == 2
    assert estado.veiculos_nos_minutos_com_dado == 2
    assert ler_estado(data_dir) == estado


def test_AC_029_1_parar_cancela_sem_gravar_e_mantem_os_videos(
    data_dir, modelo, rastreador_duble
):
    arquivos, nomes = videos_em_envios(data_dir, 2)
    parada = ParadaDuble()
    parada.pedida = True

    estado = executa(data_dir, arquivos, nomes, criar_parada=lambda: parada)

    assert estado.fase is Fase.PROCESSAMENTO_CANCELADO
    assert f"session process {ID_SESSAO}" in estado.mensagem
    assert not list(data_dir.glob("*.xlsx"))
    assert not (dir_da_sessao(data_dir) / "eventos.json").exists()
    with conectar(data_dir) as conexao:
        assert listar_sessoes(conexao) == ()
    guardados = sorted(p.name for p in dir_da_sessao(data_dir).glob("video-*"))
    assert guardados == ["video-01.mp4", "video-02.mp4"]
    assert (dir_da_sessao(data_dir) / NOME_DO_REGISTRO).is_file()


class ParadaNaConsulta:
    """Pede a parada na consulta de número `n` (a contagem começa em 1)."""

    def __init__(self, n: int) -> None:
        self._n = n
        self.consultas = 0

    def foi_pedida(self) -> bool:
        self.consultas += 1
        return self.consultas >= self._n


def test_AC_029_2_cancelada_mostra_interrompido_concluido_e_fila(
    data_dir, modelo, rastreador_duble
):
    arquivos, nomes = videos_em_envios(data_dir, 3)
    # Consultas: antes do vídeo 1 (1) e do seu minuto (2); antes do vídeo 2 (3)
    # e do seu minuto (4). A quarta pede a parada com o vídeo 2 em curso.
    parada = ParadaNaConsulta(4)

    estado = executa(data_dir, arquivos, nomes, criar_parada=lambda: parada)

    assert estado.fase is Fase.PROCESSAMENTO_CANCELADO
    assert tuple(v.situacao for v in estado.videos) == (
        SituacaoDoVideo.CONCLUIDO,
        SituacaoDoVideo.INTERROMPIDO,
        SituacaoDoVideo.FILA,
    )
    assert ler_estado(data_dir) == estado


def test_AC_030_6_concluida_nao_deixa_video_em_envios_nem_na_sessao(
    data_dir, modelo, rastreador_duble
):
    arquivos, nomes = videos_em_envios(data_dir, 2)
    sobra = escreve_video(data_dir / "envios" / "orfao.mp4")

    estado = executa(data_dir, arquivos, nomes)

    assert estado.fase is Fase.CONCLUIDA
    assert list((data_dir / "envios").iterdir()) == []
    assert not sobra.exists()
    assert list(dir_da_sessao(data_dir).glob("video-*")) == []
    # O registro e os eventos ficam, para o histórico e a reexportação.
    assert (dir_da_sessao(data_dir) / NOME_DO_REGISTRO).is_file()
    assert (dir_da_sessao(data_dir) / "eventos.json").is_file()


def test_SUP_094_nenhum_video_legivel_termina_sem_planilha(
    data_dir, modelo, rastreador_duble, monkeypatch
):
    arquivos, nomes = videos_em_envios(data_dir, 2)
    faz_falhar(monkeypatch, posicoes=[1, 2])

    estado = executa(data_dir, arquivos, nomes)

    assert estado.fase is Fase.SEM_PLANILHA
    assert estado.planilha is None
    assert tuple(v.situacao for v in estado.videos) == (
        SituacaoDoVideo.FALHOU,
        SituacaoDoVideo.FALHOU,
    )
    assert not list(data_dir.glob("*.xlsx"))
    with conectar(data_dir) as conexao:
        assert listar_sessoes(conexao) == ()
    # D-15: as cópias ficam onde estão.
    assert len(list(dir_da_sessao(data_dir).glob("video-*"))) == 2


def test_AC_030_7_arquivo_invalido_termina_falhou_sem_criar_sessao(
    data_dir, modelo, rastreador_duble
):
    arquivos, nomes = videos_em_envios(data_dir, 2)
    escreve_video(arquivos[1], lado=(640, 480))

    with pytest.raises(ValueError, match="original-2.mp4"):
        executa(data_dir, arquivos, nomes)

    estado = ler_estado(data_dir)
    assert estado.fase is Fase.FALHOU
    assert "original-2.mp4" in estado.mensagem
    assert not (data_dir / "sessions").exists()
    # Nada foi movido nem apagado: o arquivo continua onde a interface o pôs.
    assert all(arquivo.exists() for arquivo in arquivos)


def test_modelo_ausente_falha_antes_de_ler_os_videos(data_dir, rastreador_duble):
    arquivos, nomes = videos_em_envios(data_dir, 2)
    lidos = []

    def criar_detector(caminho, config):
        lidos.append(caminho)
        return DetectorQueCruza()

    with pytest.raises(ModeloAusenteError):
        executa(data_dir, arquivos, nomes, criar_detector=criar_detector)

    assert lidos == []
    assert ler_estado(data_dir).fase is Fase.FALHOU
    assert not (data_dir / "sessions").exists()
    assert all(arquivo.exists() for arquivo in arquivos)


def test_falha_inesperada_marca_interrompido_e_falhou(
    data_dir, modelo, rastreador_duble
):
    arquivos, nomes = videos_em_envios(data_dir, 2)

    class DetectorQueQuebra(DetectorQueCruza):
        def detectar(self, frame):
            if self.chamadas == 3:
                raise RuntimeError("detector quebrou")
            return super().detectar(frame)

    with pytest.raises(RuntimeError, match="detector quebrou"):
        executa(
            data_dir,
            arquivos,
            nomes,
            criar_detector=lambda c, cfg: DetectorQueQuebra(),
        )

    estado = ler_estado(data_dir)
    assert estado.fase is Fase.FALHOU
    assert "detector quebrou" in estado.mensagem
    assert estado.id_sessao == ID_SESSAO
    assert tuple(v.situacao for v in estado.videos) == (
        SituacaoDoVideo.INTERROMPIDO,
        SituacaoDoVideo.FILA,
    )

"""Laço da sessão de upload — T-09 de `processamento-upload`.

Critérios cobertos, de `.spec/features/processamento-upload/spec.md`:

- AC-028.1 — os vídeos são processados na ordem da lista;
- AC-028.7 — a troca de vídeo reinicia o rastreador e conta todos os
  cruzamentos dos dois vídeos;
- AC-028.8 — os minutos da sessão atravessam os vídeos;
- AC-028.9 — o vídeo que falha não para a sessão;
- AC-029.1 — a parada cancela sem deixar `eventos.json`.

Mais SUP-094 (nenhum vídeo legível) e D-12. Vídeos sintéticos em `tmp_path`,
com detector e ByteTrack dublês; nenhum teste carrega o `.onnx`.
"""

from datetime import datetime, timezone

import pytest

from auto_counter.counting.config import ConfiguracaoDoProcessamento
from auto_counter.counting.events import NOME_DO_ARQUIVO_DE_EVENTOS
from auto_counter.counting.session import ProcessamentoCancelado, SessaoSemClipes
from auto_counter.counting.upload import processar_sessao_de_upload
from auto_counter.upload.manifest import (
    RegistroDoUpload,
    VideoDaSessaoDeUpload,
    gravar,
    numerar_minutos,
)
from tests.test_counting_session import (
    DIREITA,
    ESQUERDA,
    ByteTrackDuble,
    DetectorDuble,
    ParadaDuble,
    camera,
    roteiro_do_clipe,
)
from tests.test_counting_video import escreve_video

ID_SESSAO = "000013-20261107T143000Z"
T0 = datetime(2026, 11, 7, 14, 30, 0, tzinfo=timezone.utc)
VERSAO_DO_MODELO = "yolo11n.onnx@0123456789ab"
FPS = 10


def monta_sessao(tmp_path, videos):
    """`videos` é uma lista de `(quadros, legivel)`; devolve o diretório."""
    dir_sessao = tmp_path / "sessions" / ID_SESSAO
    dir_sessao.mkdir(parents=True)
    duracoes = [quadros // FPS for quadros, _ in videos]
    faixas = numerar_minutos(duracoes)
    itens = []
    for posicao, ((quadros, legivel), duracao, (inicial, final)) in enumerate(
        zip(videos, duracoes, faixas), start=1
    ):
        arquivo = f"video-{posicao:02d}.mp4"
        if legivel:
            escreve_video(dir_sessao / arquivo, fps=FPS, quadros=quadros)
        else:
            (dir_sessao / arquivo).write_bytes(b"isto nao e um video")
        itens.append(
            VideoDaSessaoDeUpload(
                posicao=posicao,
                nome_original=f"original-{posicao}.mp4",
                arquivo=arquivo,
                duracao_segundos=duracao,
                sha256=f"{posicao}" * 64,
                minuto_inicial=inicial,
                minuto_final=final,
            )
        )
    gravar(
        dir_sessao,
        RegistroDoUpload(
            id_sessao=ID_SESSAO,
            id_camera="000013",
            duracao_minutos=faixas[-1][1],
            videos=tuple(itens),
        ),
    )
    return dir_sessao


def conta(dir_sessao, roteiro=(), **extra):
    extra.setdefault("fabrica_de_bytetrack", ByteTrackDuble)
    return processar_sessao_de_upload(
        dir_sessao,
        camera=camera(),
        detector=DetectorDuble(roteiro),
        config=ConfiguracaoDoProcessamento(),
        versao_do_modelo=VERSAO_DO_MODELO,
        inicio_do_processamento=T0,
        **extra,
    )


def cruza(antes, quantos_antes, depois, quantos_depois):
    return roteiro_do_clipe([antes] * quantos_antes + [depois] * quantos_depois)


class Registro:
    def __init__(self):
        self.chamadas = []

    def ganchos(self):
        return {
            "ao_iniciar_video": lambda p: self.chamadas.append(("iniciar_video", p)),
            "ao_terminar_video": lambda p, falhou: self.chamadas.append(
                ("terminar_video", p, falhou)
            ),
            "ao_iniciar_minuto": lambda m: self.chamadas.append(("iniciar", m)),
            "ao_descartar_minuto": lambda m: self.chamadas.append(("descartar", m)),
            "ao_resolver_minuto": lambda m, c: self.chamadas.append(("resolver", m, c)),
        }


def test_AC_028_1_videos_processados_na_ordem_da_lista(tmp_path):
    dir_sessao = monta_sessao(tmp_path, [(50, True), (50, True), (50, True)])
    roteiro = (
        cruza(DIREITA, 10, ESQUERDA, 40)
        + cruza(DIREITA, 10, ESQUERDA, 40)
        + cruza(DIREITA, 10, ESQUERDA, 40)
    )

    resultado = conta(dir_sessao, roteiro)

    assert [e.video for e in resultado.eventos] == [1, 2, 3]
    assert [e.minuto for e in resultado.eventos] == [1, 2, 3]
    assert (dir_sessao / NOME_DO_ARQUIVO_DE_EVENTOS).is_file()
    assert resultado.registro.id_sessao == ID_SESSAO
    assert resultado.registro.id_camera == "000013"
    assert resultado.registro.versao_do_modelo == VERSAO_DO_MODELO


def test_AC_028_7_dois_videos_consecutivos_contam_todos_os_cruzamentos(tmp_path):
    dir_sessao = monta_sessao(tmp_path, [(100, True), (100, True)])
    # Mesma assinatura (lado e sentido) no último segundo do vídeo 1 e no
    # primeiro do vídeo 2: SUP-092 aceita contar as duas.
    roteiro = cruza(DIREITA, 95, ESQUERDA, 5) + cruza(DIREITA, 5, ESQUERDA, 95)

    resultado = conta(dir_sessao, roteiro)

    assert len(resultado.eventos) == 2
    assert {e.sentido for e in resultado.eventos} == {"CENTRO"}
    assert sorted(e.video for e in resultado.eventos) == [1, 2]


def test_AC_028_7_rastreador_reiniciado_na_troca_de_video(tmp_path):
    dir_sessao = monta_sessao(tmp_path, [(100, True), (100, True)])
    roteiro = cruza(DIREITA, 50, ESQUERDA, 50) + cruza(DIREITA, 50, ESQUERDA, 50)
    criados = []

    def fabrica():
        criados.append(1)
        return ByteTrackDuble()

    resultado = conta(dir_sessao, roteiro, fabrica_de_bytetrack=fabrica)

    assert len(criados) == 2
    ids = [e.id_de_rastreio for e in resultado.eventos]
    assert len(ids) == len(set(ids)) == 2


def test_AC_028_8_minutos_da_sessao_atravessam_os_videos(tmp_path):
    dir_sessao = monta_sessao(tmp_path, [(1300, True), (450, True), (600, True)])
    # Vídeo 1: 130 s (minutos 1 a 3); vídeo 2: 45 s (minuto 4); vídeo 3: 60 s
    # (minuto 5). Um cruzamento a 10 s do vídeo 2 fica no minuto 4.
    roteiro = [None] * 1300 + cruza(DIREITA, 100, ESQUERDA, 350)

    resultado = conta(dir_sessao, roteiro)

    assert resultado.minutos_processados == (1, 2, 3, 4, 5)
    [evento] = resultado.eventos
    assert (evento.video, evento.minuto, evento.deslocamento_segundos) == (2, 4, 10)


def test_AC_028_9_video_que_falha_nao_para_a_sessao(tmp_path):
    dir_sessao = monta_sessao(tmp_path, [(50, True), (50, False), (50, True)])
    roteiro = cruza(DIREITA, 10, ESQUERDA, 40) + cruza(DIREITA, 10, ESQUERDA, 40)
    registro = Registro()

    resultado = conta(dir_sessao, roteiro, **registro.ganchos())

    assert resultado.minutos_processados == (1, 3)
    [sem_dado] = resultado.minutos_nao_processados
    assert sem_dado.minuto == 2
    assert "vídeo 2: original-2.mp4" in sem_dado.motivo
    assert [e.video for e in resultado.eventos] == [1, 3]
    assert ("terminar_video", 2, True) in registro.chamadas
    assert ("terminar_video", 3, False) in registro.chamadas


def test_SUP_094_nenhum_video_legivel_levanta_sessao_sem_clipes_sem_gravar(tmp_path):
    dir_sessao = monta_sessao(tmp_path, [(50, False), (50, False)])

    with pytest.raises(SessaoSemClipes):
        conta(dir_sessao)

    assert not (dir_sessao / NOME_DO_ARQUIVO_DE_EVENTOS).exists()


def test_AC_029_1_parada_entre_videos_cancela_sem_eventos_json(tmp_path):
    dir_sessao = monta_sessao(tmp_path, [(50, True), (50, True)])
    parada = ParadaDuble()
    registro = Registro()
    ganchos = registro.ganchos()
    terminar = ganchos["ao_terminar_video"]

    def terminar_e_pedir(posicao, falhou):
        terminar(posicao, falhou)
        parada.pedida = True

    ganchos["ao_terminar_video"] = terminar_e_pedir

    with pytest.raises(ProcessamentoCancelado):
        conta(dir_sessao, parada=parada, **ganchos)

    assert not (dir_sessao / NOME_DO_ARQUIVO_DE_EVENTOS).exists()
    assert ("iniciar_video", 2) not in registro.chamadas
    # Os vídeos continuam em disco, para reprocessar (AC-029.3).
    assert (dir_sessao / "video-01.mp4").is_file()
    assert (dir_sessao / "video-02.mp4").is_file()


def test_AC_029_1_parada_no_meio_de_um_video_cancela_sem_eventos_json(tmp_path):
    dir_sessao = monta_sessao(tmp_path, [(50, True), (1300, True)])
    parada = ParadaDuble()
    registro = Registro()
    ganchos = registro.ganchos()
    resolver = ganchos["ao_resolver_minuto"]

    def resolver_e_pedir(minuto, com_dado):
        resolver(minuto, com_dado)
        if minuto == 2:  # minuto 1 do vídeo 2 resolvido; o seguinte é cancelado
            parada.pedida = True

    ganchos["ao_resolver_minuto"] = resolver_e_pedir

    with pytest.raises(ProcessamentoCancelado):
        conta(dir_sessao, parada=parada, **ganchos)

    # O vídeo 1 chegou a gravar o eventos.json; o cancelamento o apaga.
    assert not (dir_sessao / NOME_DO_ARQUIVO_DE_EVENTOS).exists()
    assert ("terminar_video", 2, False) not in registro.chamadas


def test_ganchos_de_video_na_ordem(tmp_path):
    dir_sessao = monta_sessao(tmp_path, [(50, True), (50, True)])
    registro = Registro()

    conta(dir_sessao, **registro.ganchos())

    assert registro.chamadas == [
        ("iniciar_video", 1),
        ("iniciar", 1),
        ("resolver", 1, True),
        ("terminar_video", 1, False),
        ("iniciar_video", 2),
        ("iniciar", 2),
        ("resolver", 2, True),
        ("terminar_video", 2, False),
    ]

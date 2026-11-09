"""Persistir a sessão de upload — T-10 de `processamento-upload`.

Critérios cobertos, de `.spec/features/processamento-upload/spec.md`:

- AC-030.1 — origem UPLOAD e os dados de cada vídeo;
- AC-030.4 — o status segue os limites de AC-004.4 a AC-004.6, com os minutos
  sem dado por falha de leitura como minutos perdidos (SUP-095).

Mais SUP-093, SUP-099 e SUP-100, e AC-008.5 (persistir duas vezes não duplica).
Os arquivos de entrada (`upload.json`, `eventos.json`) são construídos com as
classes reais. Tudo em `tmp_path`.
"""

from datetime import datetime, timedelta, timezone

import pytest

from auto_counter.capture.status import StatusDaSessao
from auto_counter.counting.config import Categoria, ConfiguracaoDoProcessamento
from auto_counter.counting.events import Evento, MinutoNaoProcessado, RegistroDeEventos
from auto_counter.storage.connection import conectar
from auto_counter.storage.events import contar_eventos, ler_eventos
from auto_counter.storage.model import OrigemDaSessao, VideoGravado
from auto_counter.storage.persist import EventosAusentesError, persistir_sessao_de_upload
from auto_counter.storage.sessions import ler_sessao
from auto_counter.upload.manifest import (
    RegistroDoUpload,
    VideoDaSessaoDeUpload,
    gravar,
)
from tests.test_storage_persist import ID_CAMERA, SENTIDO_A, VERSAO_DO_MODELO, camera

ID_SESSAO = "000013-20261107T143000Z"
INICIO = datetime(2026, 11, 7, 14, 30, 0, tzinfo=timezone.utc)
FIM = datetime(2026, 11, 7, 14, 41, 30, tzinfo=timezone.utc)


def evento_de_upload(*, video=1, deslocamento=12, minuto=1, id_de_rastreio="1:7"):
    return Evento(
        timestamp=INICIO + timedelta(seconds=deslocamento),
        categoria=Categoria.CARRO,
        sentido=SENTIDO_A,
        id_de_rastreio=id_de_rastreio,
        confianca=0.9,
        minuto=minuto,
        indice_do_frame=120,
        posicao_na_linha=0.5,
        video=video,
        deslocamento_segundos=deslocamento,
    )


def monta(tmp_path, *, minutos=10, sem_dado=(), eventos=None, videos=None):
    """Sessão de upload de `minutos` minutos, num vídeo só (ou nos `videos`)."""
    dir_sessao = tmp_path / "sessions" / ID_SESSAO
    if videos is None:
        videos = (
            VideoDaSessaoDeUpload(
                posicao=1,
                nome_original="unico.mp4",
                arquivo="video-01.mp4",
                duracao_segundos=minutos * 60,
                sha256="a" * 64,
                minuto_inicial=1,
                minuto_final=minutos,
            ),
        )
    gravar(
        dir_sessao,
        RegistroDoUpload(
            id_sessao=ID_SESSAO,
            id_camera=ID_CAMERA,
            duracao_minutos=videos[-1].minuto_final,
            videos=tuple(videos),
        ),
    )
    total = videos[-1].minuto_final
    RegistroDeEventos(
        id_sessao=ID_SESSAO,
        id_camera=ID_CAMERA,
        configuracao=ConfiguracaoDoProcessamento(),
        versao_do_modelo=VERSAO_DO_MODELO,
        minutos_processados=tuple(m for m in range(1, total + 1) if m not in sem_dado),
        minutos_nao_processados=tuple(
            MinutoNaoProcessado(m, "falha de leitura") for m in sem_dado
        ),
        eventos=tuple(eventos if eventos is not None else (evento_de_upload(),)),
    ).gravar(dir_sessao)
    return dir_sessao


def persiste(tmp_path, dir_sessao):
    with conectar(tmp_path) as conexao:
        resumo = persistir_sessao_de_upload(
            conexao, dir_sessao, camera=camera(), inicio=INICIO, fim=FIM
        )
        return resumo, ler_sessao(conexao, ID_SESSAO)


def test_AC_030_1_sessao_de_upload_gravada_com_origem_upload_e_os_videos(tmp_path):
    videos = (
        VideoDaSessaoDeUpload(1, "primeiro.mp4", "video-01.mp4", 130, "a" * 64, 1, 3),
        VideoDaSessaoDeUpload(2, "segundo.mov", "video-02.mov", 45, "b" * 64, 4, 4),
    )
    dir_sessao = monta(tmp_path, videos=videos)

    resumo, sessao = persiste(tmp_path, dir_sessao)

    assert sessao.origem is OrigemDaSessao.UPLOAD
    assert sessao.videos == (
        VideoGravado(1, "primeiro.mp4", 130, "a" * 64, 1, 3),
        VideoGravado(2, "segundo.mov", 45, "b" * 64, 4, 4),
    )
    assert sessao.id_camera == ID_CAMERA
    assert sessao.nome_camera == "Praça Exemplo"
    assert sessao.versao_do_modelo == VERSAO_DO_MODELO
    assert sessao.limiar_de_confianca == 0.35
    assert resumo.eventos_gravados == 1


def test_SUP_093_duracao_pedida_e_real_iguais_a_M(tmp_path):
    dir_sessao = monta(tmp_path, minutos=12)

    _, sessao = persiste(tmp_path, dir_sessao)

    assert sessao.duracao_pedida == sessao.duracao_real == 12
    assert sessao.encerrada_pelo_usuario is False


def test_SUP_100_periodo_e_o_do_processamento(tmp_path):
    dir_sessao = monta(tmp_path)

    _, sessao = persiste(tmp_path, dir_sessao)

    assert sessao.inicio == INICIO
    assert sessao.fim == FIM
    assert sessao.criada_em == INICIO


def test_SUP_099_amostragem_gravada_em_frames_por_segundo(tmp_path):
    dir_sessao = monta(tmp_path)

    _, sessao = persiste(tmp_path, dir_sessao)

    assert sessao.amostragem == 10
    assert sessao.amostragem != ConfiguracaoDoProcessamento().amostragem


def test_AC_030_4_sem_minuto_sem_dado_e_completa(tmp_path):
    _, sessao = persiste(tmp_path, monta(tmp_path, minutos=10))

    assert sessao.status is StatusDaSessao.COMPLETA


def test_AC_030_4_ate_20_porcento_sem_dado_e_degradada(tmp_path):
    _, sessao = persiste(tmp_path, monta(tmp_path, minutos=10, sem_dado=(4, 5)))

    assert sessao.status is StatusDaSessao.DEGRADADA


def test_AC_030_4_acima_de_20_porcento_e_invalida(tmp_path):
    _, sessao = persiste(tmp_path, monta(tmp_path, minutos=10, sem_dado=(4, 5, 6)))

    assert sessao.status is StatusDaSessao.INVALIDA


def test_SUP_095_minutos_perdidos_sao_os_sem_dado_por_falha_de_leitura(tmp_path):
    resumo, sessao = persiste(tmp_path, monta(tmp_path, minutos=10, sem_dado=(4, 5)))

    assert sessao.minutos_perdidos == (4, 5)
    assert sessao.minutos_perdidos_quantidade == 2
    assert resumo.minutos_sem_dado == 2
    assert resumo.minutos_capturados == 8


def test_AC_008_5_persistir_duas_vezes_nao_duplica_eventos_nem_videos(tmp_path):
    dir_sessao = monta(tmp_path)
    persiste(tmp_path, dir_sessao)

    with conectar(tmp_path) as conexao:
        persistir_sessao_de_upload(
            conexao, dir_sessao, camera=camera(), inicio=INICIO, fim=FIM
        )
        sessao = ler_sessao(conexao, ID_SESSAO)
        total = contar_eventos(conexao, ID_SESSAO)

    assert total == 1
    assert len(sessao.videos) == 1


def test_evento_de_upload_gravado_com_video_e_deslocamento(tmp_path):
    dir_sessao = monta(
        tmp_path, eventos=[evento_de_upload(video=1, deslocamento=12)]
    )
    persiste(tmp_path, dir_sessao)

    with conectar(tmp_path) as conexao:
        [lido] = ler_eventos(conexao, ID_SESSAO)

    assert (lido.video, lido.deslocamento) == (1, 12)


def test_sem_eventos_json_a_sessao_de_upload_nao_e_persistida(tmp_path):
    dir_sessao = monta(tmp_path)
    (dir_sessao / "eventos.json").unlink()

    with conectar(tmp_path) as conexao:
        with pytest.raises(EventosAusentesError):
            persistir_sessao_de_upload(
                conexao, dir_sessao, camera=camera(), inicio=INICIO, fim=FIM
            )
        assert ler_sessao(conexao, ID_SESSAO) is None

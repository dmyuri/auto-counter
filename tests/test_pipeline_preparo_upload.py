"""Validação dos arquivos e preparo do diretório da sessão de upload — T-08.

Critérios cobertos, de `.spec/features/processamento-upload/spec.md`:

- AC-028.1 — só entram vídeos válidos e dentro do limite de 15 min somados;
- AC-030.7 — arquivo inválido é recusado antes de qualquer processamento, com
  mensagem que nomeia o arquivo;
- AC-028.8 — o `upload.json` traz os minutos de cada vídeo.

Mais SUP-087, SUP-097 e SUP-098. Os vídeos são gerados em `tmp_path`; nada aqui
toca a rede nem grava fora de `tmp_path`.
"""

import cv2
import numpy as np
import pytest

from auto_counter.pipeline import preparo_upload
from auto_counter.pipeline.envio import diretorio_de_envio
from auto_counter.pipeline.leitura_video import LeituraDoVideo
from auto_counter.pipeline.preparo_upload import (
    ArquivoRecusadoError,
    preparar_sessao,
    triar_arquivos,
    validar_arquivos,
)
from auto_counter.upload.manifest import ler as ler_registro
from tests.test_counting_session import camera

ID_SESSAO = "000013-20261107T143000Z"


def escreve_video(caminho, *, lado=(1280, 720), quadros=20, fps=10):
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


def leitura(duracao, sha="a" * 64):
    return LeituraDoVideo(
        legivel=True, duracao_segundos=duracao, largura=1280, altura=720, sha256=sha
    )


def test_AC_030_7_extensao_recusada_nomeia_o_arquivo(tmp_path):
    arquivo = tmp_path / "x.txt"
    arquivo.write_bytes(b"x")

    with pytest.raises(ArquivoRecusadoError) as erro:
        triar_arquivos([arquivo], ["relatorio.txt"])

    assert str(erro.value).startswith("relatorio.txt: ")
    assert "extensão" in str(erro.value)


def test_AC_030_7_arquivo_acima_de_1_gb_nomeia_o_arquivo(tmp_path, monkeypatch):
    arquivo = tmp_path / "x.mp4"
    arquivo.write_bytes(b"x")
    monkeypatch.setattr(
        preparo_upload, "_tamanho_do_arquivo", lambda caminho: 1_000_000_001
    )

    with pytest.raises(ArquivoRecusadoError) as erro:
        triar_arquivos([arquivo], ["enorme.mp4"])

    assert str(erro.value).startswith("enorme.mp4: ")
    assert "1 GB" in str(erro.value)


def test_AC_030_7_arquivo_inexistente_nomeia_o_arquivo(tmp_path):
    with pytest.raises(ArquivoRecusadoError) as erro:
        triar_arquivos([tmp_path / "nao-existe.mp4"], ["sumiu.mp4"])

    assert str(erro.value).startswith("sumiu.mp4: ")


def test_AC_030_7_o_primeiro_recusado_levanta_na_ordem_da_lista(tmp_path):
    bom = tmp_path / "a.mp4"
    bom.write_bytes(b"x")
    ruim = tmp_path / "b.txt"
    ruim.write_bytes(b"x")

    with pytest.raises(ArquivoRecusadoError) as erro:
        triar_arquivos([bom, ruim], ["a.mp4", "b.txt"])

    assert str(erro.value).startswith("b.txt: ")


def test_AC_030_7_ilegivel_nomeia_o_arquivo(tmp_path):
    arquivo = tmp_path / "quebrado.mp4"
    arquivo.write_bytes(b"isto nao e um video")

    with pytest.raises(ArquivoRecusadoError) as erro:
        validar_arquivos([arquivo], ["quebrado-original.mp4"], camera())

    assert str(erro.value).startswith("quebrado-original.mp4: ")
    assert "vídeo legível" in str(erro.value)
    assert "Inválido" not in str(erro.value)


def test_AC_030_7_resolucao_diferente_da_camera_nomeia_o_arquivo(tmp_path):
    arquivo = escreve_video(tmp_path / "pequeno.mp4", lado=(640, 360))

    with pytest.raises(ArquivoRecusadoError) as erro:
        validar_arquivos([arquivo], ["pequeno.mp4"], camera())

    assert str(erro.value).startswith("pequeno.mp4: ")
    assert "640×360" in str(erro.value)


def test_validar_arquivos_aceita_video_valido_e_devolve_a_leitura(tmp_path):
    arquivo = escreve_video(tmp_path / "ok.mp4", quadros=30, fps=10)

    validacao = validar_arquivos([arquivo], ["ok.mp4"], camera())

    [lida] = validacao.leituras
    assert lida.duracao_segundos == 3
    assert validacao.avisos == ()


def test_AC_028_1_soma_acima_de_15_min_e_recusada(tmp_path, monkeypatch):
    arquivos = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
    for arquivo in arquivos:
        arquivo.write_bytes(b"x")
    monkeypatch.setattr(
        preparo_upload, "ler_video", lambda caminho: leitura(500, str(caminho))
    )

    with pytest.raises(ArquivoRecusadoError) as erro:
        validar_arquivos(arquivos, ["a.mp4", "b.mp4"], camera())

    # O nome é o do último arquivo, o que passou do limite.
    assert str(erro.value).startswith("b.mp4: ")
    assert "15 min" in str(erro.value)


def test_AC_028_1_soma_exatamente_no_limite_e_aceita(tmp_path, monkeypatch):
    arquivos = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
    for arquivo in arquivos:
        arquivo.write_bytes(b"x")
    monkeypatch.setattr(
        preparo_upload, "ler_video", lambda caminho: leitura(450, str(caminho))
    )

    validacao = validar_arquivos(arquivos, ["a.mp4", "b.mp4"], camera())

    assert len(validacao.leituras) == 2


def test_SUP_098_duplicata_passa_com_aviso(tmp_path, monkeypatch):
    arquivos = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
    for arquivo in arquivos:
        arquivo.write_bytes(b"x")
    monkeypatch.setattr(preparo_upload, "ler_video", lambda caminho: leitura(10))

    validacao = validar_arquivos(arquivos, ["a.mp4", "copia-de-a.mp4"], camera())

    assert len(validacao.leituras) == 2
    [aviso] = validacao.avisos
    assert aviso.startswith("copia-de-a.mp4: ")
    assert "a.mp4" in aviso


def prepara(tmp_path, arquivos, nomes, duracoes):
    return preparar_sessao(
        tmp_path,
        id_sessao=ID_SESSAO,
        camera=camera(),
        arquivos=arquivos,
        nomes=nomes,
        leituras=[leitura(d, sha=f"{i}" * 64) for i, d in enumerate(duracoes)],
    )


def test_SUP_097_arquivo_do_envio_e_movido(tmp_path):
    envios = diretorio_de_envio(tmp_path)
    envios.mkdir(parents=True)
    recebido = envios / "abc123.mp4"
    recebido.write_bytes(b"conteudo")

    registro = prepara(tmp_path, [recebido], ["original.MP4"], [30])

    destino = tmp_path / "sessions" / ID_SESSAO / "video-01.mp4"
    assert destino.read_bytes() == b"conteudo"
    assert not recebido.exists()
    assert registro.videos[0].arquivo == "video-01.mp4"
    assert registro.videos[0].nome_original == "original.MP4"


def test_SUP_097_arquivo_de_fora_do_data_dir_e_copiado_e_o_original_fica(tmp_path):
    data_dir = tmp_path / "dados"
    data_dir.mkdir()
    original = tmp_path / "meus-videos" / "clip.mov"
    original.parent.mkdir()
    original.write_bytes(b"do usuario")

    prepara(data_dir, [original], ["clip.mov"], [30])

    assert original.read_bytes() == b"do usuario"
    copia = data_dir / "sessions" / ID_SESSAO / "video-01.mov"
    assert copia.read_bytes() == b"do usuario"


def test_SUP_087_sobras_do_envio_sao_apagadas_ao_preparar(tmp_path):
    envios = diretorio_de_envio(tmp_path)
    envios.mkdir(parents=True)
    usado = envios / "usado.mp4"
    usado.write_bytes(b"a")
    sobra = envios / "sobra.mp4"
    sobra.write_bytes(b"b")

    prepara(tmp_path, [usado], ["usado.mp4"], [30])

    assert list(envios.iterdir()) == []


def test_AC_028_8_upload_json_traz_os_minutos_de_cada_video(tmp_path):
    a = tmp_path / "a.mp4"
    b = tmp_path / "b.mkv"
    a.write_bytes(b"a")
    b.write_bytes(b"b")

    registro = prepara(tmp_path, [a, b], ["a.mp4", "b.mkv"], [130, 45])

    lido = ler_registro(tmp_path / "sessions" / ID_SESSAO)
    assert lido == registro
    assert lido.id_camera == "000013"
    assert lido.duracao_minutos == 4
    assert [(v.posicao, v.minuto_inicial, v.minuto_final) for v in lido.videos] == [
        (1, 1, 3),
        (2, 4, 4),
    ]
    assert [v.duracao_segundos for v in lido.videos] == [130, 45]
    assert [v.sha256 for v in lido.videos] == ["0" * 64, "1" * 64]


def test_preparar_com_falha_no_meio_apaga_o_diretorio_da_sessao(tmp_path):
    a = tmp_path / "a.mp4"
    a.write_bytes(b"a")

    with pytest.raises(OSError):
        prepara(tmp_path, [a, tmp_path / "some.mp4"], ["a.mp4", "b.mp4"], [30, 30])

    assert not (tmp_path / "sessions" / ID_SESSAO).exists()
    assert a.exists()

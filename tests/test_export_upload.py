"""Planilha da sessão de upload — T-11 de `processamento-upload`.

Critérios cobertos, de `.spec/features/processamento-upload/spec.md`:

- AC-030.3 — as três abas, a origem e uma linha por vídeo na aba Sessao, o
  período marcado como "horário do processamento" e o nome do arquivo com
  `_upload` antes do sufixo de status;
- AC-030.4 — o aviso cita os minutos sem dado por falha de leitura;
- AC-030.5 — a aba Eventos traz o nome do vídeo e o deslocamento em MM:SS, sem
  data nem hora do dia.

Mais AC-010.2 (uma linha por evento) e AC-030.1 (a origem também na sessão ao
vivo). O banco vive em `tmp_path`.
"""

from datetime import datetime, timezone

from openpyxl import load_workbook

from auto_counter.capture.status import StatusDaSessao
from auto_counter.export.workbook import exportar_sessao
from auto_counter.storage.connection import conectar
from auto_counter.storage.model import OrigemDaSessao, VideoGravado
from tests.export_helpers import ID_SESSAO, evento, gravar_sessao

INICIO = datetime(2026, 11, 7, 17, 30, 0, tzinfo=timezone.utc)  # 14:30 em Brasília
VIDEOS = (
    VideoGravado(1, "primeiro.mp4", 130, "a" * 64, 1, 3),
    VideoGravado(2, "segundo.mov", 45, "b" * 64, 4, 4),
)
EVENTOS = (
    evento(minuto=1, id_de_rastreio="1:7", video=1, deslocamento=12, segundos=12),
    evento(minuto=4, id_de_rastreio="4:9", video=2, deslocamento=75, segundos=75),
)


def exporta(tmp_path, **campos):
    parametros = dict(
        origem=OrigemDaSessao.UPLOAD,
        videos=VIDEOS,
        eventos=EVENTOS,
        inicio=INICIO,
        duracao_pedida=4,
        amostragem=10,
    )
    parametros.update(campos)
    with conectar(tmp_path) as conexao:
        gravar_sessao(conexao, **parametros)
        return exportar_sessao(conexao, ID_SESSAO, data_dir=tmp_path)


def linhas(aba):
    return [tuple(c.value for c in linha) for linha in aba.iter_rows()]


def test_AC_030_3_planilha_de_upload_tem_as_tres_abas(tmp_path):
    caminho = exporta(tmp_path)

    assert load_workbook(caminho).sheetnames == ["Eventos", "PorMinuto", "Sessao"]


def test_AC_030_3_nome_do_arquivo_com_upload_antes_do_status(tmp_path):
    caminho = exporta(
        tmp_path,
        duracao_pedida=12,
        status=StatusDaSessao.DEGRADADA,
        minutos_perdidos=(5, 6),
    )

    assert caminho.name == "000013_20261107_1430_12min_upload_DEGRADADA.xlsx"


def test_AC_030_3_nome_do_arquivo_completa_sem_sufixo_de_status(tmp_path):
    caminho = exporta(tmp_path, duracao_pedida=12)

    assert caminho.name == "000013_20261107_1430_12min_upload.xlsx"


def test_AC_030_3_aba_sessao_traz_origem_upload_e_uma_linha_por_video(tmp_path):
    aba = load_workbook(exporta(tmp_path))["Sessao"]
    todas = linhas(aba)
    campos = {linha[0]: linha[1] for linha in todas}

    assert campos["origem"] == "UPLOAD"
    # A origem vem logo depois do id da sessão.
    nomes = [linha[0] for linha in todas]
    assert nomes[nomes.index("id da sessão") + 1] == "origem"
    inicio_do_bloco = todas.index(("vídeo", "nome", "duração (MM:SS)", "minutos"))
    assert todas[inicio_do_bloco - 1] == (None, None, None, None)
    assert todas[inicio_do_bloco + 1 :] == [
        (1, "primeiro.mp4", "02:10", "1 a 3"),
        (2, "segundo.mov", "00:45", "4"),
    ]


def test_AC_030_3_periodo_marcado_como_horario_do_processamento(tmp_path):
    aba = load_workbook(exporta(tmp_path))["Sessao"]
    campos = {linha[0]: linha[1] for linha in linhas(aba)}

    assert campos["início (horário do processamento)"] == datetime(2026, 11, 7, 14, 30)
    assert campos["fim (horário do processamento)"] == datetime(2026, 11, 7, 14, 34)
    assert "início real" not in campos
    assert campos["amostragem (frames por segundo de vídeo)"] == 10
    assert "amostragem (1 frame a cada N)" not in campos


def test_AC_030_4_aviso_da_sessao_de_upload_cita_falha_de_leitura(tmp_path):
    caminho = exporta(
        tmp_path,
        duracao_pedida=12,
        status=StatusDaSessao.DEGRADADA,
        minutos_perdidos=(5, 6),
        videos=(VideoGravado(1, "unico.mp4", 720, "a" * 64, 1, 12),),
        eventos=(),
    )

    pasta = load_workbook(caminho)
    for aba in pasta.worksheets:
        assert aba["A1"].value == (
            "ATENÇÃO: sessão DEGRADADA — 2 de 12 minutos sem dado por falha de "
            "leitura (16,7%)"
        )
    campos = {linha[0]: linha[1] for linha in linhas(pasta["Sessao"])}
    assert campos["minutos sem dado (falha de leitura)"] == "5, 6"
    assert "minutos perdidos" not in campos


def test_AC_030_5_aba_eventos_traz_nome_do_video_e_deslocamento_mm_ss(tmp_path):
    aba = load_workbook(exporta(tmp_path))["Eventos"]
    todas = linhas(aba)

    assert todas[0] == (
        "vídeo",
        "deslocamento (MM:SS)",
        "categoria",
        "sentido",
        "id de rastreio",
        "confiança",
    )
    assert todas[1][:2] == ("primeiro.mp4", "00:12")
    assert todas[2][:2] == ("segundo.mov", "01:15")


def test_AC_030_5_aba_eventos_do_upload_nao_tem_data_nem_hora(tmp_path):
    aba = load_workbook(exporta(tmp_path))["Eventos"]

    for linha in aba.iter_rows():
        for celula in linha:
            assert not isinstance(celula.value, datetime)
    assert all("timestamp" not in str(c.value) for c in aba[1])


def test_AC_010_2_upload_tem_uma_linha_por_evento_gravado(tmp_path):
    aba = load_workbook(exporta(tmp_path))["Eventos"]

    assert aba.max_row == 1 + len(EVENTOS)


def test_AC_030_1_sessao_ao_vivo_traz_origem_camera_na_aba_sessao(tmp_path):
    with conectar(tmp_path) as conexao:
        gravar_sessao(conexao)
        caminho = exportar_sessao(conexao, ID_SESSAO, data_dir=tmp_path)

    aba = load_workbook(caminho)["Sessao"]
    campos = {linha[0]: linha[1] for linha in linhas(aba)}
    assert campos["origem"] == "CAMERA"
    assert "início real" in campos
    assert "minutos perdidos" in campos
    assert "_upload" not in caminho.name
    # A sessão ao vivo não ganha o bloco de vídeos.
    assert ("vídeo", "nome", "duração (MM:SS)", "minutos") not in linhas(aba)

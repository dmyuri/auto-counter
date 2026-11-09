"""Registro em disco da sessão de upload (`upload.json`) — T-03.

Critérios cobertos, de `.spec/features/processamento-upload/spec.md`:

- AC-028.8 — os minutos da sessão são numerados em sequência através dos
  vídeos (D-3);
- AC-030.1 — o registro guarda nome original, posição, duração, sha256 e
  minutos de cada vídeo;
- AC-030.6 — o descarte apaga só os arquivos listados (SUP-097, D-7).
"""

import json

import pytest

from auto_counter.upload.manifest import (
    NOME_DO_REGISTRO,
    RegistroDoUpload,
    VideoDaSessaoDeUpload,
    apagar_videos,
    e_sessao_de_upload,
    gravar,
    ler,
    nome_do_arquivo_do_video,
    numerar_minutos,
)


def _video(posicao: int, arquivo: str, inicial: int, final: int, **extra):
    campos = {
        "posicao": posicao,
        "nome_original": f"original-{posicao}.mp4",
        "arquivo": arquivo,
        "duracao_segundos": 60,
        "sha256": "a" * 64,
        "minuto_inicial": inicial,
        "minuto_final": final,
    }
    campos.update(extra)
    return VideoDaSessaoDeUpload(**campos)


def test_AC_028_8_minutos_numerados_em_sequencia_atraves_dos_videos():
    assert numerar_minutos([130, 45, 60]) == ((1, 3), (4, 4), (5, 5))


def test_AC_028_8_video_de_exatamente_60_s_ocupa_um_minuto():
    assert numerar_minutos([60, 60]) == ((1, 1), (2, 2))


def test_D_3_video_de_duracao_zero_ocupa_um_minuto():
    assert numerar_minutos([0, 10]) == ((1, 1), (2, 2))


def test_D_3_duracao_negativa_e_recusada():
    with pytest.raises(ValueError):
        numerar_minutos([10, -1])


def test_SUP_093_soma_dos_minutos_pode_passar_de_15_com_videos_curtos():
    faixas = numerar_minutos([40] * 20)

    assert sum(f - i + 1 for i, f in faixas) == 20
    assert faixas[-1][1] == 20


def test_AC_030_1_registro_ida_e_volta_com_nome_posicao_duracao_sha256_e_minutos(
    tmp_path,
):
    original = RegistroDoUpload(
        id_sessao="000013-20261107T143000Z",
        id_camera="000013",
        duracao_minutos=4,
        videos=(
            _video(1, "video-01.mp4", 1, 3, duracao_segundos=130, sha256="b" * 64),
            _video(2, "video-02.mov", 4, 4, duracao_segundos=45),
        ),
    )

    caminho = gravar(tmp_path, original)

    assert caminho == tmp_path / NOME_DO_REGISTRO == tmp_path / "upload.json"
    assert ler(tmp_path) == original
    gravado = json.loads(caminho.read_text(encoding="utf-8"))
    assert gravado["versao"] == 1
    assert gravado["videos"][0]["nome_original"] == "original-1.mp4"
    assert gravado["videos"][0]["sha256"] == "b" * 64
    assert sorted(p.name for p in tmp_path.iterdir()) == ["upload.json"]


def test_registro_com_duracao_que_nao_bate_com_os_minutos_e_recusado():
    with pytest.raises(ValueError):
        RegistroDoUpload(
            id_sessao="s",
            id_camera="000013",
            duracao_minutos=9,
            videos=(_video(1, "video-01.mp4", 1, 3),),
        )


def test_SUP_097_nome_do_arquivo_do_video_tem_posicao_e_extensao_minuscula():
    assert nome_do_arquivo_do_video(1, ".MP4") == "video-01.mp4"
    assert nome_do_arquivo_do_video(12, ".mkv") == "video-12.mkv"


def test_AC_030_6_apagar_videos_apaga_so_os_listados(tmp_path):
    registro = RegistroDoUpload(
        id_sessao="s",
        id_camera="000013",
        duracao_minutos=2,
        videos=(
            _video(1, "video-01.mov", 1, 1),
            _video(2, "video-02.mkv", 2, 2),
        ),
    )
    gravar(tmp_path, registro)
    for nome in ("video-01.mov", "video-02.mkv", "outro.mp4"):
        (tmp_path / nome).write_bytes(b"x")

    assert apagar_videos(tmp_path) == 2
    assert sorted(p.name for p in tmp_path.iterdir()) == ["outro.mp4", "upload.json"]
    # Arquivo já ausente não é erro.
    assert apagar_videos(tmp_path) == 0


def test_e_sessao_de_upload_distingue_pelo_upload_json(tmp_path):
    assert e_sessao_de_upload(tmp_path) is False

    gravar(
        tmp_path,
        RegistroDoUpload(
            id_sessao="s",
            id_camera="000013",
            duracao_minutos=1,
            videos=(_video(1, "video-01.mp4", 1, 1),),
        ),
    )

    assert e_sessao_de_upload(tmp_path) is True

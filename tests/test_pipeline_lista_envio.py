"""Avaliação da lista de envio, dos totais e do botão (regra pura).

Critérios de `.spec/features/upload-videos/spec.md`: AC-027.3 a AC-027.9 e
AC-027.11, SUP-085 (duplicata), R-3 e as decisões D-7, D-8 e D-9. Também
AC-026.2 (aviso da câmera), AC-013.1 (outra sessão) e AC-011.3 (sem câmera).

Nenhum vídeo é decodificado: cada item traz um `Future` já resolvido, ou
pendente, com uma `LeituraDoVideo` escolhida pelo teste.
"""

from concurrent.futures import Future
from pathlib import Path

from auto_counter.cameras.model import Camera
from auto_counter.pipeline.lista_envio import (
    LIMITE_DE_DURACAO_SEGUNDOS,
    ItemDoEnvio,
    Situacao,
    aviso_da_camera,
    avaliar_envio,
)
from auto_counter.pipeline.leitura_video import LeituraDoVideo


def camera(id="000013", nome="Praça Getúlio Vargas", largura=1280, altura=720):
    return Camera(
        id=id,
        nome=nome,
        sentido_a="A",
        sentido_b="B",
        linha={"p1": {"x": 10, "y": 10}, "p2": {"x": 100, "y": 100}},
        resolucao={"largura": largura, "altura": altura},
    )


CAMERA_720P = camera()
CAMERA_1080P = camera(id="000012", nome="Praia x Mariz Barros", largura=1920, altura=1080)


def leitura(duracao=10, largura=1280, altura=720, sha="h"):
    return LeituraDoVideo(
        legivel=True,
        duracao_segundos=duracao,
        largura=largura,
        altura=altura,
        sha256=sha,
    )


ILEGIVEL = LeituraDoVideo(
    legivel=False, duracao_segundos=None, largura=None, altura=None, sha256=None
)


def resolvido(valor: LeituraDoVideo) -> "Future[LeituraDoVideo]":
    futuro: Future = Future()
    futuro.set_result(valor)
    return futuro


def pendente() -> "Future[LeituraDoVideo]":
    return Future()


def item(id, nome="v.mp4", tamanho=1_000_000, lido=None):
    return ItemDoEnvio(
        id=id,
        nome=nome,
        tamanho=tamanho,
        caminho=Path(f"{id}.mp4"),
        leitura=pendente() if lido is None else resolvido(lido),
    )


def test_AC_027_3_linha_mostra_nome_duracao_e_tamanho():
    avaliacao = avaliar_envio(
        [item("1", "trecho.mp4", 12_340_000, leitura(duracao=75))], CAMERA_720P
    )

    (linha,) = avaliacao.linhas
    assert linha.id == "1"
    assert linha.nome == "trecho.mp4"
    assert linha.duracao == "01:15"
    assert linha.tamanho == "12,3 MB"
    assert linha.situacao is Situacao.VALIDO
    assert linha.motivo is None
    assert linha.aviso is None


def test_AC_027_3_totais_somam_so_os_validos():
    itens = [
        item("1", tamanho=10_000_000, lido=leitura(duracao=60, sha="a")),
        item("2", tamanho=20_000_000, lido=leitura(duracao=30, sha="b")),
        item("3", tamanho=99_000_000, lido=ILEGIVEL),
    ]

    avaliacao = avaliar_envio(itens, CAMERA_720P)

    assert avaliacao.totais == "2 vídeos · 30,0 MB"
    assert avaliacao.duracao_total == "duração total 01:30"


def test_AC_027_3_um_video_usa_o_singular():
    avaliacao = avaliar_envio([item("1", lido=leitura())], CAMERA_720P)

    assert avaliacao.totais.startswith("1 vídeo · ")
    assert "vídeos" not in avaliacao.totais


def test_AC_027_4_ilegivel_fica_invalido_com_motivo_e_fora_dos_totais():
    avaliacao = avaliar_envio([item("1", lido=ILEGIVEL)], CAMERA_720P)

    (linha,) = avaliacao.linhas
    assert linha.situacao is Situacao.INVALIDO
    assert linha.motivo == "Inválido: o arquivo não abre como vídeo legível."
    assert avaliacao.totais is None
    assert avaliacao.duracao_total is None


def test_AC_027_5_resolucao_diferente_fica_invalida_citando_as_duas():
    avaliacao = avaliar_envio(
        [item("1", lido=leitura(largura=1920, altura=1080))], CAMERA_720P
    )

    (linha,) = avaliacao.linhas
    assert linha.situacao is Situacao.INVALIDO
    assert "1920×1080" in linha.motivo
    assert "1280×720" in linha.motivo
    assert "000013" in linha.motivo
    assert avaliacao.totais is None


def test_AC_027_6_trocar_a_camera_reavalia_a_lista():
    itens = [
        item("1", lido=leitura(largura=1280, altura=720, sha="a")),
        item("2", lido=leitura(largura=1920, altura=1080, sha="b")),
    ]

    na_720 = avaliar_envio(itens, CAMERA_720P)
    na_1080 = avaliar_envio(itens, CAMERA_1080P)

    assert [linha.situacao for linha in na_720.linhas] == [
        Situacao.VALIDO,
        Situacao.INVALIDO,
    ]
    assert [linha.situacao for linha in na_1080.linhas] == [
        Situacao.INVALIDO,
        Situacao.VALIDO,
    ]


def test_AC_027_7_duplicata_continua_valida_e_cita_o_nome_igual():
    itens = [
        item("1", "original.mp4", lido=leitura(sha="x")),
        item("2", "copia.mp4", lido=leitura(sha="x")),
    ]

    avaliacao = avaliar_envio(itens, CAMERA_720P)

    original, copia = avaliacao.linhas
    assert original.aviso is None
    assert copia.situacao is Situacao.VALIDO
    assert copia.aviso == "Duplicata de original.mp4: o conteúdo é idêntico."
    assert avaliacao.totais.startswith("2 vídeos")


def test_AC_027_7_duplicata_compara_com_toda_a_lista():
    itens = [
        item("1", "A.mp4", lido=leitura(sha="a")),
        item("2", "B.mp4", lido=leitura(sha="b")),
        item("3", "A_copia.mp4", lido=leitura(sha="a")),
    ]

    avaliacao = avaliar_envio(itens, CAMERA_720P)

    assert avaliacao.linhas[2].aviso == "Duplicata de A.mp4: o conteúdo é idêntico."
    assert avaliacao.linhas[1].aviso is None


def test_SUP_085_nome_igual_com_conteudo_diferente_nao_e_duplicata():
    itens = [
        item("1", "mesmo.mp4", lido=leitura(sha="a")),
        item("2", "mesmo.mp4", lido=leitura(sha="b")),
    ]

    avaliacao = avaliar_envio(itens, CAMERA_720P)

    assert all(linha.aviso is None for linha in avaliacao.linhas)


def test_AC_027_8_sem_o_original_o_aviso_da_duplicata_some():
    original = item("1", "original.mp4", lido=leitura(sha="x"))
    copia = item("2", "copia.mp4", lido=leitura(sha="x"))

    com_os_dois = avaliar_envio([original, copia], CAMERA_720P)
    sem_o_original = avaliar_envio([copia], CAMERA_720P)

    assert com_os_dois.linhas[1].aviso is not None
    assert sem_o_original.linhas[0].aviso is None


def test_AC_027_9_sem_validos_importe_videos_indisponivel():
    vazia = avaliar_envio([], CAMERA_720P)
    so_invalidos = avaliar_envio([item("1", lido=ILEGIVEL)], CAMERA_720P)

    for avaliacao in (vazia, so_invalidos):
        assert avaliacao.texto_do_botao == "Importe vídeos para iniciar"
        assert avaliacao.botao_disponivel is False


def test_AC_027_9_com_leitura_pendente_lendo_videos_indisponivel():
    so_pendente = avaliar_envio([item("1")], CAMERA_720P)
    com_valido = avaliar_envio(
        [item("1", lido=leitura(sha="a")), item("2")], CAMERA_720P
    )

    for avaliacao in (so_pendente, com_valido):
        assert avaliacao.texto_do_botao == "Lendo vídeos…"
        assert avaliacao.botao_disponivel is False

    (linha,) = so_pendente.linhas
    assert linha.situacao is Situacao.LENDO
    assert linha.duracao is None


def test_AC_027_9_processar_1_video_e_processar_n_videos():
    um = avaliar_envio([item("1", lido=leitura(sha="a"))], CAMERA_720P)
    tres = avaliar_envio(
        [item(str(i), lido=leitura(sha=str(i))) for i in range(3)], CAMERA_720P
    )

    assert um.texto_do_botao == "Processar 1 vídeo"
    assert um.botao_disponivel is True
    assert tres.texto_do_botao == "Processar 3 vídeos"
    assert tres.botao_disponivel is True


def test_AC_027_11_soma_acima_de_900_s_indisponivel_com_mensagem():
    itens = [
        item("1", lido=leitura(duracao=899, sha="a")),
        item("2", lido=leitura(duracao=2, sha="b")),
    ]

    avaliacao = avaliar_envio(itens, CAMERA_720P)

    assert avaliacao.botao_disponivel is False
    assert avaliacao.texto_do_botao == "Processar 2 vídeos"
    assert "15 min" in avaliacao.aviso_do_limite
    assert "15:01" in avaliacao.aviso_do_limite


def test_AC_027_11_exatamente_900_s_continua_disponivel():
    assert LIMITE_DE_DURACAO_SEGUNDOS == 900

    avaliacao = avaliar_envio(
        [item("1", lido=leitura(duracao=900))], CAMERA_720P
    )

    assert avaliacao.botao_disponivel is True
    assert avaliacao.aviso_do_limite is None


def test_AC_013_1_outra_sessao_deixa_o_botao_indisponivel():
    itens = [item("1", lido=leitura())]

    avaliacao = avaliar_envio(itens, CAMERA_720P, outra_sessao_em_andamento=True)

    assert avaliacao.texto_do_botao == "Processar 1 vídeo"
    assert avaliacao.botao_disponivel is False


def test_AC_011_3_sem_camera_nenhum_video_e_valido():
    avaliacao = avaliar_envio([item("1", lido=leitura())], None)

    (linha,) = avaliacao.linhas
    assert linha.situacao is Situacao.INVALIDO
    assert linha.motivo == "Inválido: selecione a câmera dos vídeos."
    assert avaliacao.botao_disponivel is False
    assert avaliacao.totais is None


def test_AC_026_2_aviso_cita_id_e_nome_da_camera():
    assert (
        aviso_da_camera(CAMERA_720P)
        == "Envie apenas vídeos gravados pela 000013 · Praça Getúlio Vargas."
    )

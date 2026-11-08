"""Interface: envio, lista e remoção dos vídeos — upload-videos.

Critérios cobertos, de `.spec/features/upload-videos/spec.md`: AC-026.3,
AC-026.4 (a lista fica de fora da sessão ao vivo), AC-026.5 (remover travado),
AC-027.1 a AC-027.8 e AC-027.10, na tela.

`iniciar_leitura` é trocado por um dublê que devolve um `Future` já resolvido
com a leitura escolhida pelo teste, então nenhum vídeo é decodificado. Os
arquivos enviados são bytes quaisquer, gravados em `tmp_path` pelo
`pipeline/envio.py` de verdade. Nada aqui toca a rede ou abre navegador.
"""

import hashlib
from concurrent.futures import Future

import pytest
import streamlit

from auto_counter.pipeline.clipes import formatar_megabytes
from auto_counter.pipeline.leitura_video import LeituraDoVideo
from tests.test_ui_acompanhamento import (  # noqa: F401  (fixtures usadas por nome)
    captura_em_curso,
    data_dir,
    textos,
    trava_do_run,
)
from tests.test_ui_formulario import (  # noqa: F401  (fixtures usadas por nome)
    abre_a_interface,
    ambiente,
    disparo,
    registro_com,
)


class Leituras:
    """Dublê de `iniciar_leitura`: lê os bytes gravados e devolve um `Future`."""

    def __init__(self):
        self.por_conteudo: dict[bytes, LeituraDoVideo] = {}

    def leitura(self, conteudo: bytes) -> LeituraDoVideo:
        return self.por_conteudo.get(conteudo) or LeituraDoVideo(
            legivel=True,
            duracao_segundos=75,
            largura=1280,
            altura=720,
            sha256=hashlib.sha256(conteudo).hexdigest(),
        )

    def iniciar(self, caminho) -> "Future[LeituraDoVideo]":
        futuro: Future = Future()
        futuro.set_result(self.leitura(caminho.read_bytes()))
        return futuro


@pytest.fixture
def leituras(monkeypatch) -> Leituras:
    duble = Leituras()
    monkeypatch.setattr(
        "auto_counter.pipeline.leitura_video.iniciar_leitura", duble.iniciar
    )
    return duble


ILEGIVEL = LeituraDoVideo(
    legivel=False, duracao_segundos=None, largura=None, altura=None, sha256=None
)


def video(nome: str, conteudo: bytes):
    return (nome, conteudo, "video/mp4")


def abre_o_upload(tmp_path, monkeypatch, *cameras: str):
    registro_com(tmp_path, monkeypatch, *(cameras or ("valida_000013.yaml",)))
    at = abre_a_interface()
    next(r for r in at.radio if r.key == "fonte").set_value("upload")
    return at.run()


def envia(at, *arquivos):
    at.file_uploader[0].set_value(list(arquivos))
    return at.run()


def muda_a_fonte(at, valor: str):
    next(r for r in at.radio if r.key == "fonte").set_value(valor)
    return at.run()


def nomes_na_lista(at) -> list[str]:
    return [m.value.strip("*") for m in at.markdown if m.value.startswith("**")
            and m.value.endswith("**") and "." in m.value]


def botoes_remover(at) -> list:
    return [b for b in at.button if (b.key or "").startswith("remover_")]


def avisos(at) -> list[str]:
    return [w.value for w in at.warning]


def erros(at) -> list[str]:
    return [e.value for e in at.error]


def legendas(at) -> list[str]:
    return [c.value for c in at.caption]


def test_AC_027_1_varios_arquivos_entram_na_ordem_recebida(
    tmp_path, monkeypatch, leituras
):
    at = abre_o_upload(tmp_path, monkeypatch)

    at = envia(at, video("b.mp4", b"1"), video("A.MOV", b"2"), video("c.mkv", b"3"))

    assert not at.exception
    assert nomes_na_lista(at) == ["b.mp4", "A.MOV", "c.mkv"]
    assert len(botoes_remover(at)) == 3


def test_AC_027_1_arquivo_aceito_e_gravado_no_diretorio_de_envio(
    tmp_path, monkeypatch, leituras
):
    at = abre_o_upload(tmp_path, monkeypatch)

    envia(at, video("trecho.mp4", b"conteudo do video"))

    gravados = list((tmp_path / "data" / "envios").iterdir())
    assert len(gravados) == 1
    assert gravados[0].suffix == ".mp4"
    assert gravados[0].read_bytes() == b"conteudo do video"


def test_AC_027_2_extensao_recusada_mostra_nome_e_extensoes_e_nao_entra(
    tmp_path, monkeypatch, leituras
):
    at = abre_o_upload(tmp_path, monkeypatch)

    at = envia(at, video("ok.mp4", b"1"), video("filme.webm", b"2"))

    mensagens = [a for a in avisos(at) if "filme.webm" in a]
    assert len(mensagens) == 1
    for extensao in (".mp4", ".mov", ".avi", ".mkv"):
        assert extensao in mensagens[0]
    assert nomes_na_lista(at) == ["ok.mp4"]
    # a recusa não é gravada em disco
    assert len(list((tmp_path / "data" / "envios").iterdir())) == 1


def test_AC_027_10_acima_de_1_gb_mostra_nome_e_limite_e_nao_entra(
    tmp_path, monkeypatch, leituras
):
    class ArquivoGrande:
        name = "enorme.mp4"
        size = 1_000_000_001

    entregues = [[ArquivoGrande()]]

    def uploader_duble(*args, **kwargs):
        return entregues.pop() if entregues else []

    at = abre_o_upload(tmp_path, monkeypatch)
    monkeypatch.setattr(streamlit, "file_uploader", uploader_duble)

    at = at.run()

    mensagens = [a for a in avisos(at) if "enorme.mp4" in a]
    assert len(mensagens) == 1
    assert "1 GB" in mensagens[0]
    assert nomes_na_lista(at) == []
    assert not (tmp_path / "data" / "envios").exists()


def test_AC_027_3_linha_e_totais_aparecem_depois_da_leitura(
    tmp_path, monkeypatch, leituras
):
    at = abre_o_upload(tmp_path, monkeypatch)
    conteudo_a, conteudo_b = b"a" * 1500, b"b" * 2500

    at = envia(at, video("a.mp4", conteudo_a), video("b.mp4", conteudo_b))

    legenda = legendas(at)
    assert legenda.count("01:15") == 2
    assert formatar_megabytes(len(conteudo_a)) in legenda
    assert formatar_megabytes(len(conteudo_b)) in legenda
    assert f"2 vídeos · {formatar_megabytes(4000)}" in legenda
    assert "duração total 02:30" in legenda


def test_AC_027_4_ilegivel_aparece_invalido_com_motivo(
    tmp_path, monkeypatch, leituras
):
    leituras.por_conteudo[b"quebrado"] = ILEGIVEL
    at = abre_o_upload(tmp_path, monkeypatch)

    at = envia(at, video("quebrado.mp4", b"quebrado"), video("bom.mp4", b"bom"))

    assert "Inválido: o arquivo não abre como vídeo legível." in erros(at)
    assert "1 vídeo · " in "\n".join(legendas(at))
    assert "duração total 01:15" in legendas(at)


def test_AC_027_5_resolucao_diferente_aparece_invalida(
    tmp_path, monkeypatch, leituras
):
    leituras.por_conteudo[b"full-hd"] = LeituraDoVideo(
        legivel=True, duracao_segundos=30, largura=1920, altura=1080, sha256="x"
    )
    at = abre_o_upload(tmp_path, monkeypatch)

    at = envia(at, video("full.mp4", b"full-hd"))

    (motivo,) = erros(at)
    assert "1920×1080" in motivo
    assert "1280×720" in motivo
    assert "000013" in motivo
    assert not [c for c in legendas(at) if c.startswith("duração total")]


def test_AC_027_6_trocar_de_camera_atualiza_aviso_e_validade(
    tmp_path, monkeypatch, leituras
):
    at = abre_o_upload(tmp_path, monkeypatch, "valida_000013.yaml", "valida_000042.yaml")
    outra = tmp_path / "cameras" / "valida_000042.yaml"
    outra.write_text(
        outra.read_text(encoding="utf-8").replace(
            "resolucao: {largura: 1280, altura: 720}",
            "resolucao: {largura: 1920, altura: 1080}",
        ),
        encoding="utf-8",
    )
    at = at.run()
    at = envia(at, video("a.mp4", b"a"))
    assert erros(at) == []
    assert any("000013" in i.value and "Envie apenas" in i.value for i in at.info)

    next(b for b in at.button if b.key == "camera_000042").click()
    at = at.run()

    assert any("000042" in i.value and "Envie apenas" in i.value for i in at.info)
    (motivo,) = erros(at)
    assert "1280×720" in motivo
    assert "1920×1080" in motivo
    assert "000042" in motivo


def test_AC_027_7_duplicata_aparece_com_aviso(tmp_path, monkeypatch, leituras):
    at = abre_o_upload(tmp_path, monkeypatch)

    at = envia(at, video("original.mp4", b"mesmo"), video("copia.mp4", b"mesmo"))

    assert avisos(at) == ["Duplicata de original.mp4: o conteúdo é idêntico."]
    assert erros(at) == []
    assert len(botoes_remover(at)) == 2
    assert "2 vídeos · " in "\n".join(legendas(at))


def test_AC_027_8_remover_tira_da_lista_e_dos_totais(tmp_path, monkeypatch, leituras):
    at = abre_o_upload(tmp_path, monkeypatch)
    at = envia(at, video("a.mp4", b"a"), video("b.mp4", b"b"))
    arquivos_antes = sorted((tmp_path / "data" / "envios").iterdir())

    botoes_remover(at)[0].click()
    at = at.run()

    assert nomes_na_lista(at) == ["b.mp4"]
    assert "1 vídeo · " in "\n".join(legendas(at))
    assert "duração total 01:15" in legendas(at)
    # remover não apaga o arquivo do disco (D-4)
    assert sorted((tmp_path / "data" / "envios").iterdir()) == arquivos_antes


def test_AC_027_8_remover_o_par_tira_o_aviso_da_duplicata(
    tmp_path, monkeypatch, leituras
):
    at = abre_o_upload(tmp_path, monkeypatch)
    at = envia(at, video("original.mp4", b"mesmo"), video("copia.mp4", b"mesmo"))
    assert len(avisos(at)) == 1

    botoes_remover(at)[0].click()
    at = at.run()

    assert nomes_na_lista(at) == ["copia.mp4"]
    assert avisos(at) == []


def test_AC_026_3_ir_ao_vivo_e_voltar_mantem_a_lista_e_a_ordem(
    tmp_path, monkeypatch, leituras
):
    at = abre_o_upload(tmp_path, monkeypatch)
    at = envia(at, video("z.mp4", b"1"), video("a.mp4", b"2"), video("m.mp4", b"3"))

    at = muda_a_fonte(at, "camera")
    assert nomes_na_lista(at) == []
    at = muda_a_fonte(at, "upload")

    assert nomes_na_lista(at) == ["z.mp4", "a.mp4", "m.mp4"]


def test_AC_026_4_lista_nao_entra_na_sessao_ao_vivo(
    tmp_path, monkeypatch, leituras, disparo
):
    at = abre_o_upload(tmp_path, monkeypatch)
    at = envia(at, video("a.mp4", b"a"), video("b.mp4", b"b"))

    at = muda_a_fonte(at, "camera")
    next(b for b in at.button if b.label == "Iniciar sessão").click()
    at = at.run()

    assert len(disparo.chamadas) == 1
    (id_camera, minutos, _data_dir, _config_dir, manter_videos) = disparo.chamadas[0]
    assert (id_camera, minutos, manter_videos) == ("000013", 15, False)
    at = muda_a_fonte(at, "upload")
    assert nomes_na_lista(at) == ["a.mp4", "b.mp4"]


def test_AC_026_5_remover_fica_indisponivel_com_sessao_em_andamento(
    data_dir, leituras
):
    at = abre_a_interface()
    next(r for r in at.radio if r.key == "fonte").set_value("upload")
    at = at.run()
    at = envia(at, video("a.mp4", b"a"))
    assert botoes_remover(at)[0].disabled is False

    captura_em_curso(data_dir)
    with trava_do_run(data_dir):
        at = at.run()

    assert nomes_na_lista(at) == ["a.mp4"]
    assert all(b.disabled for b in botoes_remover(at))


def test_D_6_leitura_pendente_mostra_lendo_na_linha_sem_duracao(
    tmp_path, monkeypatch, leituras
):
    pendente: Future = Future()
    monkeypatch.setattr(
        "auto_counter.pipeline.leitura_video.iniciar_leitura", lambda caminho: pendente
    )
    at = abre_o_upload(tmp_path, monkeypatch)

    at = envia(at, video("a.mp4", b"a"))

    assert not at.exception
    assert nomes_na_lista(at) == ["a.mp4"]
    assert "lendo…" in legendas(at)
    assert not [c for c in legendas(at) if c.startswith("duração total")]

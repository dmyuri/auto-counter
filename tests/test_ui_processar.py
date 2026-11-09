"""Interface: o clique em "Processar N vídeos" dispara a sessão — T-16.

Critérios cobertos, de `.spec/features/processamento-upload/spec.md`: AC-028.1
na tela (só os vídeos válidos entram, na ordem da lista, com a câmera
selecionada) e AC-028.2 (com outra sessão em andamento, nada é disparado), mais
a nota de AC-023.6 de `upload-videos`: o disparo confirmado consome a lista da
aba, e o recusado a mantém com o motivo.

`launch.iniciar_upload` e `launch.aguardar_inicio` são trocados por um dublê e
`iniciar_leitura` devolve leituras prontas, então nenhum comando roda e nenhum
vídeo é decodificado. Os arquivos enviados são bytes quaisquer, gravados em
`tmp_path`. Nada aqui toca a rede ou abre navegador.
"""

from datetime import datetime, timezone

import pytest

from auto_counter.pipeline import launch
from auto_counter.pipeline.lock import InfoDaTrava, OutraSessaoEmAndamentoError
from tests.test_ui_envio import (  # noqa: F401  (fixtures usadas por nome)
    ILEGIVEL,
    abre_o_upload,
    botao_processar,
    envia,
    erros,
    leituras,
    nomes_na_lista,
    video,
)
from tests.test_ui_formulario import (  # noqa: F401  (fixtures usadas por nome)
    abre_a_interface,
    ambiente,
    botao_iniciar,
    disparo,
    registro_com,
)


class DisparoDeUploadDuble:
    """Dublê de `launch.iniciar_upload` e de `launch.aguardar_inicio`."""

    def __init__(self):
        self.chamadas = []
        self.esperas = []
        self.problema = None
        self.falha = None

    def iniciar(self, id_camera, arquivos, nomes, *, data_dir, config_dir, **_):
        if self.falha is not None:
            raise self.falha
        self.chamadas.append((id_camera, list(arquivos), list(nomes)))
        return object()

    def aguardar(self, disparada, **opcoes):
        self.esperas.append(opcoes)
        return self.problema


@pytest.fixture
def disparo_de_upload(monkeypatch) -> DisparoDeUploadDuble:
    duble = DisparoDeUploadDuble()
    monkeypatch.setattr(launch, "iniciar_upload", duble.iniciar)
    monkeypatch.setattr(launch, "aguardar_inicio", duble.aguardar)
    return duble


def clica_em_processar(at):
    botao_processar(at).click()
    return at.run()


def test_AC_028_1_processar_dispara_com_a_camera_e_so_os_validos_na_ordem(
    tmp_path, monkeypatch, leituras, disparo_de_upload
):
    leituras.por_conteudo[b"quebrado"] = ILEGIVEL
    at = abre_o_upload(tmp_path, monkeypatch)
    at = envia(
        at, video("a.mp4", b"a"), video("b.mp4", b"quebrado"), video("c.mp4", b"c")
    )
    assert botao_processar(at).label == "Processar 2 vídeos"

    at = clica_em_processar(at)

    assert not at.exception
    assert len(disparo_de_upload.chamadas) == 1
    id_camera, arquivos, nomes = disparo_de_upload.chamadas[0]
    assert id_camera == "000013"
    assert nomes == ["a.mp4", "c.mp4"]
    assert [arquivo.read_bytes() for arquivo in arquivos] == [b"a", b"c"]
    assert all(arquivo.parent == tmp_path / "data" / "envios" for arquivo in arquivos)
    # A espera pelo início reconhece a trava do comando de upload.
    assert disparo_de_upload.esperas == [{"comando": "upload"}]


def test_AC_028_1_disparo_confirmado_esvazia_a_lista_da_aba(
    tmp_path, monkeypatch, leituras, disparo_de_upload
):
    at = abre_o_upload(tmp_path, monkeypatch)
    at = envia(at, video("a.mp4", b"a"), video("b.mp4", b"b"))
    assert nomes_na_lista(at) == ["a.mp4", "b.mp4"]

    at = clica_em_processar(at)

    assert not at.exception
    assert nomes_na_lista(at) == []
    assert botao_processar(at).label == "Importe vídeos para iniciar"
    assert botao_processar(at).disabled is True


def test_AC_028_1_disparo_recusado_mantem_a_lista_e_mostra_o_motivo(
    tmp_path, monkeypatch, leituras, disparo_de_upload
):
    disparo_de_upload.problema = "erro: o modelo não foi encontrado"
    at = abre_o_upload(tmp_path, monkeypatch)
    at = envia(at, video("a.mp4", b"a"))

    at = clica_em_processar(at)

    assert not at.exception
    assert nomes_na_lista(at) == ["a.mp4"]
    assert any("o modelo não foi encontrado" in erro for erro in erros(at))


def test_AC_028_1_falha_ao_disparar_mantem_a_lista_e_nao_mostra_traceback(
    tmp_path, monkeypatch, leituras, disparo_de_upload
):
    disparo_de_upload.falha = OSError("sem espaço em disco")
    at = abre_o_upload(tmp_path, monkeypatch)
    at = envia(at, video("a.mp4", b"a"))

    at = clica_em_processar(at)

    assert not at.exception
    assert nomes_na_lista(at) == ["a.mp4"]
    assert any("sem espaço em disco" in erro for erro in erros(at))


def test_AC_028_2_disparo_recusado_pela_trava_mostra_a_mensagem_e_mantem_a_lista(
    tmp_path, monkeypatch, leituras, disparo_de_upload
):
    disparo_de_upload.falha = OutraSessaoEmAndamentoError(
        InfoDaTrava(
            pid=1,
            criado_em_do_processo=0.0,
            comando="run",
            id_camera="000042",
            nome_camera="Outro local",
            iniciada_em=datetime(2026, 9, 7, 11, 0, tzinfo=timezone.utc),
        )
    )
    at = abre_o_upload(tmp_path, monkeypatch)
    at = envia(at, video("a.mp4", b"a"))

    at = clica_em_processar(at)

    assert not at.exception
    assert nomes_na_lista(at) == ["a.mp4"]
    assert any("Outro local" in erro for erro in erros(at))


def test_AC_028_2_com_sessao_em_andamento_processar_nao_dispara(
    tmp_path, monkeypatch, leituras, disparo_de_upload
):
    from datetime import datetime, timezone

    from auto_counter.pipeline.lock import adquirir_trava

    at = abre_o_upload(tmp_path, monkeypatch)
    at = envia(at, video("a.mp4", b"a"))
    assert botao_processar(at).disabled is False

    # Sessão iniciada pelo terminal: o botão continua desenhado, mas travado.
    with adquirir_trava(
        tmp_path / "data",
        comando="capture",
        id_camera="000042",
        nome_camera="Outro local",
        agora=lambda: datetime(2026, 9, 7, 11, 0, tzinfo=timezone.utc),
    ):
        at = at.run()
        assert botao_processar(at).disabled is True
        # O AppTest recusa o clique num botão desabilitado: ninguém dispara.
        with pytest.raises(Exception, match="disabled"):
            botao_processar(at).click()

    assert not at.exception
    assert disparo_de_upload.chamadas == []
    assert nomes_na_lista(at) == ["a.mp4"]


def test_iniciar_sessao_da_camera_ao_vivo_continua_igual(
    tmp_path, monkeypatch, disparo, disparo_de_upload
):
    registro_com(tmp_path, monkeypatch, "valida_000013.yaml")

    at = abre_a_interface()
    botao_iniciar(at).click()
    at = at.run()

    assert not at.exception
    assert len(disparo.chamadas) == 1
    assert disparo.chamadas[0][0] == "000013"
    assert disparo_de_upload.chamadas == []

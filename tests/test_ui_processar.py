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
from tests.test_ui_acompanhamento import (  # noqa: F401  (fixtures usadas por nome)
    data_dir,
    textos,
)
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


# --- T-17: painel e lista da sessão de upload na tela --------------------------
#
# AC-028.3 (título "Contagem · vídeo k/N" e o estado de cada vídeo), AC-028.10
# (aba nova reencontra tudo do disco), AC-029.1 e AC-029.2 (cancelada), AC-019.2
# (cabeçalho direto em "Processando") e AC-026.5, mais R-1 e D-16 do `_tasks.md`:
# a lista do painel de Configuração vem do estado em disco, e não da aba.

import os

from auto_counter.counting.config import Categoria
from auto_counter.pipeline.lock import adquirir_trava
from auto_counter.pipeline.state import AnotadorDoEstado, Fase, SituacaoDoVideo
from tests.test_ui_formulario import INICIO
from tests.test_ui_layout import indicador

ROTULOS_DOS_ESTADOS = {"fila", "processando", "concluído", "falhou", "interrompido"}
NOMES = ["a.mp4", "b.mp4", "c.mp4"]


def anotador_do_upload(data_dir, nomes=NOMES) -> AnotadorDoEstado:
    return AnotadorDoEstado(
        data_dir,
        pid=os.getpid(),
        id_camera="000013",
        nome_camera="Praça Exemplo",
        duracao_pedida=len(nomes),
        iniciada_em=INICIO,
        origem="UPLOAD",
        videos=nomes,
    )


def upload_no_segundo_video(data_dir) -> AnotadorDoEstado:
    """3 vídeos: o 1º concluído com 1 carro, o 2º em processamento, o 3º na fila."""
    a = anotador_do_upload(data_dir)
    a.iniciar()
    a.video_iniciado(1)
    a.minuto_iniciado()
    a.evento_aceito(1, Categoria.CARRO)
    a.minuto_processado()
    a.video_terminado(1, SituacaoDoVideo.CONCLUIDO)
    a.video_iniciado(2)
    return a


def trava_do_upload(data_dir):
    return adquirir_trava(
        data_dir,
        comando="upload",
        id_camera="000013",
        nome_camera="Praça Exemplo",
        agora=lambda: INICIO,
    )


def estados_na_lista(at) -> list[str]:
    return [c.value for c in at.caption if c.value in ROTULOS_DOS_ESTADOS]


def titulos(at) -> list[str]:
    return [s.value for s in at.subheader]


def fonte(at):
    return next(r for r in at.radio if r.key == "fonte")


def test_AC_028_3_painel_ao_vivo_tem_o_titulo_contagem_video_k_de_n(data_dir):
    upload_no_segundo_video(data_dir)

    with trava_do_upload(data_dir):
        at = abre_a_interface()

    assert not at.exception
    assert "Contagem · vídeo 2/3" in titulos(at)
    assert not any(t.startswith("Contagem ao vivo") for t in titulos(at))


def test_AC_028_3_cada_video_mostra_o_seu_estado(data_dir):
    upload_no_segundo_video(data_dir)

    with trava_do_upload(data_dir):
        at = abre_a_interface()

    assert nomes_na_lista(at) == NOMES
    assert estados_na_lista(at) == ["concluído", "processando", "fila"]


def test_AC_028_3_no_maximo_um_processando_na_tela(data_dir):
    upload_no_segundo_video(data_dir)

    with trava_do_upload(data_dir):
        at = abre_a_interface()

    assert estados_na_lista(at).count("processando") == 1


def test_AC_019_2_cabecalho_vai_direto_para_processando(data_dir):
    anotador_do_upload(data_dir).iniciar()

    with trava_do_upload(data_dir):
        at = abre_a_interface()

    assert indicador(at) == "Processando"
    assert "Contagem · vídeo 1/3" in titulos(at)


def test_AC_028_10_aba_nova_reencontra_a_lista_os_estados_e_as_quantidades(data_dir):
    upload_no_segundo_video(data_dir)

    with trava_do_upload(data_dir):
        primeira = abre_a_interface()
        # Outra aba: nenhum `session_state` em comum, só o disco.
        segunda = abre_a_interface()

    assert fonte(segunda).value == "upload"
    assert fonte(segunda).disabled is True
    assert nomes_na_lista(segunda) == NOMES
    assert estados_na_lista(segunda) == ["concluído", "processando", "fila"]
    assert [(m.label, m.value) for m in segunda.metric] == [
        (m.label, m.value) for m in primeira.metric
    ]
    assert ("Total", "1") in [(m.label, m.value) for m in segunda.metric]


def test_AC_029_1_cancelada_mostra_cancelado_sem_download(data_dir):
    a = upload_no_segundo_video(data_dir)
    a.video_terminado(2, SituacaoDoVideo.INTERROMPIDO)
    a.terminar(
        Fase.PROCESSAMENTO_CANCELADO,
        id_sessao="000013-20260907T110000Z",
        mensagem="o processamento foi cancelado e os vídeos foram mantidos",
    )

    at = abre_a_interface()

    assert not at.exception
    assert "Processamento cancelado." in textos(at)
    assert list(at.get("download_button")) == []
    assert "Baixar .xlsx" not in [b.label for b in at.button]


def test_AC_029_2_cancelada_mostra_interrompido_concluido_e_fila(data_dir):
    a = upload_no_segundo_video(data_dir)
    a.video_terminado(2, SituacaoDoVideo.INTERROMPIDO)
    a.terminar(
        Fase.PROCESSAMENTO_CANCELADO,
        id_sessao="000013-20260907T110000Z",
        mensagem="cancelado",
    )

    at = abre_a_interface()

    assert nomes_na_lista(at) == NOMES
    assert estados_na_lista(at) == ["concluído", "interrompido", "fila"]


def test_AC_026_5_area_de_envio_travada_durante_o_upload(data_dir):
    upload_no_segundo_video(data_dir)

    with trava_do_upload(data_dir):
        at = abre_a_interface()

    assert at.file_uploader[0].disabled is True
    assert fonte(at).disabled is True
    # A lista do disco não tem "Remover" nem totais.
    assert [b for b in at.button if (b.key or "").startswith("remover_")] == []
    assert not [c for c in at.caption if c.value.startswith("duração total")]


def test_nova_sessao_depois_do_upload_volta_com_a_lista_vazia(data_dir):
    a = upload_no_segundo_video(data_dir)
    a.video_terminado(2, SituacaoDoVideo.INTERROMPIDO)
    a.terminar(
        Fase.PROCESSAMENTO_CANCELADO,
        id_sessao="000013-20260907T110000Z",
        mensagem="cancelado",
    )
    at = abre_a_interface()
    assert nomes_na_lista(at) == NOMES

    at.button(key="nova_sessao").click()
    at = at.run()

    assert not at.exception
    assert nomes_na_lista(at) == []
    assert fonte(at).value == "upload"
    assert fonte(at).disabled is False
    assert at.file_uploader[0].disabled is False

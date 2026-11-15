"""Comando `session process` na CLI e o descarte dos vídeos — T-13.

Critério coberto, de `.spec/features/captura-clipes/spec.md`:

- AC-003.5 — sessão cujo processamento terminou e que foi executada **sem** a
  opção de manter os vídeos não deixa nenhum arquivo de vídeo em disco; com a
  opção ativa, todos os clipes permanecem no diretório da sessão. O descarte é
  D-5 do `_tasks.md` de `contagem-veiculos`: acontece **depois** do
  processamento e **só** quando ele termina com sucesso — processamento que
  falha não apaga nada, porque a sessão ainda pode ser reprocessada.

Mais os dois erros tratados do comando, que nunca podem virar traceback
(`CLAUDE.md`): modelo ausente e sessão inexistente.

Nenhum teste daqui toca a rede, carrega o `.onnx` ou grava dentro do
repositório: o registro de câmeras é um diretório temporário montado a partir
de `tests/fixtures/cameras/`, `AUTO_COUNTER_DATA_DIR` aponta para `tmp_path`, o
modelo é um arquivo qualquer — só o hash do conteúdo dele é lido (SUP-027) — e
o detector é dublê (D-8), injetado por `_detector`.
"""

import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import cv2
import numpy as np
import pytest
import supervision as sv
from typer.testing import CliRunner

from auto_counter.capture.manifest import ManifestDaSessao, nome_do_arquivo_do_minuto
from auto_counter.capture.status import StatusDaSessao
from auto_counter.cli import app
from auto_counter.counting.events import NOME_DO_ARQUIVO_DE_EVENTOS
from auto_counter.counting.model import (
    NOME_DO_ARQUIVO_DO_MODELO,
    SUBDIRETORIO_DE_MODELOS,
)
from auto_counter.storage.connection import conectar
from auto_counter.storage.events import contar_eventos
from auto_counter.storage.minutes import ler_agregados
from auto_counter.storage.model import EstadoDoMinuto
from auto_counter.storage.sessions import ler_sessao

FIXTURES = Path(__file__).parent / "fixtures" / "cameras"

ID_CAMERA = "000013"
ID_SESSAO = "000013-20260504T123000Z"
PRIMEIRO_LAST_MODIFIED = datetime(2026, 5, 4, 12, 30, 0, tzinfo=timezone.utc)

LARGURA = 128
ALTURA = 48
FPS = 30.0
QUADROS_POR_CLIPE = 6


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def registro(tmp_path) -> Path:
    """Registro temporário com a câmera 000013 das fixtures."""
    destino = tmp_path / "cameras"
    destino.mkdir(exist_ok=True)
    shutil.copy(FIXTURES / "valida_000013.yaml", destino / "valida_000013.yaml")
    return destino


@pytest.fixture
def data_dir(monkeypatch, tmp_path) -> Path:
    """Diretório de dados dentro do `tmp_path` — nada cai no repositório."""
    caminho = tmp_path / "data"
    monkeypatch.setenv("AUTO_COUNTER_DATA_DIR", str(caminho))
    return caminho


@pytest.fixture
def modelo(data_dir) -> Path:
    """Um `.onnx` de mentira: nada aqui carrega o modelo, só o hasheia."""
    caminho = data_dir / SUBDIRETORIO_DE_MODELOS / NOME_DO_ARQUIVO_DO_MODELO
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_bytes(b"onnx de mentira")
    return caminho


class DetectorDuble:
    """Dublê do detector (D-8): cena vazia em todo frame analisado.

    AC-003.5 é sobre o descarte dos vídeos depois do processamento, não sobre a
    contagem: um clipe sem ninguém em cena é processado do mesmo jeito, e a
    contagem em si já é verificada em T-09 a T-12.
    """

    def __init__(self) -> None:
        self.chamadas = 0

    def detectar(self, frame: np.ndarray) -> sv.Detections:
        self.chamadas += 1
        return sv.Detections.empty()


@pytest.fixture
def detector(monkeypatch) -> DetectorDuble:
    """Substitui a construção do detector real pelo dublê (D-8)."""
    duble = DetectorDuble()
    monkeypatch.setattr("auto_counter.cli._detector", lambda caminho, config: duble)
    return duble


def escreve_clipe(caminho: Path) -> Path:
    """Um MP4 válido e curto, como o de T-12."""
    escritor = cv2.VideoWriter(
        str(caminho), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (LARGURA, ALTURA)
    )
    assert escritor.isOpened(), (
        "o codec mp4v não está disponível nesta máquina e a fixture de vídeo "
        "válido não pôde ser gerada"
    )
    try:
        for _ in range(QUADROS_POR_CLIPE):
            escritor.write(np.zeros((ALTURA, LARGURA, 3), dtype=np.uint8))
    finally:
        escritor.release()
    assert caminho.exists() and caminho.stat().st_size > 0
    return caminho


def monta_sessao(
    data_dir: Path,
    *,
    minutos=(1, 2),
    manter_videos: bool = False,
    corrompidos=(),
) -> Path:
    """Cria o diretório da sessão com manifest e clipes, e devolve o caminho.

    `corrompidos` são minutos cujo `.mp4` existe mas não abre — o ramo de clipe
    ilegível de D-4, que é como esta suíte faz o processamento falhar sem
    apagar arquivo nenhum de propósito.

    `duracao_real` é gravada junto do `status`, replicando o invariante real
    de `manifest.fechar()` (`captura-clipes`): uma sessão real nunca tem
    status sem duração real. Sem isso, `persistencia-resultados` (T-07)
    recusaria a sessão como "ainda em captura" (D-4 daquela feature).
    """
    duracao_pedida = max(minutos, default=0)
    dir_sessao = data_dir / "sessions" / ID_SESSAO
    dir_sessao.mkdir(parents=True, exist_ok=True)
    manifest = ManifestDaSessao(
        dir_sessao,
        id_sessao=ID_SESSAO,
        id_camera=ID_CAMERA,
        duracao_pedida=duracao_pedida,
        duracao_real=duracao_pedida,
        status=StatusDaSessao.COMPLETA,
        manter_videos=manter_videos,
    )
    for minuto in sorted(minutos):
        manifest.registrar_minuto(
            minuto,
            etag=f"etag-{minuto}",
            last_modified=PRIMEIRO_LAST_MODIFIED + timedelta(minutes=minuto - 1),
            relogio_local=PRIMEIRO_LAST_MODIFIED + timedelta(minutes=minuto - 1),
        )
        caminho = dir_sessao / nome_do_arquivo_do_minuto(minuto)
        if minuto in corrompidos:
            caminho.write_bytes(b"isto nao e um video")
        else:
            escreve_clipe(caminho)
    manifest.gravar()
    return dir_sessao


def videos(dir_sessao: Path) -> list[str]:
    """Os arquivos de vídeo que restaram no diretório da sessão."""
    return sorted(caminho.name for caminho in dir_sessao.glob("*.mp4"))


def processa(runner: CliRunner, registro: Path, *extras: str):
    """Roda `session process` com o registro temporário do teste."""
    return runner.invoke(
        app,
        ["session", "process", ID_SESSAO, "--config-dir", str(registro), *extras],
    )


def test_AC_003_5_processamento_concluido_apaga_os_videos_da_sessao(
    runner, registro, data_dir, modelo, detector
):
    """Sem `manter_videos`, o sucesso do processamento leva os clipes embora.

    O `manifest.json` e o `eventos.json` continuam: o que AC-003.5 manda apagar
    é arquivo de vídeo, e é dos dois que `persistencia-resultados` vive depois
    que os `.mp4` somem.
    """
    dir_sessao = monta_sessao(data_dir)

    resultado = processa(runner, registro)

    assert resultado.exit_code == 0, resultado.output
    assert videos(dir_sessao) == []
    assert (dir_sessao / "manifest.json").is_file()
    assert (dir_sessao / NOME_DO_ARQUIVO_DE_EVENTOS).is_file()


def test_AC_003_5_sessao_com_manter_videos_preserva_os_clipes_apos_o_processamento(
    runner, registro, data_dir, modelo, detector
):
    """Com a opção ativa no manifest, **todos** os clipes permanecem."""
    dir_sessao = monta_sessao(data_dir, manter_videos=True)

    resultado = processa(runner, registro)

    assert resultado.exit_code == 0, resultado.output
    assert videos(dir_sessao) == ["minuto-01.mp4", "minuto-02.mp4"]
    assert (dir_sessao / NOME_DO_ARQUIVO_DE_EVENTOS).is_file()


def test_AC_003_5_processamento_que_falha_nao_apaga_nenhum_video(
    runner, registro, data_dir, modelo, detector
):
    """Nenhum clipe legível: a sessão falha (D-4) e nada é descartado.

    O descarte é irreversível e a sessão ainda pode ser reprocessada depois que
    a causa da falha for corrigida — apagar aqui destruiria o material.
    """
    dir_sessao = monta_sessao(data_dir, minutos=(1, 2), corrompidos=(1, 2))

    resultado = processa(runner, registro)

    assert resultado.exit_code == 1
    assert videos(dir_sessao) == ["minuto-01.mp4", "minuto-02.mp4"]
    assert not (dir_sessao / NOME_DO_ARQUIVO_DE_EVENTOS).exists()
    assert "Traceback" not in resultado.output


def test_session_process_sem_modelo_erra_citando_o_comando_de_export(
    runner, registro, data_dir, detector
):
    """Modelo ausente é erro tratado, com o caminho e o comando que o produz.

    E acontece **antes** de abrir qualquer vídeo: o detector não chega a ser
    consultado, e nenhum clipe é descartado.
    """
    dir_sessao = monta_sessao(data_dir)

    resultado = processa(runner, registro)

    assert resultado.exit_code == 1
    assert "auto-counter model export" in resultado.output
    assert NOME_DO_ARQUIVO_DO_MODELO in resultado.output
    assert detector.chamadas == 0
    assert videos(dir_sessao) == ["minuto-01.mp4", "minuto-02.mp4"]
    assert "Traceback" not in resultado.output


def test_session_process_em_sessao_inexistente_erra_citando_o_caminho(
    runner, registro, data_dir, modelo, detector
):
    """Sessão que não existe, ou diretório sem manifest, dizem onde se procurou."""
    resultado = processa(runner, registro)

    assert resultado.exit_code == 1
    assert ID_SESSAO in resultado.output
    assert "manifest.json" in resultado.output
    assert "Traceback" not in resultado.output


# --- Ligação com `persistencia-resultados` (T-08 daquela feature) ---------


def test_AC_008_1_session_process_grava_a_sessao_no_banco(
    runner, registro, data_dir, modelo, detector
):
    """A sessão processada fica gravada no banco, não só no `eventos.json`."""
    monta_sessao(data_dir)

    resultado = processa(runner, registro)
    assert resultado.exit_code == 0, resultado.output

    with conectar(data_dir) as conexao:
        sessao = ler_sessao(conexao, ID_SESSAO)

    assert sessao is not None
    assert sessao.id_camera == ID_CAMERA
    assert sessao.duracao_pedida == 2
    assert sessao.duracao_real == 2
    assert sessao.status is StatusDaSessao.COMPLETA
    assert sessao.versao_do_modelo is not None
    assert sessao.amostragem is not None
    assert sessao.limiar_de_confianca is not None


def test_AC_008_2_session_process_grava_os_eventos_no_banco(
    runner, registro, data_dir, modelo, detector
):
    """Os eventos da contagem ficam ligados ao id da sessão no banco.

    O detector dublê não produz cruzamento nenhum (cena vazia, D-8) — a
    correção da contagem é provada em `contagem-veiculos`, não aqui. O que
    esta ligação prova é que a escrita acontece e que a contagem gravada no
    banco é exatamente a que o comando reportou, inclusive quando é zero.
    """
    monta_sessao(data_dir)

    resultado = processa(runner, registro)
    assert resultado.exit_code == 0, resultado.output

    with conectar(data_dir) as conexao:
        total_no_banco = contar_eventos(conexao, ID_SESSAO)
        agregados = ler_agregados(conexao, ID_SESSAO)

    assert "Total de eventos:  0" in resultado.output
    assert total_no_banco == 0
    # E a grade de minutos também subiu — AC-008.3/AC-008.4, pela mesma
    # chamada de `persistir_sessao`.
    assert len(agregados) == 2
    assert all(item.estado is EstadoDoMinuto.CAPTURADO for item in agregados)


def test_AC_008_5_rodar_session_process_duas_vezes_nao_duplica_nada(
    runner, registro, data_dir, modelo, detector
):
    """`--keep-clips` equivalente (`manter_videos` no manifest) permite rodar
    `session process` duas vezes na mesma sessão: a segunda não duplica."""
    monta_sessao(data_dir, manter_videos=True)

    primeira = processa(runner, registro)
    assert primeira.exit_code == 0, primeira.output
    segunda = processa(runner, registro)
    assert segunda.exit_code == 0, segunda.output

    with conectar(data_dir) as conexao:
        assert contar_eventos(conexao, ID_SESSAO) == 0
        assert len(ler_agregados(conexao, ID_SESSAO)) == 2


def test_falha_ao_persistir_nao_apaga_os_videos_da_sessao(
    runner, registro, data_dir, modelo, detector, monkeypatch
):
    """Falha de banco aborta o comando **antes** do descarte dos vídeos
    (D-3): a sessão continua reprocessável depois que a causa for corrigida.
    """
    dir_sessao = monta_sessao(data_dir)

    def _persistir_com_falha(*args, **kwargs):
        raise RuntimeError("falha simulada de banco")

    monkeypatch.setattr("auto_counter.cli.persistir_sessao", _persistir_com_falha)

    resultado = processa(runner, registro)

    assert resultado.exit_code == 1
    assert "Traceback" not in resultado.output
    assert "banco" in resultado.output
    assert "reprocessada" in resultado.output
    # Nenhum clipe foi apagado: a falha aconteceu antes do descarte (D-3).
    assert videos(dir_sessao) == ["minuto-01.mp4", "minuto-02.mp4"]


# --- processamento-upload: `session process` numa sessão de upload (T-15) -----
#
# AC-029.3 (a sessão cancelada é processada desde o primeiro vídeo e gravada como
# a de upload concluída), AC-030.6 (os vídeos são apagados depois de gravar),
# AC-028.2 (a trava) e D-14 do `_tasks.md`. A sessão cancelada é produzida pelo
# próprio pipeline de upload, com a parada pedida antes do primeiro minuto.

ID_SESSAO_DO_UPLOAD = "000013-20261107T143000Z"
INICIO_DO_PROCESS = datetime(2026, 11, 8, 9, 0, 0, tzinfo=timezone.utc)
FIM_DO_PROCESS = datetime(2026, 11, 8, 9, 0, 5, tzinfo=timezone.utc)


def cancela_um_upload(data_dir, registro, tmp_path, *, quantos=2):
    """Roda `executar_upload` cancelado e devolve o diretório da sessão."""
    from auto_counter.cameras.registry import carregar_registro
    from auto_counter.pipeline.upload import executar_upload
    from tests.test_cli_session_upload import escreve_video
    from tests.test_pipeline_upload import ParadaNaConsulta, T0

    camera = carregar_registro(registro).cameras[0]
    arquivos = [
        escreve_video(tmp_path / f"v{i}.mp4", cor=10 * (i + 1)) for i in range(quantos)
    ]
    estado = executar_upload(
        camera,
        arquivos,
        [f"original-{i + 1}.mp4" for i in range(quantos)],
        data_dir=data_dir,
        agora=lambda: T0,
        criar_detector=lambda caminho, config: None,
        criar_parada=lambda: ParadaNaConsulta(1),
        pid=1,
    )
    assert estado.fase.value == "PROCESSAMENTO_CANCELADO"
    return data_dir / "sessions" / estado.id_sessao


@pytest.fixture
def upload_cancelado(data_dir, registro, modelo, tmp_path):
    return cancela_um_upload(data_dir, registro, tmp_path)


@pytest.fixture
def relogio_do_process(monkeypatch):
    # A primeira leitura é da trava de sessão única; depois vêm T0 e o fim.
    instantes = iter(
        [INICIO_DO_PROCESS, INICIO_DO_PROCESS, FIM_DO_PROCESS] + [FIM_DO_PROCESS] * 20
    )
    monkeypatch.setattr("auto_counter.cli._agora", lambda: next(instantes))


def processa_upload(runner, registro, *extras):
    return runner.invoke(
        app,
        [
            "session",
            "process",
            ID_SESSAO_DO_UPLOAD,
            "--config-dir",
            str(registro),
            *extras,
        ],
    )


def test_AC_029_3_upload_cancelado_e_processado_desde_o_primeiro_video(
    runner, registro, data_dir, modelo, detector, upload_cancelado, relogio_do_process
):
    assert not (upload_cancelado / NOME_DO_ARQUIVO_DE_EVENTOS).exists()

    resultado = processa_upload(runner, registro)

    assert resultado.exit_code == 0, resultado.output
    assert "Traceback" not in resultado.output
    # 2 vídeos de 10 quadros a 10 fps: todos os 20 frames passam pelo detector.
    assert detector.chamadas == 20
    assert (upload_cancelado / NOME_DO_ARQUIVO_DE_EVENTOS).is_file()
    assert "Minutos com dado:  1, 2" in resultado.output


def test_AC_029_3_resultado_gravado_como_sessao_de_upload_concluida(
    runner, registro, data_dir, modelo, detector, upload_cancelado, relogio_do_process
):
    from auto_counter.storage.model import OrigemDaSessao

    resultado = processa_upload(runner, registro)

    assert resultado.exit_code == 0, resultado.output
    with conectar(data_dir) as conexao:
        gravada = ler_sessao(conexao, ID_SESSAO_DO_UPLOAD)
    assert gravada.origem is OrigemDaSessao.UPLOAD
    assert gravada.status is StatusDaSessao.COMPLETA
    assert gravada.duracao_pedida == gravada.duracao_real == 2
    assert [v.nome_original for v in gravada.videos] == [
        "original-1.mp4",
        "original-2.mp4",
    ]
    assert [(v.minuto_inicial, v.minuto_final) for v in gravada.videos] == [
        (1, 1),
        (2, 2),
    ]
    # T0 e fim são os desta execução, e não os do upload cancelado.
    assert gravada.inicio == INICIO_DO_PROCESS
    assert gravada.fim == FIM_DO_PROCESS
    # Como `session process` da ao vivo, não gera a planilha.
    assert not list(data_dir.glob("*.xlsx"))


def test_AC_030_6_process_do_upload_apaga_os_videos_depois_de_gravar(
    runner, registro, data_dir, modelo, detector, upload_cancelado, relogio_do_process
):
    assert len(list(upload_cancelado.glob("video-*"))) == 2

    resultado = processa_upload(runner, registro)

    assert resultado.exit_code == 0, resultado.output
    assert list(upload_cancelado.glob("video-*")) == []
    assert (upload_cancelado / "upload.json").is_file()
    assert (upload_cancelado / NOME_DO_ARQUIVO_DE_EVENTOS).is_file()
    with conectar(data_dir) as conexao:
        assert ler_sessao(conexao, ID_SESSAO_DO_UPLOAD) is not None
    assert "apagado" in resultado.output


@pytest.mark.parametrize("opcao", [("--threshold", "0.5"), ("--sample-rate", "2")])
def test_D_14_upload_recusa_threshold_e_sample_rate(
    runner, registro, data_dir, modelo, detector, upload_cancelado, opcao
):
    resultado = processa_upload(runner, registro, *opcao)

    assert resultado.exit_code == 1
    assert opcao[0] in resultado.output
    assert "Traceback" not in resultado.output
    assert detector.chamadas == 0
    assert len(list(upload_cancelado.glob("video-*"))) == 2
    assert not (data_dir / "auto_counter.db").exists()


def test_D_14_upload_sem_videos_em_disco_e_recusado_sem_tocar_no_banco(
    runner, registro, data_dir, modelo, detector, upload_cancelado
):
    from auto_counter.storage.connection import NOME_DO_ARQUIVO_DO_BANCO

    for video in upload_cancelado.glob("video-*"):
        video.unlink()

    resultado = processa_upload(runner, registro)

    assert resultado.exit_code == 1
    assert "já foram apagados" in resultado.output
    assert "Traceback" not in resultado.output
    assert detector.chamadas == 0
    assert not (data_dir / NOME_DO_ARQUIVO_DO_BANCO).exists()


def test_AC_028_2_process_do_upload_pega_a_trava(
    runner, registro, data_dir, modelo, detector, upload_cancelado
):
    from tests.test_cli_lock import sessao_em_curso

    with sessao_em_curso(data_dir):
        resultado = processa_upload(runner, registro)

    assert resultado.exit_code == 1
    assert "Outro local" in resultado.output
    assert detector.chamadas == 0
    assert len(list(upload_cancelado.glob("video-*"))) == 2
    assert not (upload_cancelado / NOME_DO_ARQUIVO_DE_EVENTOS).exists()


def test_AC_012_7_session_process_recusa_sessao_cancelada_na_captura(
    runner, registro, data_dir, modelo, detector
):
    """A sessão marcada como cancelada não tem o que processar, e nada é gravado."""
    from auto_counter.storage.sessions import abrir_sessao, marcar_sessao_cancelada

    dir_sessao = monta_sessao(data_dir)
    with conectar(data_dir) as conexao:
        abrir_sessao(
            conexao,
            id_sessao=ID_SESSAO,
            id_camera=ID_CAMERA,
            criada_em=PRIMEIRO_LAST_MODIFIED,
            duracao_pedida=2,
            sentido_a="Icaraí",
            sentido_b="Centro",
        )
        marcar_sessao_cancelada(conexao, ID_SESSAO)

    resultado = processa(runner, registro)

    assert resultado.exit_code == 1
    assert "cancelada pelo usuário" in resultado.output
    assert ID_SESSAO in resultado.output
    assert detector.chamadas == 0
    assert not (dir_sessao / NOME_DO_ARQUIVO_DE_EVENTOS).exists()
    with conectar(data_dir) as conexao:
        assert contar_eventos(conexao, ID_SESSAO) == 0
        assert ler_agregados(conexao, ID_SESSAO) == ()
    assert list(data_dir.glob("*.xlsx")) == []

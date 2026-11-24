"""Aba Sessao — T-09.

Comportamento em `.spec/features/exportacao-xlsx/spec.md`: AC-010.4, AC-010.5
e SUP-033. A planilha é montada em memória, e o banco vive em `tmp_path`.
"""

from datetime import datetime
from pathlib import Path

from openpyxl import Workbook

from auto_counter.cameras.registry import carregar_registro
from auto_counter.capture.status import StatusDaSessao
from auto_counter.export.load import carregar
from auto_counter.export.sheet_session import escrever_sessao
from auto_counter.storage.connection import conectar
from tests.export_helpers import (
    ID_CAMERA,
    ID_SESSAO,
    NOME_CAMERA,
    SENTIDO_A,
    SENTIDO_B,
    VERSAO_DO_MODELO,
    gravar_sessao,
)


def _aba(tmp_path, **campos):
    with conectar(tmp_path) as conexao:
        gravar_sessao(conexao, **campos)
        dados = carregar(conexao, ID_SESSAO)
    aba = Workbook().active
    escrever_sessao(aba, dados)
    return aba


def _campos(aba) -> dict:
    return {linha[0].value: linha[1].value for linha in aba.iter_rows()}


def test_AC_010_4_sessao_traz_id_e_nome_da_camera_e_os_dois_rotulos(tmp_path):
    campos = _campos(_aba(tmp_path))

    assert campos["id da câmera"] == ID_CAMERA
    assert campos["nome da câmera"] == NOME_CAMERA
    assert campos["sentido A"] == SENTIDO_A
    assert campos["sentido B"] == SENTIDO_B


def test_AC_010_4_sessao_traz_periodo_real_em_horario_de_brasilia(tmp_path):
    aba = _aba(tmp_path, duracao_pedida=5)
    campos = _campos(aba)

    assert campos["início real"] == datetime(2026, 9, 7, 8, 0, 5)
    assert campos["fim real"] == datetime(2026, 9, 7, 8, 5, 5)
    celulas = {linha[0].value: linha[1] for linha in aba.iter_rows()}
    assert celulas["início real"].number_format == "dd/mm/yyyy hh:mm:ss"
    assert celulas["fim real"].number_format == "dd/mm/yyyy hh:mm:ss"


def test_AC_010_4_sessao_traz_duracao_pedida_real_e_encerramento_pelo_usuario(
    tmp_path,
):
    campos = _campos(
        _aba(tmp_path, duracao_pedida=15, duracao_real=7, encerrada_pelo_usuario=True)
    )

    assert campos["duração pedida (min)"] == 15
    assert campos["duração real (min)"] == 7
    assert campos["encerrada pelo usuário"] == "SIM"


def test_AC_010_4_sessao_traz_status_e_a_lista_de_minutos_perdidos(tmp_path):
    campos = _campos(
        _aba(
            tmp_path,
            duracao_pedida=10,
            status=StatusDaSessao.DEGRADADA,
            minutos_perdidos=(3, 7),
        )
    )
    sem_perda = _campos(_aba(tmp_path / "outra"))

    assert campos["status"] == "DEGRADADA"
    assert campos["minutos perdidos"] == "3, 7"
    assert sem_perda["minutos perdidos"] == "nenhum"
    assert sem_perda["encerrada pelo usuário"] == "NÃO"


def test_AC_010_4_sessao_traz_modelo_amostragem_e_limiar(tmp_path):
    campos = _campos(_aba(tmp_path))

    assert campos["versão do modelo"] == VERSAO_DO_MODELO
    assert campos["amostragem (1 frame a cada N)"] == 3
    assert campos["limiar de confiança"] == 0.35


def test_AC_010_5_aba_sessao_de_sessao_invalida_comeca_com_o_aviso(tmp_path):
    aba = _aba(
        tmp_path,
        duracao_pedida=2,
        status=StatusDaSessao.INVALIDA,
        minutos_perdidos=(1,),
    )

    assert aba["A1"].value.startswith("ATENÇÃO: sessão INVALIDA")
    assert aba["A2"].value == "campo"


def test_sessao_gravada_sem_nome_da_camera_deixa_a_celula_vazia(tmp_path):
    aba = _aba(tmp_path, nome_camera=None)

    assert _campos(aba)["nome da câmera"] is None


def test_AC_032_6_aba_de_metadados_registra_id_e_nome_da_000012(tmp_path):
    diretorio = Path(__file__).resolve().parents[1] / "config" / "cameras"
    camera = {c.id: c for c in carregar_registro(diretorio).cameras}["000012"]

    campos = _campos(
        _aba(
            tmp_path,
            id_camera=camera.id,
            nome_camera=camera.nome,
            sentido_a=camera.sentido_a,
            sentido_b=camera.sentido_b,
        )
    )

    assert campos["id da câmera"] == "000012"
    assert campos["nome da câmera"] == "Praia x Mariz Barros"


def test_AC_036_3_aba_sessao_traz_a_linha_com_sim(tmp_path):
    aba = _aba(
        tmp_path,
        duracao_pedida=15,
        status=StatusDaSessao.INVALIDA,
        minutos_perdidos=tuple(range(4, 16)),
        encerrada_por_servidor_indisponivel=True,
    )

    assert _campos(aba)["encerrada por servidor indisponível"] == "SIM"
    # Logo depois de "encerrada pelo usuário", na mesma grafia (D-13).
    nomes = [linha[0].value for linha in aba.iter_rows()]
    assert (
        nomes.index("encerrada por servidor indisponível")
        == nomes.index("encerrada pelo usuário") + 1
    )


def test_AC_036_3_aba_sessao_traz_a_linha_com_nao(tmp_path):
    campos = _campos(_aba(tmp_path))

    assert campos["encerrada por servidor indisponível"] == "NÃO"
    assert campos["encerrada pelo usuário"] == "NÃO"

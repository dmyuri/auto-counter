"""Carregamento do registro de câmeras — T-03.

Critérios cobertos, de `.spec/features/configuracao-camera/spec.md`:
AC-001.1 (N arquivos válidos → N câmeras completas), AC-001.2 (arquivo
inválido rejeitado citando arquivo e campo, sem derrubar as demais),
AC-001.3 (id duplicado derruba o carregamento inteiro) e AC-002.4 (câmera
sem linha é rejeitada e nunca herda a linha de outra).

A assimetria entre AC-001.2 e AC-001.3 é da spec e é proposital: arquivo
inválido é rejeição isolada, id duplicado é falha do registro inteiro.

Nenhum teste aqui lê `config/cameras/`: cada caso monta o seu próprio
diretório temporário a partir dos YAMLs de `tests/fixtures/cameras/`.
"""

import shutil
from pathlib import Path

import pytest

from auto_counter.cameras.model import Camera
from auto_counter.cameras.registry import (
    DiretorioDeRegistroInvalidoError,
    IdDuplicadoError,
    carregar_registro,
)

FIXTURES = Path(__file__).parent / "fixtures" / "cameras"


@pytest.fixture
def diretorio_com(tmp_path):
    """Monta um diretório de registro com os YAMLs de fixture pedidos."""

    def monta(*nomes: str) -> Path:
        destino = tmp_path / "cameras"
        destino.mkdir(exist_ok=True)
        for nome in nomes:
            shutil.copy(FIXTURES / nome, destino / nome)
        return destino

    return monta


def rejeicao_de(registro, nome_arquivo: str):
    """A rejeição referente a um arquivo, ou None se ele não foi rejeitado."""
    for rejeicao in registro.rejeicoes:
        if Path(rejeicao.arquivo).name == nome_arquivo:
            return rejeicao
    return None


def test_AC_001_1_registro_com_n_arquivos_validos_retorna_n_cameras(diretorio_com):
    diretorio = diretorio_com("valida_000013.yaml", "valida_000042.yaml")

    registro = carregar_registro(diretorio)

    assert len(registro.cameras) == 2
    assert registro.rejeicoes == []
    assert {camera.id for camera in registro.cameras} == {"000013", "000042"}


def test_AC_001_1_camera_carregada_tem_id_nome_sentidos_e_linha(diretorio_com):
    diretorio = diretorio_com("valida_000013.yaml")

    registro = carregar_registro(diretorio)

    (camera,) = registro.cameras
    assert isinstance(camera, Camera)
    assert camera.id == "000013"  # zeros à esquerda preservados (SUP-001)
    assert camera.nome == "Via de teste - camera 13"
    assert camera.sentido_a == "sentido A"
    assert camera.sentido_b == "sentido B"
    assert (camera.linha.p1.x, camera.linha.p1.y) == (120, 400)
    assert (camera.linha.p2.x, camera.linha.p2.y) == (1160, 420)


def test_AC_001_2_arquivo_invalido_e_rejeitado_citando_arquivo_e_campo(diretorio_com):
    diretorio = diretorio_com("sem_campo_sentido_b.yaml")

    registro = carregar_registro(diretorio)

    assert registro.cameras == []
    (rejeicao,) = registro.rejeicoes
    assert Path(rejeicao.arquivo).name == "sem_campo_sentido_b.yaml"
    assert "sentido_b" in rejeicao.motivo
    # o arquivo aparece também na mensagem legível, que é o que o CLI (T-09)
    # e a interface (AC-011.3) mostram
    assert "sem_campo_sentido_b.yaml" in str(rejeicao)


def test_AC_001_2_arquivo_invalido_nao_derruba_as_demais_cameras(diretorio_com):
    diretorio = diretorio_com(
        "valida_000013.yaml",
        "sem_campo_sentido_b.yaml",
        "valida_000042.yaml",
    )

    registro = carregar_registro(diretorio)

    assert {camera.id for camera in registro.cameras} == {"000013", "000042"}
    assert len(registro.rejeicoes) == 1
    assert rejeicao_de(registro, "sem_campo_sentido_b.yaml") is not None


def test_AC_001_3_id_duplicado_falha_o_carregamento_e_nao_devolve_nenhuma_camera(
    diretorio_com,
):
    # a 000042 é válida e sozinha carregaria: mesmo assim o registro inteiro cai
    diretorio = diretorio_com(
        "valida_000013.yaml",
        "duplicada_000013.yaml",
        "valida_000042.yaml",
    )

    with pytest.raises(IdDuplicadoError) as erro:
        carregar_registro(diretorio)

    mensagem = str(erro.value)
    assert "000013" in mensagem
    assert "valida_000013.yaml" in mensagem
    assert "duplicada_000013.yaml" in mensagem
    # nenhuma câmera é disponibilizada: nem a válida que não tem nada a ver
    assert "000042" not in mensagem


def test_AC_002_4_camera_sem_linha_e_rejeitada_sem_herdar_linha_de_outra(
    diretorio_com,
):
    diretorio = diretorio_com("valida_000013.yaml", "sem_linha.yaml")

    registro = carregar_registro(diretorio)

    (camera,) = registro.cameras
    assert camera.id == "000013"
    assert "000077" not in {c.id for c in registro.cameras}

    rejeicao = rejeicao_de(registro, "sem_linha.yaml")
    assert rejeicao is not None
    assert "linha" in rejeicao.motivo

    # a linha da 000013 continua sendo só dela
    assert (camera.linha.p1.x, camera.linha.p1.y) == (120, 400)


def test_registro_vazio_nao_e_erro(diretorio_com):
    registro = carregar_registro(diretorio_com())

    assert registro.cameras == []
    assert registro.rejeicoes == []


def test_diretorio_inexistente_falha_com_erro_explicito(tmp_path):
    # Decisão do autor do projeto: diretório ausente não é "registro vazio".
    # Nenhum AC cobre este caso; o erro explícito segue o espírito de AC-001.5
    # e evita que um cwd errado apareça como "nenhuma câmera cadastrada".
    ausente = tmp_path / "nao_existe"

    with pytest.raises(DiretorioDeRegistroInvalidoError) as erro:
        carregar_registro(ausente)
    assert str(ausente) in str(erro.value)

    arquivo = tmp_path / "cameras.yaml"
    arquivo.write_text("", encoding="utf-8")
    with pytest.raises(DiretorioDeRegistroInvalidoError):
        carregar_registro(arquivo)

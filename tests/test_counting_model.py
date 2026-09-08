"""Provisionamento e identidade do modelo de detecção — T-03.

T-03 não atende critério de aceite diretamente: implementa SUP-015 (YOLO11n
exportado para ONNX com entrada 640×640) e a parte de "versão do modelo" de
SUP-027, que AC-008.1 de `persistencia-resultados` vai consumir. Por isso os
nomes dos testes não carregam id de critério — não há critério a citar.

Nenhum teste daqui baixa peso, importa `ultralytics` ou carrega o `.onnx` real
(D-2 e D-8): o que dá para provar sem rede é caminho, identidade e mensagem, e
é só isso que está aqui. A exportação de verdade é passo manual de preparação
de máquina, conferido em T-14.
"""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from auto_counter.cli import app
from auto_counter.counting.model import (
    ModeloAusenteError,
    caminho_do_modelo,
    versao_do_modelo,
)


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_caminho_do_modelo_fica_em_models_dentro_do_data_dir(tmp_path: Path):
    assert caminho_do_modelo(tmp_path) == tmp_path / "models" / "yolo11n.onnx"


def test_versao_do_modelo_muda_quando_o_conteudo_do_arquivo_muda(tmp_path: Path):
    caminho = tmp_path / "yolo11n.onnx"

    caminho.write_bytes(b"pesos da exportacao de ontem")
    antes = versao_do_modelo(caminho)

    caminho.write_bytes(b"pesos da exportacao de hoje")
    depois = versao_do_modelo(caminho)

    # É exatamente isto que SUP-027 compra: dois resultados só são comparáveis
    # quando vieram do mesmo detector, mesmo que o arquivo tenha o mesmo nome.
    assert antes != depois


def test_versao_do_modelo_e_estavel_para_o_mesmo_conteudo(tmp_path: Path):
    primeiro = tmp_path / "primeiro" / "yolo11n.onnx"
    segundo = tmp_path / "segundo" / "yolo11n.onnx"
    for caminho in (primeiro, segundo):
        caminho.parent.mkdir()
        caminho.write_bytes(b"mesmos pesos, outra maquina")

    # O diretório não entra na identidade: mesmo conteúdo, mesma versão.
    assert versao_do_modelo(primeiro) == versao_do_modelo(segundo)
    assert versao_do_modelo(primeiro) == versao_do_modelo(primeiro)

    nome, separador, hash_curto = versao_do_modelo(primeiro).partition("@")
    assert nome == "yolo11n.onnx"
    assert separador == "@"
    assert len(hash_curto) == 12
    assert all(caractere in "0123456789abcdef" for caractere in hash_curto)


def test_versao_do_modelo_de_arquivo_ausente_produz_erro_citando_o_caminho(
    tmp_path: Path,
):
    ausente = caminho_do_modelo(tmp_path)

    with pytest.raises(ModeloAusenteError) as falha:
        versao_do_modelo(ausente)

    assert str(ausente) in str(falha.value)


def test_modelo_ausente_produz_erro_citando_o_caminho_e_o_comando_de_export(
    tmp_path: Path,
):
    ausente = caminho_do_modelo(tmp_path)

    mensagem = str(ModeloAusenteError(ausente))

    # A mensagem nasce aqui e é o CLI (T-13) quem a apresenta: precisa dizer
    # onde o modelo era esperado e qual comando o produz.
    assert str(ausente) in mensagem
    assert "auto-counter model export" in mensagem


def test_model_export_nao_sobrescreve_arquivo_existente_sem_force(
    runner: CliRunner, tmp_path: Path
):
    destino = caminho_do_modelo(tmp_path)
    destino.parent.mkdir(parents=True)
    conteudo = b"modelo ja exportado nesta maquina"
    destino.write_bytes(conteudo)

    resultado = runner.invoke(app, ["model", "export", "--out", str(destino)])

    # Sem `--force` o comando informa e sai bem: reexportar é minutos de
    # download, e o acidente não pode custar isso.
    assert resultado.exit_code == 0, resultado.output
    assert str(destino) in resultado.output
    assert destino.read_bytes() == conteudo


def test_model_export_usa_o_data_dir_quando_out_e_omitido(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("AUTO_COUNTER_DATA_DIR", str(tmp_path))
    destino = caminho_do_modelo(tmp_path)
    destino.parent.mkdir(parents=True)
    destino.write_bytes(b"modelo ja exportado nesta maquina")

    resultado = runner.invoke(app, ["model", "export"])

    assert resultado.exit_code == 0, resultado.output
    assert str(destino) in resultado.output


def test_model_export_sem_ultralytics_instalado_diz_como_instalar(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from auto_counter.counting import model

    def sem_ultralytics(destino: Path) -> Path:
        raise model.UltralyticsAusenteError()

    monkeypatch.setattr(model, "exportar", sem_ultralytics)

    resultado = runner.invoke(
        app, ["model", "export", "--out", str(caminho_do_modelo(tmp_path))]
    )

    assert resultado.exit_code == 1, resultado.output
    assert "ultralytics" in resultado.output
    assert "Traceback" not in resultado.output

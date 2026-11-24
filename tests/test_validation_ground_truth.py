"""Testes da leitura do conjunto de referência da validação de acurácia.

Comportamento definido em `.spec/features/validacao-acuracia/spec.md`. Todos os
conjuntos são sintéticos, montados em `tmp_path`: nenhum teste aqui lê o
`tests/ground_truth/` real.
"""

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from auto_counter.counting.config import Categoria
from auto_counter.validation.ground_truth import (
    ConjuntoDeReferenciaInvalidoError,
    carregar_conjunto,
    ler_contagem_manual,
    videos_ausentes,
)
from auto_counter.validation.model import Condicao

ROTULOS = ("Icaraí", "Centro")
CABECALHO = "instante_s,categoria,sentido\n"

_LAST_MODIFIED = {
    "pico": "2026-09-08T20:15:00+00:00",
    "fora_pico": "2026-09-09T17:30:00+00:00",
    "noturno": "2026-09-10T01:05:00+00:00",
    "chuva": "2026-09-11T19:00:00+00:00",
}


def _entrada(condicao: str, last_modified: str | None = None) -> str:
    return (
        f"  - condicao: {condicao}\n"
        f'    camera: "000013"\n'
        f'    last_modified: "{last_modified or _LAST_MODIFIED[condicao]}"\n'
        f"    etag: '\"65f1a2-{condicao}\"'\n"
    )


def _montar(
    raiz: Path,
    condicoes=("pico", "fora_pico", "noturno"),
    *,
    com_csv=None,
    manifest: str | None = None,
) -> Path:
    raiz.mkdir(parents=True, exist_ok=True)
    if manifest is None:
        manifest = "versao: 1\nclipes:\n" + "".join(_entrada(c) for c in condicoes)
    (raiz / "manifest.yaml").write_text(manifest, encoding="utf-8")
    for condicao in condicoes if com_csv is None else com_csv:
        (raiz / f"{condicao}.csv").write_text(CABECALHO, encoding="utf-8")
    return raiz


def _csv(tmp_path: Path, conteudo: str, *, encoding="utf-8") -> Path:
    caminho = tmp_path / "amostra.csv"
    caminho.write_bytes(conteudo.encode(encoding))
    return caminho


def test_manifest_valido_carrega_as_tres_condicoes_obrigatorias_em_ordem(tmp_path):
    # manifest fora de ordem de propósito: a ordem de saída é a do enum
    raiz = _montar(tmp_path / "gt", ("noturno", "pico", "fora_pico"))

    conjunto = carregar_conjunto(raiz)

    assert conjunto.raiz == raiz
    assert [c.condicao for c in conjunto.clipes] == [
        Condicao.PICO,
        Condicao.FORA_PICO,
        Condicao.NOTURNO,
    ]
    pico = conjunto.clipes[0]
    assert pico.id_camera == "000013"
    assert pico.last_modified == datetime(2026, 9, 8, 20, 15, tzinfo=timezone.utc)
    assert pico.last_modified.utcoffset() is not None
    assert pico.etag == '"65f1a2-pico"'
    assert pico.caminho_csv == raiz / "pico.csv"
    assert pico.caminho_video == raiz / "clipes" / "pico.mp4"


def test_manifest_sem_condicao_obrigatoria_e_recusado_citando_qual(tmp_path):
    raiz = _montar(tmp_path / "gt", ("pico", "fora_pico"))

    with pytest.raises(ConjuntoDeReferenciaInvalidoError) as erro:
        carregar_conjunto(raiz)

    assert "noturno" in str(erro.value)
    assert "manifest.yaml" in str(erro.value)


def test_condicao_repetida_no_manifest_e_recusada(tmp_path):
    raiz = _montar(tmp_path / "gt", ("pico", "fora_pico", "noturno", "pico"))

    with pytest.raises(ConjuntoDeReferenciaInvalidoError) as erro:
        carregar_conjunto(raiz)

    assert "pico" in str(erro.value)
    assert "manifest.yaml" in str(erro.value)


def test_last_modified_sem_fuso_no_manifest_e_recusado(tmp_path):
    manifest = (
        "versao: 1\nclipes:\n"
        + _entrada("pico", "2026-09-08T20:15:00")
        + _entrada("fora_pico")
        + _entrada("noturno")
    )
    raiz = _montar(tmp_path / "gt", manifest=manifest)

    with pytest.raises(ConjuntoDeReferenciaInvalidoError) as erro:
        carregar_conjunto(raiz)

    assert "fuso" in str(erro.value)
    assert "manifest.yaml" in str(erro.value)


def test_csv_ausente_de_condicao_listada_e_recusado_citando_o_caminho(tmp_path):
    raiz = _montar(tmp_path / "gt", com_csv=("pico", "fora_pico"))

    with pytest.raises(ConjuntoDeReferenciaInvalidoError) as erro:
        carregar_conjunto(raiz)

    assert str(raiz / "noturno.csv") in str(erro.value)


def test_csv_com_categoria_fora_das_quatro_e_recusado_citando_a_linha(tmp_path):
    caminho = _csv(
        tmp_path,
        CABECALHO + "1.0,CARRO,Icaraí\n2.5,BICICLETA,Centro\n",
    )

    with pytest.raises(ConjuntoDeReferenciaInvalidoError) as erro:
        ler_contagem_manual(caminho, rotulos=ROTULOS)

    mensagem = str(erro.value)
    assert str(caminho) in mensagem
    assert "linha 3" in mensagem
    assert "BICICLETA" in mensagem


def test_csv_com_sentido_fora_dos_rotulos_e_recusado_citando_os_rotulos_esperados(
    tmp_path,
):
    caminho = _csv(tmp_path, CABECALHO + "1.0,CARRO,sentido_a\n")

    with pytest.raises(ConjuntoDeReferenciaInvalidoError) as erro:
        ler_contagem_manual(caminho, rotulos=ROTULOS)

    mensagem = str(erro.value)
    assert str(caminho) in mensagem
    assert "linha 2" in mensagem
    assert "sentido_a" in mensagem
    assert "Icaraí" in mensagem and "Centro" in mensagem


@pytest.mark.parametrize("instante", ["-0.5", "60", "60.1", "125", "nan", "inf", "abc"])
def test_csv_com_instante_negativo_ou_a_partir_de_60_s_e_recusado(tmp_path, instante):
    caminho = _csv(tmp_path, CABECALHO + f"{instante},CARRO,Centro\n")

    with pytest.raises(ConjuntoDeReferenciaInvalidoError) as erro:
        ler_contagem_manual(caminho, rotulos=ROTULOS)

    assert str(caminho) in str(erro.value)
    assert "linha 2" in str(erro.value)


def test_csv_salvo_com_ponto_e_virgula_e_recusado_com_dica_do_separador(tmp_path):
    caminho = _csv(tmp_path, "instante_s;categoria;sentido\n12,4;CARRO;Centro\n")

    with pytest.raises(ConjuntoDeReferenciaInvalidoError) as erro:
        ler_contagem_manual(caminho, rotulos=ROTULOS)

    mensagem = str(erro.value)
    assert str(caminho) in mensagem
    assert "Excel" in mensagem
    assert "vírgula" in mensagem
    assert "ponto decimal" in mensagem


def test_csv_com_bom_e_lido_normalmente(tmp_path):
    caminho = _csv(
        tmp_path,
        CABECALHO + "12.4,CARRO,Icaraí\n30,ONIBUS,Centro\n",
        encoding="utf-8-sig",
    )

    veiculos = ler_contagem_manual(caminho, rotulos=ROTULOS)

    assert [(v.linha, v.instante_s, v.categoria, v.sentido) for v in veiculos] == [
        (2, Decimal("12.4"), Categoria.CARRO, "Icaraí"),
        (3, Decimal("30"), Categoria.ONIBUS, "Centro"),
    ]
    assert isinstance(veiculos[0].instante_s, Decimal)


def test_csv_so_com_cabecalho_e_clipe_sem_veiculo(tmp_path):
    caminho = _csv(tmp_path, CABECALHO)

    assert ler_contagem_manual(caminho, rotulos=ROTULOS) == ()


def test_csv_com_cabecalho_diferente_ou_colunas_a_mais_e_recusado(tmp_path):
    cabecalho_errado = _csv(tmp_path, "tempo,categoria,sentido\n1.0,CARRO,Centro\n")
    with pytest.raises(ConjuntoDeReferenciaInvalidoError) as erro:
        ler_contagem_manual(cabecalho_errado, rotulos=ROTULOS)
    assert "instante_s,categoria,sentido" in str(erro.value)

    colunas_a_mais = _csv(tmp_path, CABECALHO + "1.0,CARRO,Centro,extra\n")
    with pytest.raises(ConjuntoDeReferenciaInvalidoError) as erro:
        ler_contagem_manual(colunas_a_mais, rotulos=ROTULOS)
    assert "linha 2" in str(erro.value)


def test_manifest_com_versao_diferente_de_1_e_recusado(tmp_path):
    manifest = "versao: 2\nclipes:\n" + "".join(
        _entrada(c) for c in ("pico", "fora_pico", "noturno")
    )
    raiz = _montar(tmp_path / "gt", manifest=manifest)

    with pytest.raises(ConjuntoDeReferenciaInvalidoError) as erro:
        carregar_conjunto(raiz)

    assert "versao" in str(erro.value) or "versão" in str(erro.value)


def test_AC_014_5_video_obrigatorio_ausente_e_nomeado_a_partir_do_manifest(tmp_path):
    raiz = _montar(tmp_path / "gt")
    (raiz / "clipes").mkdir()
    (raiz / "clipes" / "pico.mp4").write_bytes(b"x")
    conjunto = carregar_conjunto(raiz)

    ausentes = videos_ausentes(conjunto)

    assert [c.condicao for c in ausentes] == [Condicao.FORA_PICO, Condicao.NOTURNO]
    assert [c.caminho_video.name for c in ausentes] == ["fora_pico.mp4", "noturno.mp4"]


def test_video_de_chuva_ausente_nao_entra_na_lista_de_ausentes(tmp_path):
    raiz = _montar(tmp_path / "gt", ("pico", "fora_pico", "noturno", "chuva"))
    (raiz / "clipes").mkdir()
    for nome in ("pico", "fora_pico", "noturno"):
        (raiz / "clipes" / f"{nome}.mp4").write_bytes(b"x")
    conjunto = carregar_conjunto(raiz)

    assert [c.condicao for c in conjunto.clipes][-1] is Condicao.CHUVA
    assert Condicao.CHUVA.obrigatoria is False
    assert Condicao.PICO.obrigatoria is True
    assert videos_ausentes(conjunto) == ()

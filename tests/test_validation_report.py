"""Testes do relatório em texto da validação de acurácia.

Comportamento definido em `.spec/features/validacao-acuracia/spec.md`:
AC-015.1, com SUP-049, e AC-014.5 na parte de "mesma entrada, mesmo resultado".
Nenhum teste aqui leva o ID AC-014.3 no nome (D-9).
"""

import re
from datetime import datetime, timezone
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import pytest
from auto_counter.cameras.model import Camera, Linha, Ponto
from auto_counter.counting.config import Categoria, ConfiguracaoDoProcessamento
from auto_counter.validation.model import (
    AcertoDeCategoria,
    ClipeDeReferencia,
    ClipeMedido,
    Condicao,
    ErroDoSentido,
    MatrizDeConfusao,
    MedicaoDoClipe,
    Pareamento,
    ResultadoDaValidacao,
    VeiculoAutomatico,
    VeiculoManual,
)
from auto_counter.validation.report import gravar_relatorio, montar_relatorio
from auto_counter.validation.verdict import veredito_do_clipe, veredito_do_conjunto

A = "Icaraí"
B = "Centro"
LAST_MODIFIED = datetime(2026, 9, 8, 20, 15, 0, tzinfo=timezone.utc)
EXECUTADO_EM = datetime(2026, 10, 26, 12, 0, 5, tzinfo=timezone.utc)
CAMERA = Camera(
    id="000013",
    nome="Praça Renascença",
    sentido_a=A,
    sentido_b=B,
    linha=Linha(p1=Ponto(x=100, y=0), p2=Ponto(x=100, y=200)),
)
SHA_VIDEO = "a" * 64
SHA_CSV = "b" * 64


def _erro(sentido: str, manual: int, automatico: int) -> ErroDoSentido:
    if manual == 0:
        erro = Fraction(0) if automatico == 0 else None
    else:
        erro = Fraction(abs(automatico - manual), manual)
    return ErroDoSentido(sentido=sentido, manual=manual, automatico=automatico, erro=erro)


def _matriz(**celulas: int) -> MatrizDeConfusao:
    """`CARRO_MOTO=2` coloca 2 pares com manual CARRO e automático MOTO."""
    categorias = list(Categoria)
    linhas = [[0] * 4 for _ in categorias]
    for nome, valor in celulas.items():
        manual, automatica = nome.split("_")
        linhas[categorias.index(Categoria[manual])][categorias.index(Categoria[automatica])] = valor
    return MatrizDeConfusao(linhas=tuple(tuple(linha) for linha in linhas))


def _medicao(
    *,
    a=(20, 20),
    b=(20, 20),
    pares: int = 40,
    acertos: int = 40,
    matriz: MatrizDeConfusao | None = None,
    manuais_sem_par: int = 0,
    automaticos_sem_par: int = 0,
) -> MedicaoDoClipe:
    sem_par_manual = tuple(
        VeiculoManual(linha=i + 2, instante_s=Decimal(i), categoria=Categoria.CARRO, sentido=A)
        for i in range(manuais_sem_par)
    )
    sem_par_auto = tuple(
        VeiculoAutomatico(
            instante_s=Decimal(i), categoria=Categoria.CARRO, sentido=A, id_de_rastreio=f"1:{i}"
        )
        for i in range(automaticos_sem_par)
    )
    return MedicaoDoClipe(
        erros=(_erro(A, *a), _erro(B, *b)),
        acerto=AcertoDeCategoria(
            pares=pares,
            acertos=acertos,
            fracao=None if pares == 0 else Fraction(acertos, pares),
        ),
        matriz=matriz or _matriz(CARRO_CARRO=acertos),
        pareamento=Pareamento(
            pares=(), manuais_sem_par=sem_par_manual, automaticos_sem_par=sem_par_auto
        ),
    )


def _clipe(condicao: Condicao) -> ClipeDeReferencia:
    return ClipeDeReferencia(
        condicao=condicao,
        id_camera="000013",
        last_modified=LAST_MODIFIED,
        etag='"65f1a2-1e8480"',
        caminho_csv=Path(f"{condicao.value}.csv"),
        caminho_video=Path("clipes") / f"{condicao.value}.mp4",
    )


def _medido(condicao: Condicao, medicao: MedicaoDoClipe | None = None) -> ClipeMedido:
    medicao = medicao or _medicao()
    return ClipeMedido(
        clipe=_clipe(condicao),
        camera=CAMERA,
        sha256_video=SHA_VIDEO,
        sha256_csv=SHA_CSV,
        medicao=medicao,
        veredito=veredito_do_clipe(condicao, medicao),
        motivo_nao_medido=None,
    )


def _nao_medido(condicao: Condicao, motivo: str) -> ClipeMedido:
    return ClipeMedido(
        clipe=_clipe(condicao),
        camera=CAMERA,
        sha256_video=None,
        sha256_csv=None,
        medicao=None,
        veredito=None,
        motivo_nao_medido=motivo,
    )


def _resultado(*clipes: ClipeMedido) -> ResultadoDaValidacao:
    return ResultadoDaValidacao(
        clipes=tuple(clipes),
        veredito=veredito_do_conjunto([c.veredito for c in clipes if c.veredito is not None]),
        versao_do_modelo="yolo11n.onnx@0123456789ab",
        configuracao=ConfiguracaoDoProcessamento(),
    )


def _tres(**medicoes: MedicaoDoClipe) -> list[ClipeMedido]:
    return [
        _medido(condicao, medicoes.get(condicao.value))
        for condicao in (Condicao.PICO, Condicao.FORA_PICO, Condicao.NOTURNO)
    ]


def _secao(texto: str, condicao: Condicao) -> str:
    """O trecho do relatório que começa no título do clipe e vai até o próximo."""
    partes = re.split(r"(?m)^(?==== )", texto)
    return next(p for p in partes if p.startswith(f"=== Clipe {condicao.value}"))


def test_AC_015_1_relatorio_traz_contagem_manual_e_automatica_por_sentido_de_cada_clipe():
    resultado = _resultado(
        *_tres(
            pico=_medicao(a=(31, 33), b=(27, 25)),
            fora_pico=_medicao(a=(12, 12), b=(9, 10)),
            noturno=_medicao(a=(4, 4), b=(5, 6)),
        )
    )

    texto = montar_relatorio(resultado, executado_em=EXECUTADO_EM)

    pico = _secao(texto, Condicao.PICO)
    assert re.search(rf"{A}\s+31\s+33", pico)
    assert re.search(rf"{B}\s+27\s+25", pico)
    assert re.search(rf"{A}\s+12\s+12", _secao(texto, Condicao.FORA_PICO))
    assert re.search(rf"{B}\s+5\s+6", _secao(texto, Condicao.NOTURNO))
    assert "Manual" in pico and "Automático" in pico


def test_AC_015_1_relatorio_traz_o_erro_percentual_por_sentido():
    resultado = _resultado(
        *_tres(
            pico=_medicao(a=(20, 22), b=(16, 19)),
            fora_pico=_medicao(a=(0, 2)),
        )
    )

    texto = montar_relatorio(resultado, executado_em=EXECUTADO_EM)

    assert "10.00% (2/20)" in _secao(texto, Condicao.PICO)
    assert "18.75% (3/16)" in _secao(texto, Condicao.PICO)
    assert "indefinido (manual 0, automático 2)" in _secao(texto, Condicao.FORA_PICO)
    assert "0.00% (0/20)" in _secao(texto, Condicao.NOTURNO)


def test_AC_015_1_relatorio_traz_o_acerto_pares_e_veiculos_sem_par():
    resultado = _resultado(
        *_tres(
            pico=_medicao(
                pares=42, acertos=32, manuais_sem_par=3, automaticos_sem_par=1
            ),
            fora_pico=_medicao(pares=0, acertos=0),
        )
    )

    texto = montar_relatorio(resultado, executado_em=EXECUTADO_EM)

    pico = _secao(texto, Condicao.PICO)
    assert "76.19% (32/42)" in pico
    assert re.search(r"[Pp]ares:\s+42", pico)
    assert re.search(r"[Ss]em par.*manuais:?\s+3.*automáticos:?\s+1", pico)
    assert "indefinido (0 pares)" in _secao(texto, Condicao.FORA_PICO)


def test_AC_015_1_relatorio_traz_a_matriz_de_confusao_das_quatro_categorias():
    matriz = _matriz(CARRO_CARRO=5, CARRO_MOTO=1, ONIBUS_CAMINHAO=2)
    resultado = _resultado(*_tres(pico=_medicao(matriz=matriz, pares=8, acertos=5)))

    texto = montar_relatorio(resultado, executado_em=EXECUTADO_EM)

    pico = _secao(texto, Condicao.PICO)
    assert "manual" in pico and "automático" in pico
    cabecalho = next(l for l in pico.splitlines() if "CARRO" in l and "CAMINHAO" in l)
    assert [c.value for c in Categoria] == re.findall(r"[A-Z]+", cabecalho)
    assert re.search(r"(?m)^\s*CARRO\s+5\s+1\s+0\s+0\s*$", pico)
    assert re.search(r"(?m)^\s*MOTO\s+0\s+0\s+0\s+0\s*$", pico)
    assert re.search(r"(?m)^\s*ONIBUS\s+0\s+0\s+0\s+2\s*$", pico)
    assert re.search(r"(?m)^\s*CAMINHAO\s+0\s+0\s+0\s+0\s*$", pico)


def test_AC_015_1_relatorio_traz_o_veredito_de_cada_clipe():
    resultado = _resultado(
        *_tres(pico=_medicao(pares=42, acertos=32), noturno=_medicao(b=(16, 19)))
    )

    texto = montar_relatorio(resultado, executado_em=EXECUTADO_EM)

    assert "Veredito do clipe pico: REPROVADO" in texto
    assert "Veredito do clipe fora_pico: APROVADO" in texto
    assert "Veredito do clipe noturno: REPROVADO" in texto
    assert "acerto de categoria = 76.19% (32/42); limite ≥ 80%" in _secao(
        texto, Condicao.PICO
    )
    assert "erro de contagem no sentido Centro = 18.75% (3/16)" in _secao(
        texto, Condicao.NOTURNO
    )
    assert "VEREDITO DO CONJUNTO: REPROVADO" in texto
    assert "validação reprovada:" in texto


def test_AC_015_1_conjunto_aprovado_aparece_como_aprovado_sem_mensagem_de_falha():
    texto = montar_relatorio(_resultado(*_tres()), executado_em=EXECUTADO_EM)

    assert "VEREDITO DO CONJUNTO: APROVADO" in texto
    assert "validação reprovada" not in texto


def test_AC_015_1_clipe_de_chuva_aparece_identificado_como_medicao_fora_da_meta():
    chuva = _medido(Condicao.CHUVA, _medicao(a=(10, 20), pares=10, acertos=1))
    resultado = _resultado(*_tres(), chuva)

    texto = montar_relatorio(resultado, executado_em=EXECUTADO_EM)

    assert "medição fora da meta" in texto
    assert "não entra no veredito" in texto
    secao = _secao(texto, Condicao.CHUVA)
    assert re.search(rf"{A}\s+10\s+20", secao)
    assert "VEREDITO DO CONJUNTO: APROVADO" in texto
    assert "Veredito do clipe chuva" not in texto


def test_AC_015_1_chuva_nao_medida_aparece_com_o_motivo():
    resultado = _resultado(
        *_tres(), _nao_medido(Condicao.CHUVA, "vídeo ausente em clipes/chuva.mp4")
    )

    texto = montar_relatorio(resultado, executado_em=EXECUTADO_EM)

    secao = _secao(texto, Condicao.CHUVA)
    assert "não medido" in secao
    assert "vídeo ausente em clipes/chuva.mp4" in secao
    assert "VEREDITO DO CONJUNTO: APROVADO" in texto


def test_sem_chuva_no_manifest_o_relatorio_nao_tem_secao_de_chuva():
    texto = montar_relatorio(_resultado(*_tres()), executado_em=EXECUTADO_EM)

    assert "chuva" not in texto.lower()


def test_relatorio_identifica_a_entrada_e_a_configuracao_usadas():
    texto = montar_relatorio(_resultado(*_tres()), executado_em=EXECUTADO_EM)

    assert "2026-10-26T12:00:05Z" in texto
    assert "yolo11n.onnx@0123456789ab" in texto
    assert "0.35" in texto  # limiar de confiança
    assert "640" in texto  # tamanho de entrada
    assert "10%" in texto and "80%" in texto
    assert "2 s" in texto  # janela de pareamento
    pico = _secao(texto, Condicao.PICO)
    assert "000013" in pico
    assert A in pico and B in pico
    assert "(100, 0)" in pico and "(100, 200)" in pico
    assert "2026-09-08T20:15:00+00:00" in pico
    assert '"65f1a2-1e8480"' in pico
    assert SHA_VIDEO in pico and SHA_CSV in pico


def test_relatorio_e_texto_puro_sem_cor_ansi():
    texto = montar_relatorio(_resultado(*_tres()), executado_em=EXECUTADO_EM)

    assert "\x1b" not in texto
    assert texto.endswith("\n")


def test_AC_015_1_relatorio_e_gravado_como_texto_no_diretorio_de_dados(tmp_path):
    texto = montar_relatorio(_resultado(*_tres()), executado_em=EXECUTADO_EM)

    caminho = gravar_relatorio(texto, data_dir=tmp_path, executado_em=EXECUTADO_EM)

    assert caminho == tmp_path / "validacao" / "relatorio-20261026T120005Z.txt"
    assert caminho.read_text(encoding="utf-8") == texto


def test_AC_014_5_mesmo_resultado_gera_relatorio_igual_exceto_a_data_da_execucao():
    resultado = _resultado(*_tres(pico=_medicao(pares=42, acertos=32)))
    outra_data = datetime(2026, 11, 3, 9, 30, 0, tzinfo=timezone.utc)

    um = montar_relatorio(resultado, executado_em=EXECUTADO_EM)
    outro = montar_relatorio(resultado, executado_em=outra_data)

    def sem_a_data(texto: str) -> list[str]:
        return [l for l in texto.splitlines() if "2026-10-26T" not in l and "2026-11-03T" not in l]

    assert um != outro
    assert sem_a_data(um) == sem_a_data(outro)
    assert len(um.splitlines()) == len(outro.splitlines())


def test_gravar_relatorio_nunca_sobrescreve_um_existente(tmp_path):
    caminho = gravar_relatorio("primeiro\n", data_dir=tmp_path, executado_em=EXECUTADO_EM)

    with pytest.raises(FileExistsError) as erro:
        gravar_relatorio("segundo\n", data_dir=tmp_path, executado_em=EXECUTADO_EM)

    assert str(caminho) in str(erro.value)
    assert caminho.read_text(encoding="utf-8") == "primeiro\n"


def test_clipe_obrigatorio_nao_medido_e_recusado_na_construcao():
    with pytest.raises(ValueError) as erro:
        _nao_medido(Condicao.PICO, "vídeo ausente")

    assert "pico" in str(erro.value)

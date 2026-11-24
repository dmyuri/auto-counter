"""Testes do veredito por clipe e do conjunto.

Comportamento definido em `.spec/features/validacao-acuracia/spec.md`:
AC-014.4 e AC-015.1. Nenhum teste aqui leva o ID AC-014.3 no nome: ele é
reservado ao teste sobre os clipes reais (D-9), porque o `audit.py` daria a
meta como atingida se um teste sintético com esse ID passasse.
"""

from fractions import Fraction

from auto_counter.validation.model import (
    AcertoDeCategoria,
    Condicao,
    ErroDoSentido,
    MatrizDeConfusao,
    MedicaoDoClipe,
    Pareamento,
)
from auto_counter.validation.verdict import (
    ACERTO_MINIMO_PERCENTUAL,
    ERRO_MAXIMO_PERCENTUAL,
    mensagem_de_falha,
    veredito_do_clipe,
    veredito_do_conjunto,
)

A = "Icaraí"
B = "Centro"


def _erro(sentido: str, manual: int, automatico: int) -> ErroDoSentido:
    if manual == 0:
        erro = Fraction(0) if automatico == 0 else None
    else:
        erro = Fraction(abs(automatico - manual), manual)
    return ErroDoSentido(sentido=sentido, manual=manual, automatico=automatico, erro=erro)


def _medicao(
    *, a=(20, 20), b=(20, 20), pares: int = 40, acertos: int = 40
) -> MedicaoDoClipe:
    """`a` e `b` são (manual, automático) por sentido."""
    return MedicaoDoClipe(
        erros=(_erro(A, *a), _erro(B, *b)),
        acerto=AcertoDeCategoria(
            pares=pares,
            acertos=acertos,
            fracao=None if pares == 0 else Fraction(acertos, pares),
        ),
        matriz=MatrizDeConfusao(linhas=tuple((0,) * 4 for _ in range(4))),
        pareamento=Pareamento(pares=(), manuais_sem_par=(), automaticos_sem_par=()),
    )


def _bom(condicao: Condicao):
    return veredito_do_clipe(condicao, _medicao())


def _conjunto_bom():
    return [_bom(Condicao.PICO), _bom(Condicao.FORA_PICO), _bom(Condicao.NOTURNO)]


def test_os_limites_sao_10_e_80_por_cento():
    assert ERRO_MAXIMO_PERCENTUAL == 10
    assert ACERTO_MINIMO_PERCENTUAL == 80


def test_AC_014_4_erro_acima_de_10_porcento_reprova_e_aponta_clipe_metrica_e_valor():
    veredito = veredito_do_clipe(Condicao.NOTURNO, _medicao(b=(16, 19)))

    assert veredito.passou is False
    assert len(veredito.violacoes) == 1
    violacao = veredito.violacoes[0]
    assert violacao.condicao is Condicao.NOTURNO
    assert violacao.metrica == "erro de contagem"
    assert violacao.sentido == B
    assert violacao.valor == Fraction(3, 16)
    assert (violacao.numerador, violacao.denominador) == (3, 16)
    assert violacao.limite == 10


def test_AC_014_4_acerto_abaixo_de_80_porcento_reprova_e_aponta_clipe_metrica_e_valor():
    veredito = veredito_do_clipe(Condicao.PICO, _medicao(pares=42, acertos=32))

    assert veredito.passou is False
    violacao = veredito.violacoes[0]
    assert violacao.condicao is Condicao.PICO
    assert violacao.metrica == "acerto de categoria"
    assert violacao.sentido is None
    assert violacao.valor == Fraction(32, 42)
    assert (violacao.numerador, violacao.denominador) == (32, 42)
    assert violacao.limite == 80


def test_AC_014_4_erro_de_exatamente_10_porcento_nao_e_violacao():
    veredito = veredito_do_clipe(Condicao.PICO, _medicao(a=(20, 22), b=(20, 18)))

    assert veredito.passou is True
    assert veredito.violacoes == ()


def test_AC_014_4_acerto_de_exatamente_80_porcento_nao_e_violacao():
    veredito = veredito_do_clipe(Condicao.PICO, _medicao(pares=10, acertos=8))

    assert veredito.passou is True
    assert veredito.violacoes == ()


def test_AC_014_4_um_pouco_acima_do_limite_e_violacao_sem_arredondamento():
    # 10,0001% de erro e 79,99% de acerto: nenhum dos dois pode passar
    erro = veredito_do_clipe(Condicao.PICO, _medicao(a=(100000, 110001)))
    acerto = veredito_do_clipe(Condicao.PICO, _medicao(pares=10000, acertos=7999))

    assert erro.passou is False
    assert acerto.passou is False


def test_AC_014_4_um_clipe_reprovado_reprova_o_conjunto_mesmo_com_a_media_dentro():
    # média de erro dos três no sentido B = (0 + 0 + 12,5)/3 ≈ 4,2%, mas um clipe passa de 10%
    ruim = veredito_do_clipe(Condicao.NOTURNO, _medicao(b=(16, 18)))
    conjunto = veredito_do_conjunto(
        [_bom(Condicao.PICO), _bom(Condicao.FORA_PICO), ruim]
    )

    assert conjunto.passou is False
    assert [v.condicao for v in conjunto.violacoes] == [Condicao.NOTURNO]


def test_AC_014_4_metrica_indefinida_e_violacao_e_aparece_como_indefinida():
    sem_manual = veredito_do_clipe(Condicao.FORA_PICO, _medicao(a=(0, 2)))
    sem_pares = veredito_do_clipe(Condicao.PICO, _medicao(pares=0, acertos=0))

    assert sem_manual.passou is False
    assert sem_manual.violacoes[0].valor is None
    assert sem_pares.passou is False
    assert sem_pares.violacoes[0].metrica == "acerto de categoria"
    assert sem_pares.violacoes[0].valor is None

    texto = mensagem_de_falha(veredito_do_conjunto([sem_manual, sem_pares, _bom(Condicao.NOTURNO)]))
    assert "erro de contagem no sentido Icaraí = indefinido (manual 0, automático 2)" in texto
    assert "acerto de categoria = indefinido" in texto


def test_AC_014_4_manual_zero_e_automatico_zero_nao_e_violacao():
    veredito = veredito_do_clipe(Condicao.PICO, _medicao(a=(0, 0)))

    assert veredito.passou is True


def test_AC_014_4_todas_as_violacoes_sao_listadas_e_nao_so_a_primeira():
    pico = veredito_do_clipe(Condicao.PICO, _medicao(pares=42, acertos=32))
    fora = veredito_do_clipe(Condicao.FORA_PICO, _medicao(a=(0, 2)))
    noite = veredito_do_clipe(Condicao.NOTURNO, _medicao(a=(16, 19), b=(16, 19)))

    conjunto = veredito_do_conjunto([noite, pico, fora])

    assert [(v.condicao, v.metrica, v.sentido) for v in conjunto.violacoes] == [
        (Condicao.PICO, "acerto de categoria", None),
        (Condicao.FORA_PICO, "erro de contagem", A),
        (Condicao.NOTURNO, "erro de contagem", A),
        (Condicao.NOTURNO, "erro de contagem", B),
    ]
    texto = mensagem_de_falha(conjunto)
    assert texto.startswith("validação reprovada:")
    assert "  - clipe pico: acerto de categoria = 76.19% (32/42); limite ≥ 80%" in texto
    assert (
        "  - clipe fora_pico: erro de contagem no sentido Icaraí = indefinido "
        "(manual 0, automático 2); limite ≤ 10%"
    ) in texto
    assert (
        "  - clipe noturno: erro de contagem no sentido Centro = 18.75% (3/16); "
        "limite ≤ 10%"
    ) in texto
    assert len(texto.splitlines()) == 1 + 4


def test_AC_014_4_conjunto_sem_violacao_nao_falha():
    conjunto = veredito_do_conjunto(_conjunto_bom())

    assert conjunto.passou is True
    assert conjunto.violacoes == ()
    assert mensagem_de_falha(conjunto) == ""


def test_AC_014_4_faltando_clipe_obrigatorio_o_conjunto_nao_passa():
    conjunto = veredito_do_conjunto([_bom(Condicao.PICO), _bom(Condicao.FORA_PICO)])

    assert conjunto.passou is False
    assert conjunto.ausentes == (Condicao.NOTURNO,)
    assert "noturno" in mensagem_de_falha(conjunto)


def test_AC_015_1_chuva_fora_dos_limites_nao_altera_o_veredito_do_conjunto():
    chuva = veredito_do_clipe(Condicao.CHUVA, _medicao(a=(10, 20), pares=10, acertos=1))

    assert chuva.passou is False
    assert chuva.violacoes  # a chuva tem veredito próprio, calculado para o relatório

    conjunto = veredito_do_conjunto([*_conjunto_bom(), chuva])

    assert conjunto.passou is True
    assert conjunto.violacoes == ()
    assert chuva in conjunto.clipes  # continua disponível para o relatório


def test_AC_015_1_chuva_sozinha_nao_substitui_clipe_obrigatorio():
    chuva = _bom(Condicao.CHUVA)

    conjunto = veredito_do_conjunto([_bom(Condicao.PICO), _bom(Condicao.FORA_PICO), chuva])

    assert conjunto.passou is False
    assert conjunto.ausentes == (Condicao.NOTURNO,)

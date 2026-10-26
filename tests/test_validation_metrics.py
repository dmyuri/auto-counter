"""Testes das métricas do clipe: erro por sentido, acerto de categoria e matriz.

Comportamento definido em `.spec/features/validacao-acuracia/spec.md`:
AC-014.1, AC-014.2 e AC-015.1. Funções puras, sem disco nem modelo.
"""

from decimal import Decimal
from fractions import Fraction

from auto_counter.counting.config import Categoria
from auto_counter.validation.metrics import (
    acerto_de_categoria,
    erro_por_sentido,
    matriz_de_confusao,
    medir_clipe,
)
from auto_counter.validation.model import VeiculoAutomatico, VeiculoManual
from auto_counter.validation.pairing import parear

A = "Icaraí"
B = "Centro"
ROTULOS = (A, B)


def _manuais(sentido: str, quantidade: int, categoria=Categoria.CARRO, inicio=0):
    return [
        VeiculoManual(
            linha=inicio + i + 2,
            instante_s=Decimal(10 * (inicio + i)),
            categoria=categoria,
            sentido=sentido,
        )
        for i in range(quantidade)
    ]


def _autos(sentido: str, quantidade: int, categoria=Categoria.CARRO, inicio=0):
    return [
        VeiculoAutomatico(
            instante_s=Decimal(10 * (inicio + i)),
            categoria=categoria,
            sentido=sentido,
            id_de_rastreio=f"{sentido}:{inicio + i}",
        )
        for i in range(quantidade)
    ]


def _por_sentido(erros):
    return {e.sentido: e for e in erros}


def test_AC_014_1_erro_percentual_absoluto_por_sentido():
    acima = _por_sentido(
        erro_por_sentido(_manuais(A, 20), _autos(A, 22), rotulos=ROTULOS)
    )
    abaixo = _por_sentido(
        erro_por_sentido(_manuais(A, 20), _autos(A, 18), rotulos=ROTULOS)
    )

    assert acima[A].manual == 20 and acima[A].automatico == 22
    assert acima[A].erro == Fraction(1, 10)
    assert abaixo[A].manual == 20 and abaixo[A].automatico == 18
    assert abaixo[A].erro == Fraction(1, 10)


def test_AC_014_1_erros_opostos_em_sentidos_diferentes_nao_se_cancelam():
    manuais = _manuais(A, 10) + _manuais(B, 10, inicio=100)
    automaticos = _autos(A, 12) + _autos(B, 8, inicio=100)

    erros = _por_sentido(erro_por_sentido(manuais, automaticos, rotulos=ROTULOS))

    assert erros[A].erro == Fraction(1, 5)
    assert erros[B].erro == Fraction(1, 5)


def test_AC_014_1_o_erro_usa_os_totais_e_nao_so_os_pareados():
    # nenhum par possível (instantes muito distantes), mas os totais batem
    manuais = [
        VeiculoManual(linha=2, instante_s=Decimal(1), categoria=Categoria.CARRO, sentido=A)
    ]
    automaticos = [
        VeiculoAutomatico(
            instante_s=Decimal(50),
            categoria=Categoria.CARRO,
            sentido=A,
            id_de_rastreio="1:1",
        )
    ]
    assert parear(manuais, automaticos).pares == ()

    erros = _por_sentido(erro_por_sentido(manuais, automaticos, rotulos=ROTULOS))

    assert erros[A].manual == 1 and erros[A].automatico == 1
    assert erros[A].erro == Fraction(0)


def test_AC_014_1_manual_zero_e_automatico_zero_e_erro_zero():
    erros = _por_sentido(erro_por_sentido([], [], rotulos=ROTULOS))

    assert erros[A].erro == Fraction(0)


def test_AC_014_1_manual_zero_e_automatico_positivo_e_erro_indefinido():
    erros = _por_sentido(erro_por_sentido([], _autos(A, 2), rotulos=ROTULOS))

    assert erros[A].erro is None
    assert erros[A].manual == 0 and erros[A].automatico == 2


def test_AC_014_1_sentido_sem_nenhum_veiculo_aparece_com_zero_e_zero():
    erros = erro_por_sentido(_manuais(A, 3), _autos(A, 3), rotulos=ROTULOS)

    assert [e.sentido for e in erros] == [A, B]
    sem_veiculo = _por_sentido(erros)[B]
    assert (sem_veiculo.manual, sem_veiculo.automatico) == (0, 0)
    assert sem_veiculo.erro == Fraction(0)


def test_AC_014_2_acerto_e_a_fracao_dos_pares_com_a_mesma_categoria():
    manuais = _manuais(A, 4)
    automaticos = (
        _autos(A, 3, Categoria.CARRO) + _autos(A, 1, Categoria.MOTO, inicio=3)
    )

    acerto = acerto_de_categoria(parear(manuais, automaticos))

    assert (acerto.pares, acerto.acertos) == (4, 3)
    assert acerto.fracao == Fraction(3, 4)


def test_AC_014_2_veiculo_sem_par_nao_entra_no_acerto():
    manuais = _manuais(A, 2) + _manuais(A, 1, Categoria.ONIBUS, inicio=30)
    automaticos = _autos(A, 2) + _autos(A, 1, Categoria.MOTO, inicio=40)

    pareamento = parear(manuais, automaticos)
    acerto = acerto_de_categoria(pareamento)

    assert len(pareamento.manuais_sem_par) == 1
    assert len(pareamento.automaticos_sem_par) == 1
    assert (acerto.pares, acerto.acertos) == (2, 2)
    assert acerto.fracao == Fraction(1)


def test_AC_014_2_acerto_soma_os_dois_sentidos_do_clipe():
    manuais = _manuais(A, 2) + _manuais(B, 2, inicio=100)
    automaticos = _autos(A, 2) + _autos(B, 2, Categoria.MOTO, inicio=100)

    acerto = acerto_de_categoria(parear(manuais, automaticos))

    assert (acerto.pares, acerto.acertos) == (4, 2)
    assert acerto.fracao == Fraction(1, 2)


def test_AC_014_2_sem_nenhum_par_o_acerto_e_indefinido():
    acerto = acerto_de_categoria(parear(_manuais(A, 2), []))

    assert acerto.pares == 0
    assert acerto.fracao is None


def test_AC_015_1_matriz_de_confusao_tem_as_quatro_categorias_mesmo_sem_ocorrencia():
    manuais = _manuais(A, 3, Categoria.CARRO)
    automaticos = _autos(A, 2, Categoria.CARRO) + _autos(A, 1, Categoria.MOTO, inicio=2)

    matriz = matriz_de_confusao(parear(manuais, automaticos))

    ordem = list(Categoria)
    assert len(ordem) == 4
    assert len(matriz.linhas) == 4
    assert all(len(linha) == 4 for linha in matriz.linhas)
    assert matriz.contagem(Categoria.CARRO, Categoria.CARRO) == 2
    assert matriz.contagem(Categoria.CARRO, Categoria.MOTO) == 1
    # linhas = manual, colunas = automático, na ordem do enum
    assert matriz.linhas[ordem.index(Categoria.CARRO)][ordem.index(Categoria.MOTO)] == 1
    assert sum(sum(linha) for linha in matriz.linhas) == 3
    assert matriz.contagem(Categoria.ONIBUS, Categoria.CAMINHAO) == 0


def test_AC_014_1_medir_clipe_reune_erro_acerto_matriz_e_pareamento():
    manuais = _manuais(A, 2) + _manuais(B, 1, Categoria.ONIBUS, inicio=100)
    automaticos = _autos(A, 2) + _autos(B, 1, Categoria.CARRO, inicio=100)

    medicao = medir_clipe(manuais, automaticos, rotulos=ROTULOS)

    assert medicao.pareamento == parear(manuais, automaticos)
    assert [e.sentido for e in medicao.erros] == [A, B]
    assert medicao.acerto == acerto_de_categoria(medicao.pareamento)
    assert medicao.matriz == matriz_de_confusao(medicao.pareamento)
    assert medicao.acerto.fracao == Fraction(2, 3)

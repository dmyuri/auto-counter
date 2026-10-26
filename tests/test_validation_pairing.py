"""Testes do pareamento entre veículo manual e automático.

Comportamento definido em `.spec/features/validacao-acuracia/spec.md`:
AC-014.2 e SUP-046. Funções puras, sem disco nem modelo.
"""

import random
from decimal import Decimal

from auto_counter.counting.config import Categoria
from auto_counter.validation.model import VeiculoAutomatico, VeiculoManual
from auto_counter.validation.pairing import (
    JANELA_DE_PAREAMENTO_EM_SEGUNDOS,
    parear,
)

A = "Icaraí"
B = "Centro"


def _manual(linha, instante, sentido=A, categoria=Categoria.CARRO) -> VeiculoManual:
    return VeiculoManual(
        linha=linha,
        instante_s=Decimal(str(instante)),
        categoria=categoria,
        sentido=sentido,
    )


def _auto(id_de_rastreio, instante, sentido=A, categoria=Categoria.CARRO):
    return VeiculoAutomatico(
        instante_s=Decimal(str(instante)),
        categoria=categoria,
        sentido=sentido,
        id_de_rastreio=id_de_rastreio,
    )


def test_a_janela_de_pareamento_e_de_2_s():
    assert JANELA_DE_PAREAMENTO_EM_SEGUNDOS == Decimal("2")


def test_AC_014_2_veiculos_do_mesmo_sentido_dentro_de_2_s_sao_pareados():
    manual = _manual(2, "10.4")
    automatico = _auto("1:1", 11)

    resultado = parear([manual], [automatico])

    assert len(resultado.pares) == 1
    assert resultado.pares[0].manual == manual
    assert resultado.pares[0].automatico == automatico
    assert resultado.pares[0].delta_s == Decimal("0.6")
    assert resultado.manuais_sem_par == ()
    assert resultado.automaticos_sem_par == ()


def test_AC_014_2_diferenca_de_exatamente_2_s_ainda_pareia():
    resultado = parear([_manual(2, 10)], [_auto("1:1", 12)])

    assert len(resultado.pares) == 1
    assert resultado.manuais_sem_par == ()


def test_AC_014_2_diferenca_acima_de_2_s_nao_pareia():
    manual = _manual(2, "10.0")
    automatico = _auto("1:1", "12.1")

    resultado = parear([manual], [automatico])

    assert resultado.pares == ()
    assert resultado.manuais_sem_par == (manual,)
    assert resultado.automaticos_sem_par == (automatico,)


def test_AC_014_2_sentidos_diferentes_nao_pareiam_nem_no_mesmo_instante():
    manual = _manual(2, 10, sentido=A)
    automatico = _auto("1:1", 10, sentido=B)

    resultado = parear([manual], [automatico])

    assert resultado.pares == ()
    assert resultado.manuais_sem_par == (manual,)
    assert resultado.automaticos_sem_par == (automatico,)


def test_AC_014_2_cada_veiculo_entra_em_no_maximo_um_par():
    # dois manuais disputam o mesmo automático; dois automáticos disputam o mesmo manual
    manuais = [_manual(2, 10), _manual(3, 11)]
    automaticos = [_auto("1:1", 10)]

    resultado = parear(manuais, automaticos)

    assert len(resultado.pares) == 1
    assert len(resultado.manuais_sem_par) == 1

    resultado = parear([_manual(2, 10)], [_auto("1:1", 10), _auto("1:2", 11)])

    assert len(resultado.pares) == 1
    assert len(resultado.automaticos_sem_par) == 1

    usados_manuais = [p.manual.linha for p in resultado.pares]
    usados_autos = [p.automatico.id_de_rastreio for p in resultado.pares]
    assert len(set(usados_manuais)) == len(usados_manuais)
    assert len(set(usados_autos)) == len(usados_autos)


def test_AC_014_2_o_candidato_mais_proximo_vence():
    manual = _manual(2, 10)
    longe = _auto("1:1", "11.5")
    perto = _auto("1:2", "10.2")

    resultado = parear([manual], [longe, perto])

    assert [p.automatico for p in resultado.pares] == [perto]
    assert resultado.automaticos_sem_par == (longe,)


def test_AC_014_2_guloso_pelo_menor_delta_global_e_nao_pela_ordem_do_manual():
    # m1 (10.0) está a 1.0 de a1 (11.0); m2 (11.5) está a 0.5 de a1.
    # O par globalmente mais próximo é (m2, a1); m1 fica sem par.
    m1 = _manual(2, "10.0")
    m2 = _manual(3, "11.5")
    a1 = _auto("1:1", "11.0")

    resultado = parear([m1, m2], [a1])

    assert [(p.manual, p.automatico) for p in resultado.pares] == [(m2, a1)]
    assert resultado.manuais_sem_par == (m1,)


def test_AC_014_2_a_categoria_nao_influencia_o_pareamento():
    manual = _manual(2, 10, categoria=Categoria.CARRO)
    mais_perto_outra_categoria = _auto("1:1", "10.1", categoria=Categoria.MOTO)
    mais_longe_mesma_categoria = _auto("1:2", "10.9", categoria=Categoria.CARRO)

    resultado = parear([manual], [mais_longe_mesma_categoria, mais_perto_outra_categoria])

    assert [p.automatico for p in resultado.pares] == [mais_perto_outra_categoria]
    assert resultado.pares[0].manual.categoria != resultado.pares[0].automatico.categoria


def test_AC_014_5_o_pareamento_nao_depende_da_ordem_de_entrada():
    manuais = [
        _manual(2, "5.0"),
        _manual(3, "5.0", sentido=B),
        _manual(4, "9.0"),
        _manual(5, "9.0"),  # empate com a linha 4
        _manual(6, "20.0"),
        _manual(7, "40.0", sentido=B),
    ]
    automaticos = [
        _auto("1:1", "5.0"),
        _auto("1:2", "6.0", sentido=B),
        _auto("1:3", "9.0"),
        _auto("1:4", "9.0"),  # empate com 1:3
        _auto("1:5", "10.0"),
        _auto("1:6", "21.5"),
        _auto("1:7", "55.0", sentido=B),
    ]
    esperado = parear(manuais, automaticos)

    aleatorio = random.Random(20261019)
    for _ in range(25):
        m = manuais[:]
        a = automaticos[:]
        aleatorio.shuffle(m)
        aleatorio.shuffle(a)
        assert parear(m, a) == esperado


def test_AC_014_5_saidas_em_ordem_deterministica():
    m_tarde = _manual(2, 30)
    m_cedo = _manual(3, 1)
    a_tarde = _auto("1:2", 50)
    a_cedo = _auto("1:1", 40)

    resultado = parear([m_tarde, m_cedo], [a_tarde, a_cedo])

    assert resultado.manuais_sem_par == (m_cedo, m_tarde)
    assert resultado.automaticos_sem_par == (a_cedo, a_tarde)


def test_AC_014_2_sem_nenhuma_entrada_o_pareamento_e_vazio():
    resultado = parear([], [])

    assert resultado.pares == ()
    assert resultado.manuais_sem_par == ()
    assert resultado.automaticos_sem_par == ()

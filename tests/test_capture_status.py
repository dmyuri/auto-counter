"""Vocabulário de status da sessão e a regra dos 20% — T-01.

Critérios cobertos, de `.spec/features/captura-clipes/spec.md`:

- AC-004.4 — sessão sem nenhum minuto perdido recebe `COMPLETA`;
- AC-004.5 — pelo menos um minuto perdido e no máximo 20% da base recebe
  `DEGRADADA`, com a lista dos minutos perdidos registrada;
- AC-004.6 — mais de 20% da base recebe `INVALIDA`, também com a lista.

O denominador chega **por parâmetro** (SUP-013): quem decide se é o N pedido ou
a duração real de uma sessão interrompida (AC-003.6) é o chamador, e não esta
função. Por isso os testes daqui falam em `base`, nunca em "minutos pedidos".

SUP-013 também diz que o limite é percentual puro, sem tolerância absoluta: em
sessão curta uma única perda pode bastar para `INVALIDA`, e isso é o
comportamento correto, não um caso de borda a ser suavizado.
"""

import pytest

from auto_counter.capture.status import StatusDaSessao, classificar


def test_AC_004_4_sessao_sem_minuto_perdido_recebe_status_completa():
    resultado = classificar(15, [])

    assert resultado.status is StatusDaSessao.COMPLETA
    assert list(resultado.minutos_perdidos) == []


def test_AC_004_5_perda_de_ate_vinte_por_cento_recebe_degradada_com_a_lista_de_minutos():
    # 15 minutos com 2 perdas = 13,3%, abaixo do limite.
    resultado = classificar(15, [4, 9])

    assert resultado.status is StatusDaSessao.DEGRADADA
    assert list(resultado.minutos_perdidos) == [4, 9]


def test_AC_004_6_perda_acima_de_vinte_por_cento_recebe_invalida_com_a_lista_de_minutos():
    # 10 minutos com 3 perdas = 30%, acima do limite.
    resultado = classificar(10, [2, 5, 6])

    assert resultado.status is StatusDaSessao.INVALIDA
    assert list(resultado.minutos_perdidos) == [2, 5, 6]


def test_AC_004_6_sessao_curta_com_uma_unica_perda_pode_ser_invalida():
    # SUP-013: percentual puro, sem tolerância absoluta. 1 de 3 é 33%.
    resultado = classificar(3, [2])

    assert resultado.status is StatusDaSessao.INVALIDA
    assert list(resultado.minutos_perdidos) == [2]


def test_AC_004_5_limite_de_vinte_por_cento_e_inclusivo_na_fronteira_exata():
    # AC-004.5 é "no máximo 20%" (inclusive); AC-004.6 é "mais de 20%".
    # 3 de 15 é exatamente 20% e cai do lado de DEGRADADA.
    na_fronteira = classificar(15, [1, 2, 3])
    assert na_fronteira.status is StatusDaSessao.DEGRADADA

    # Uma perda a mais atravessa a fronteira.
    acima = classificar(15, [1, 2, 3, 4])
    assert acima.status is StatusDaSessao.INVALIDA

    # 1 de 5 também é exatamente 20% e continua DEGRADADA — a comparação é
    # inteira (`perdidos * 5 <= base`), então nenhum arredondamento de float
    # empurra a fronteira para o lado errado.
    assert classificar(5, [3]).status is StatusDaSessao.DEGRADADA


def test_AC_004_4_o_vocabulario_de_status_tem_exatamente_tres_nomes():
    # O §Contexto da spec fixa três status, os mesmos no banco, na interface e
    # no XLSX. Q-003 decidiu que o encerramento pelo usuário NÃO cria um quarto
    # (AC-003.6 vira um campo à parte).
    assert {membro.name for membro in StatusDaSessao} == {
        "COMPLETA",
        "DEGRADADA",
        "INVALIDA",
    }


@pytest.mark.parametrize("base_invalida", [0, -1, -15])
def test_AC_004_4_base_menor_que_um_e_erro_de_programacao_e_nao_status(base_invalida):
    # Uma sessão de zero minutos não tem status: não há denominador. Isso é bug
    # do chamador, e falhar alto aqui evita um status inventado.
    with pytest.raises(ValueError):
        classificar(base_invalida, [])

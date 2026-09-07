"""Validação da duração pedida, antes de qualquer rede — T-02.

Critério coberto, de `.spec/features/captura-clipes/spec.md`:

- AC-003.3 — duração fora do intervalo de 1 a 15 minutos é rejeitada com erro
  que cita o limite, **antes de qualquer requisição ao servidor**.

A garantia de "antes de qualquer requisição" é estrutural: `validar_duracao` é
pura e não tem como abrir socket, ler variável de ambiente ou construir cliente
HTTP. Por isso o teste confere a assinatura do módulo (nenhum import de rede) em
vez de espionar uma chamada que não existe.
"""

import pytest

from auto_counter.capture.duration import (
    DURACAO_MAXIMA,
    DURACAO_MINIMA,
    DuracaoForaDoIntervaloError,
    validar_duracao,
)


@pytest.mark.parametrize("minutos", [0, -1, -15])
def test_AC_003_3_duracao_menor_que_um_e_rejeitada_citando_o_limite(minutos):
    with pytest.raises(DuracaoForaDoIntervaloError) as erro:
        validar_duracao(minutos)

    mensagem = str(erro.value)
    assert str(DURACAO_MINIMA) in mensagem
    assert str(DURACAO_MAXIMA) in mensagem
    assert str(minutos) in mensagem


@pytest.mark.parametrize("minutos", [16, 60, 1000])
def test_AC_003_3_duracao_maior_que_quinze_e_rejeitada_citando_o_limite(minutos):
    with pytest.raises(DuracaoForaDoIntervaloError) as erro:
        validar_duracao(minutos)

    mensagem = str(erro.value)
    assert str(DURACAO_MINIMA) in mensagem
    assert str(DURACAO_MAXIMA) in mensagem
    assert str(minutos) in mensagem


@pytest.mark.parametrize("minutos", [1, 7, 15])
def test_AC_003_3_duracao_valida_no_limite_e_aceita(minutos):
    assert validar_duracao(minutos) == minutos


@pytest.mark.parametrize("minutos", [1.0, 7.5, "3", None, True])
def test_AC_003_3_duracao_nao_inteira_e_rejeitada_citando_o_limite(minutos):
    # O intervalo de AC-003.3 é de minutos inteiros: meia sessão de 7,5 minutos
    # não existe, e `True` seria aceito como 1 se o `bool` passasse por int.
    with pytest.raises(DuracaoForaDoIntervaloError) as erro:
        validar_duracao(minutos)

    mensagem = str(erro.value)
    assert str(DURACAO_MINIMA) in mensagem
    assert str(DURACAO_MAXIMA) in mensagem


def test_AC_003_3_a_validacao_nao_alcanca_a_rede():
    # AC-003.3 exige a rejeição antes de qualquer requisição ao servidor. A
    # forma de garantir isso é a função não ter como fazer uma: o módulo não
    # importa cliente HTTP nem lê ambiente. A conferência é sobre os imports
    # de verdade (AST), não sobre o texto do arquivo — palavra em comentário
    # não abre socket.
    import ast
    import pathlib

    from auto_counter.capture import duration

    arvore = ast.parse(pathlib.Path(duration.__file__).read_text(encoding="utf-8"))

    importados = set()
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            importados.update(alias.name.split(".")[0] for alias in no.names)
        elif isinstance(no, ast.ImportFrom) and no.module:
            importados.add(no.module.split(".")[0])

    assert importados.isdisjoint({"httpx", "requests", "socket", "urllib", "os"})

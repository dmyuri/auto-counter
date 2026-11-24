"""Pedido de parada por arquivo — T-05.

Critério coberto, de `.spec/features/interface-sessao/spec.md`: AC-012.4 — o
encerramento antecipado só acontece por ação explícita do usuário. Sem pedido, a
parada nunca é sinalizada.
"""

from auto_counter.pipeline.stop import (
    NOME_DO_PEDIDO,
    ParadaComposta,
    ParadaPorArquivo,
    consumir_pedido,
    pedir_parada,
)


class ParadaFixa:
    def __init__(self, pedida: bool) -> None:
        self._pedida = pedida

    def foi_pedida(self) -> bool:
        return self._pedida


def test_AC_012_4_sem_pedido_a_parada_nunca_e_sinalizada(tmp_path):
    parada = ParadaPorArquivo(tmp_path)

    assert parada.foi_pedida() is False
    assert parada.foi_pedida() is False
    assert not (tmp_path / NOME_DO_PEDIDO).exists()


def test_AC_012_4_pedir_parada_sinaliza_a_parada_por_arquivo(tmp_path):
    parada = ParadaPorArquivo(tmp_path)

    pedir_parada(tmp_path)

    assert parada.foi_pedida() is True
    assert (tmp_path / NOME_DO_PEDIDO).is_file()


def test_pedir_parada_e_idempotente_e_cria_o_diretorio(tmp_path):
    destino = tmp_path / "novo"

    pedir_parada(destino)
    pedir_parada(destino)

    assert ParadaPorArquivo(destino).foi_pedida() is True


def test_consumir_pedido_desliga_a_parada(tmp_path):
    parada = ParadaPorArquivo(tmp_path)
    pedir_parada(tmp_path)

    consumir_pedido(tmp_path)

    assert parada.foi_pedida() is False


def test_consumir_sem_pedido_nao_falha(tmp_path):
    consumir_pedido(tmp_path)
    consumir_pedido(tmp_path / "nao_existe")


def test_parada_composta_e_pedida_quando_qualquer_uma_e():
    assert ParadaComposta(ParadaFixa(False), ParadaFixa(False)).foi_pedida() is False
    assert ParadaComposta(ParadaFixa(False), ParadaFixa(True)).foi_pedida() is True
    assert ParadaComposta(ParadaFixa(True)).foi_pedida() is True
    assert ParadaComposta().foi_pedida() is False

"""Carga dos dados de uma sessão a partir do banco — T-05.

Comportamento em `.spec/features/exportacao-xlsx/spec.md`: AC-010.7 (a
exportação lê apenas do banco, sem vídeo e sem rede) e SUP-037 (sessão em
andamento é recusada).

Só as funções de leitura de `storage` são usadas: nenhum `manifest.json`,
`eventos.json` ou diretório de sessão é aberto aqui.
"""

import sqlite3
from dataclasses import dataclass

from auto_counter.storage.events import ler_eventos
from auto_counter.storage.minutes import ler_agregados
from auto_counter.storage.model import AgregadoDoMinuto, EventoGravado, SessaoGravada
from auto_counter.storage.sessions import ler_sessao


class SessaoNaoEncontradaError(LookupError):
    """A sessão citada não tem linha em `sessao`."""

    def __init__(self, id_sessao: str) -> None:
        self.id_sessao = id_sessao
        super().__init__(f"a sessão '{id_sessao}' não está gravada no banco")


class SessaoEmAndamentoError(RuntimeError):
    """A sessão ainda está em captura (status nulo): SUP-037."""

    def __init__(self, id_sessao: str) -> None:
        self.id_sessao = id_sessao
        super().__init__(
            f"a sessão '{id_sessao}' ainda está em andamento; a exportação de "
            f"sessão parcial é recusada, espere a captura terminar"
        )


class SessaoNaoProcessadaError(RuntimeError):
    """A captura terminou, mas não há processamento gravado para a sessão."""

    def __init__(self, id_sessao: str) -> None:
        self.id_sessao = id_sessao
        super().__init__(
            f"a sessão '{id_sessao}' não foi processada: não há contagem por "
            f"minuto gravada no banco; execute `session process` antes de "
            f"exportar"
        )


@dataclass(frozen=True)
class DadosDaExportacao:
    """Tudo o que as três abas precisam, como está gravado."""

    sessao: SessaoGravada
    eventos: tuple[EventoGravado, ...]
    agregados: tuple[AgregadoDoMinuto, ...]


def carregar(conexao: sqlite3.Connection, id_sessao: str) -> DadosDaExportacao:
    """Lê a sessão, os eventos e os agregados, ou recusa com erro explícito.

    Ordem das checagens: inexistente, em andamento, não processada (D-6 de
    `_tasks.md`).
    """
    sessao = ler_sessao(conexao, id_sessao)
    if sessao is None:
        raise SessaoNaoEncontradaError(id_sessao)
    if sessao.status is None:
        raise SessaoEmAndamentoError(id_sessao)

    agregados = ler_agregados(conexao, id_sessao)
    if sessao.versao_do_modelo is None or not agregados:
        raise SessaoNaoProcessadaError(id_sessao)

    return DadosDaExportacao(
        sessao=sessao,
        eventos=ler_eventos(conexao, id_sessao),
        agregados=agregados,
    )

"""Configuração compartilhada da suíte.

Fixtures comuns entram aqui conforme as tarefas que precisarem delas.
Nenhum teste deste projeto acessa o servidor da NitTrans.
"""

import socket
from contextlib import contextmanager
from unittest import mock

import pytest


class RedeBloqueadaError(OSError):
    """Tentativa de acesso à rede durante um trecho em que ela é proibida."""


@contextmanager
def rede_bloqueada():
    """Troca as portas de entrada do socket por funções que recusam e registram.

    Devolve a lista de tentativas, que fica vazia se nada tentou usar a rede.
    Existe à parte da fixture `sem_rede` porque a validação de acurácia roda
    numa fixture de escopo de sessão, onde `monkeypatch` não serve
    (AC-014.5 de `validacao-acuracia`).
    """
    tentativas: list[str] = []

    def recusar(nome: str):
        def _recusa(*args, **kwargs):
            tentativas.append(f"{nome}{args[1:] if nome.startswith('socket.') else args}")
            raise RedeBloqueadaError(
                f"{nome}: acesso à rede bloqueado durante a validação (AC-014.5)"
            )

        return _recusa

    with (
        mock.patch.object(socket.socket, "connect", recusar("socket.connect")),
        mock.patch.object(socket.socket, "connect_ex", recusar("socket.connect_ex")),
        mock.patch.object(socket, "create_connection", recusar("create_connection")),
        mock.patch.object(socket, "getaddrinfo", recusar("getaddrinfo")),
    ):
        yield tentativas


@pytest.fixture
def sem_rede():
    """Bloqueia a rede durante o teste e entrega a lista de tentativas."""
    with rede_bloqueada() as tentativas:
        yield tentativas

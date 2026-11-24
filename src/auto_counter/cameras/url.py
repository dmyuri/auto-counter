"""Montagem da URL do clipe de uma câmera.

Comportamento em `.spec/features/configuracao-camera/spec.md`: AC-001.4 (a URL
é `<base_url>/<id>/last_video.mp4`, com os zeros à esquerda do id preservados,
porque o id é string — SUP-001) e AC-001.5 (sem a base URL configurada a
montagem falha com erro explícito).

A base URL vem exclusivamente da variável de ambiente `AUTO_COUNTER_BASE_URL`.
Não existe aqui constante, `default=` ou fallback com o endereço da NitTrans:
`.spec/constitution.md` proíbe credencial ou endereço de acesso no código, e
AC-001.5 exige que a ausência da variável seja um erro, não um padrão.

A falha acontece antes de qualquer requisição de rede: este módulo só monta
texto, quem baixa é outro.
"""

import os

from auto_counter.cameras.model import Camera

VARIAVEL_BASE_URL = "AUTO_COUNTER_BASE_URL"
"""Nome da variável de ambiente que guarda a base URL dos vídeos."""

NOME_DO_CLIPE = "last_video.mp4"
"""Último clipe publicado pela câmera, sempre no mesmo nome."""


class BaseUrlAusenteError(Exception):
    """A base URL não está definida no ambiente (AC-001.5)."""


def base_url() -> str:
    """Devolve a base URL do ambiente, sem a barra final.

    Variável ausente, vazia ou só com espaços é o mesmo caso: erro explícito
    citando o nome da variável.
    """
    valor = (os.environ.get(VARIAVEL_BASE_URL) or "").strip()
    if not valor:
        raise BaseUrlAusenteError(
            f"a variável de ambiente {VARIAVEL_BASE_URL} não está definida. "
            "Ela é a única origem da base URL dos vídeos: não há endereço "
            "padrão embutido no código."
        )
    return valor.rstrip("/")


def url_do_clipe(camera: Camera) -> str:
    """URL do último clipe da câmera: `<base_url>/<id>/last_video.mp4`."""
    return f"{base_url()}/{camera.id}/{NOME_DO_CLIPE}"

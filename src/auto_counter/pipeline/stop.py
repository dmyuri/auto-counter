"""Pedido de parada por arquivo — T-05.

Comportamento em `.spec/features/interface-sessao/spec.md`: AC-012.4 (o
encerramento antecipado só acontece por ação explícita do usuário) e AC-012.5
(encerrar no processamento cancela a contagem).

A sessão roda num processo destacado da interface, então o botão de encerrar não
tem como chamar `ParadaPorCtrlC` nem tocar em memória do outro processo. O
pedido é o arquivo `<data_dir>/sessao.parar`: a interface o cria, e o processo
da sessão o consulta pelo mesmo protocolo `Parada` de `capture.session`.

Nada aqui apaga o pedido por conta própria. Quem o consome é a orquestração da
sessão (T-10), no início, na passagem da captura para o processamento e no fim:
sem esse consumo na passagem, encerrar a captura cancelaria também o
processamento, contra AC-003.6.
"""

import time
from pathlib import Path

NOME_DO_PEDIDO = "sessao.parar"
"""Nome do arquivo dentro do diretório de dados."""

TENTATIVAS_DE_REMOCAO = 5
ESPERA_ENTRE_TENTATIVAS = 0.05
"""No Windows, remover um arquivo que um leitor tem aberto levanta
`PermissionError` por instantes; algumas tentativas curtas bastam."""


def _caminho(data_dir: str | Path) -> Path:
    return Path(data_dir) / NOME_DO_PEDIDO


def pedir_parada(data_dir: str | Path) -> None:
    """Registra o pedido de encerramento. Idempotente."""
    caminho = _caminho(data_dir)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.touch()


def consumir_pedido(data_dir: str | Path) -> None:
    """Apaga o pedido, se houver. A ausência não é erro."""
    caminho = _caminho(data_dir)
    for tentativa in range(TENTATIVAS_DE_REMOCAO):
        try:
            caminho.unlink(missing_ok=True)
            return
        except PermissionError:
            if tentativa == TENTATIVAS_DE_REMOCAO - 1:
                raise
            time.sleep(ESPERA_ENTRE_TENTATIVAS)


class ParadaPorArquivo:
    """O protocolo `Parada` lido do arquivo de pedido."""

    def __init__(self, data_dir: str | Path) -> None:
        self._caminho = _caminho(data_dir)

    def foi_pedida(self) -> bool:
        return self._caminho.exists()


class ParadaComposta:
    """Pedida quando qualquer uma das paradas componentes foi pedida."""

    def __init__(self, *paradas) -> None:
        self._paradas = paradas

    def foi_pedida(self) -> bool:
        return any(parada.foi_pedida() for parada in self._paradas)

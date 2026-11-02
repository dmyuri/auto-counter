"""Resolução do diretório de dados, compartilhada por CLI e interface.

Comportamento em `.spec/features/interface-sessao/spec.md`: SUP-038 — a
interface chama a mesma camada de aplicação que a linha de comando, então o
diretório de dados não pode ser resolvido por um módulo da CLI.
"""

import os
from pathlib import Path

VARIAVEL_DATA_DIR = "AUTO_COUNTER_DATA_DIR"
"""Variável de ambiente com o diretório de dados das sessões."""

DATA_DIR_PADRAO = Path("data")
"""Diretório de dados usado quando a variável não está definida.

Não é segredo nem endereço de rede — é só onde os artefatos locais caem — e o
`.gitignore` já cobre `data/`, então nada gerado aqui escapa para o
repositório. A proibição de valor padrão embutido de AC-001.5 é sobre a base
URL, que continua vindo exclusivamente do ambiente.
"""


def data_dir_do_ambiente() -> Path:
    """Diretório de dados: `AUTO_COUNTER_DATA_DIR`, ou o padrão local."""
    valor = (os.environ.get(VARIAVEL_DATA_DIR) or "").strip()
    return Path(valor) if valor else DATA_DIR_PADRAO

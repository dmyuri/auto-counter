"""Identidade de conteúdo de um clipe — T-12.

Comportamento em `.spec/features/captura-clipes/spec.md`: implementa SUP-051, de
que AC-004.7 depende. O ETag identifica o **recurso** no servidor (SUP-009), não
o **arquivo**: a sessão `000013-20260908T050407Z` recebeu o mesmo vídeo nos
minutos 1 e 2 com ETags diferentes, porque o servidor trocou o Last-Modified sem
trocar o conteúdo. O sha256 dos bytes é o que separa clipe novo de clipe
republicado.

Este módulo só **calcula** o hash. Quem o compara para recusar o clipe é o laço
de captura (T-13), e quem o grava é o manifest (T-12).
"""

import hashlib
from pathlib import Path

PEDACO_DE_LEITURA = 1024 * 1024
"""Quanto se lê por vez, em bytes.

O clipe tem ~32 MB e a leitura é em pedaços pelo mesmo motivo de
`counting/model.py`: hashear o arquivo não pode significar carregá-lo inteiro na
memória de uma máquina de 8 GB que já está rodando inferência.
"""


def sha256_do_arquivo(caminho: str | Path) -> str:
    """O sha256 do conteúdo do arquivo, em hexadecimal (SUP-051).

    Do **conteúdo**, e não do nome nem da data: dois clipes só são o mesmo
    quando os bytes são os mesmos.
    """
    digestor = hashlib.sha256()
    with Path(caminho).open("rb") as arquivo:
        for pedaco in iter(lambda: arquivo.read(PEDACO_DE_LEITURA), b""):
            digestor.update(pedaco)
    return digestor.hexdigest()

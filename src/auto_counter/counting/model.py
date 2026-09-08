"""Provisionamento e identidade do modelo de detecção — T-03.

Não implementa critério de aceite: implementa SUP-015 (YOLO11n exportado para
ONNX, entrada 640×640) e a parte de "versão do modelo" de SUP-027, que AC-008.1
de `persistencia-resultados` consome.

O `.onnx` nunca entra no repositório (D-2): ele é produzido por um comando de
preparação de máquina, e o runtime depende só de `onnxruntime` e `supervision`.
Por isso `ultralytics` é importado **dentro** de `exportar`, e não no topo —
falta de dependência de desenvolvimento não pode derrubar o processamento.
"""

import hashlib
from pathlib import Path

NOME_DO_ARQUIVO_DO_MODELO = "yolo11n.onnx"
"""Nome do modelo exportado (SUP-015). Entra na versão como primeira metade."""

SUBDIRETORIO_DE_MODELOS = "models"
"""Onde o modelo cai dentro do diretório de dados (D-2)."""

TAMANHO_DE_ENTRADA = 640
"""Lado da entrada quadrada da exportação, em pixels (SUP-015)."""

DIGITOS_DO_HASH = 12
"""Quantos hex do sha256 entram na versão (SUP-027: hash *curto*)."""

COMANDO_DE_EXPORT = "auto-counter model export"
"""O comando que produz o modelo. Toda mensagem de ausência precisa citá-lo."""

_PEDACO_DE_LEITURA = 1024 * 1024
"""O modelo tem dezenas de MB; o hash é calculado sem carregá-lo inteiro."""


class ModeloAusenteError(Exception):
    """O `.onnx` não está onde o processamento o espera.

    A mensagem nasce aqui, e não no CLI, porque quem sabe o caminho esperado e
    o comando que o produz é este módulo; quem a apresenta é o CLI (T-13).
    """

    def __init__(self, caminho: Path) -> None:
        self.caminho = caminho
        super().__init__(
            f"o modelo de detecção não está em {caminho}. "
            f"Produza-o com: uv run {COMANDO_DE_EXPORT}"
        )


class UltralyticsAusenteError(Exception):
    """A exportação foi pedida sem a dependência de desenvolvimento (D-2)."""

    def __init__(self) -> None:
        super().__init__(
            "a exportação precisa do pacote 'ultralytics', que é dependência "
            "apenas de desenvolvimento. Instale-o com: uv sync --group dev"
        )


def caminho_do_modelo(data_dir: Path) -> Path:
    """`<data_dir>/models/yolo11n.onnx`.

    O `data_dir` chega por parâmetro: quem resolve `AUTO_COUNTER_DATA_DIR` é o
    CLI, com `VARIAVEL_DATA_DIR` e `DATA_DIR_PADRAO` de `auto_counter.cli`.
    """
    return Path(data_dir) / SUBDIRETORIO_DE_MODELOS / NOME_DO_ARQUIVO_DO_MODELO


def versao_do_modelo(caminho: Path) -> str:
    """`yolo11n.onnx@<12 primeiros hex do sha256 do conteúdo>` (SUP-027).

    O hash é do **conteúdo**, não do caminho nem da data: dois resultados só
    são comparáveis quando vieram do mesmo detector, e duas máquinas que
    exportaram o mesmo arquivo produzem a mesma versão.
    """
    caminho = Path(caminho)
    if not caminho.is_file():
        raise ModeloAusenteError(caminho)

    digestor = hashlib.sha256()
    with caminho.open("rb") as arquivo:
        for pedaco in iter(lambda: arquivo.read(_PEDACO_DE_LEITURA), b""):
            digestor.update(pedaco)

    return f"{caminho.name}@{digestor.hexdigest()[:DIGITOS_DO_HASH]}"


def exportar(destino: Path) -> Path:
    """Baixa o YOLO11n e o exporta para ONNX com entrada 640×640 (SUP-015).

    O `import ultralytics` é local de propósito (D-2): o runtime não pode
    quebrar por falta de uma dependência de desenvolvimento, e nenhum teste da
    suíte rápida chega até aqui.
    """
    destino = Path(destino)

    try:
        from ultralytics import YOLO
    except ImportError as falha:
        raise UltralyticsAusenteError() from falha

    destino.parent.mkdir(parents=True, exist_ok=True)

    modelo = YOLO("yolo11n.pt")
    exportado = Path(
        modelo.export(format="onnx", imgsz=TAMANHO_DE_ENTRADA, dynamic=False)
    )

    if exportado.resolve() != destino.resolve():
        destino.write_bytes(exportado.read_bytes())

    return destino

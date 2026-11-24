"""Formatação de tempo em MM:SS, comum à interface e à planilha.

Comportamento em `.spec/features/acompanhamento-ao-vivo/spec.md`: SUP-057. Usada
pelo progresso da sessão (`pipeline/progress.py`), pela lista de envio e pela
planilha da sessão de upload (D-10 de `processamento-upload`).

Fica fora de `pipeline` e de `export` de propósito, e só importa a stdlib:
`pipeline.lock` importa `export.format`, então `export` importar `pipeline`
fecha um ciclo de import.
"""


def formatar_tempo(segundos: int) -> str:
    """MM:SS, com os minutos passando de 59 sem virar hora (SUP-057)."""
    minutos, resto = divmod(int(segundos), 60)
    return f"{minutos:02d}:{resto:02d}"

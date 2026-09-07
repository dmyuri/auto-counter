"""Ponto de entrada da CLI `auto-counter`.

A raiz hospeda um subgrupo por área: `camera` é o da feature
`configuracao-camera`. Os comandos concretos entram nas tarefas que os
especificam — aqui só existe o esqueleto que faz `--help` responder.
"""

import typer

app = typer.Typer(
    name="auto-counter",
    help="Contagem e classificação automática de veículos por visão computacional.",
    no_args_is_help=True,
)

camera_app = typer.Typer(
    name="camera",
    help="Câmeras cadastradas e calibração da linha de contagem.",
    no_args_is_help=True,
)


@camera_app.callback()
def camera() -> None:
    """Câmeras cadastradas e calibração da linha de contagem."""


app.add_typer(camera_app, name="camera")

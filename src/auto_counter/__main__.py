"""Permite `python -m auto_counter`, o ponto de entrada do processo destacado.

A interface dispara `python -m auto_counter session run ...` num processo que
não depende dela (AC-012.4 de `.spec/features/interface-sessao/spec.md`): o
executável `auto-counter` não é garantido no PATH de quem abriu a interface,
mas o interpretador atual é.
"""

from auto_counter.cli import app

if __name__ == "__main__":
    app(prog_name="auto-counter")

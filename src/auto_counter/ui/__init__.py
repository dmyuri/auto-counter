"""Interface local da sessão, uma casca Streamlit sobre `auto_counter.pipeline`.

Comportamento definido em `.spec/features/interface-sessao/spec.md`. Este
pacote **não importa o Streamlit**: o comando `auto-counter ui` só precisa do
caminho de `app.py`, e carregar a biblioteca aqui faria a CLI inteira pagar por
ela.
"""

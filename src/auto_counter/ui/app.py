"""Script Streamlit da interface da sessão.

Comportamento em `.spec/features/interface-sessao/spec.md`: AC-011.1 (a lista de
câmeras, pelo nome do local, sem campo para digitar id, URL ou endereço),
AC-011.2 (duração inteira de 1 a 15 minutos, padrão 15), AC-011.3 (sem câmera
válida, aviso e botão indisponível) e AC-013.1 (com sessão em andamento, o botão
fica indisponível e a mensagem diz qual).

Esta é só a casca (SUP-038): nenhuma regra de captura, contagem ou exportação
mora aqui. O script importa apenas `streamlit`, a biblioteca padrão, `dotenv` e
`auto_counter.pipeline`, e é o `pipeline` que lê o progresso e dispara a sessão.
"""

import argparse
import sys
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from auto_counter.pipeline import launch
from auto_counter.pipeline.ambiente import data_dir_do_ambiente
from auto_counter.pipeline.cameras import (
    DIRETORIO_PADRAO,
    DURACAO_MAXIMA,
    DURACAO_MINIMA,
    DURACAO_PADRAO,
    cameras_disponiveis,
)
from auto_counter.pipeline.lock import OutraSessaoEmAndamentoError
from auto_counter.pipeline.progress import Situacao, ler_progresso


def _diretorio_de_cameras() -> Path:
    """`--config-dir`, repassado depois do `--` por `auto-counter ui`."""
    analisador = argparse.ArgumentParser(add_help=False)
    analisador.add_argument("--config-dir", default=str(DIRETORIO_PADRAO))
    argumentos, _ = analisador.parse_known_args(sys.argv[1:])
    return Path(argumentos.config_dir)


def _formulario(config_dir: Path, data_dir: Path) -> None:
    progresso = ler_progresso(data_dir)
    em_andamento = progresso.situacao in (
        Situacao.EM_ANDAMENTO,
        Situacao.EM_ANDAMENTO_PELO_TERMINAL,
    )
    disponiveis = cameras_disponiveis(config_dir)

    if em_andamento:
        st.info(progresso.mensagem_de_recusa)

    id_escolhida = None
    if disponiveis.cameras:
        nomes = {camera.id: camera.nome for camera in disponiveis.cameras}
        # O usuário lê o nome do local; o id fica só do lado de dentro (AC-011.1).
        id_escolhida = st.selectbox(
            "Câmera", options=list(nomes), format_func=lambda id_: nomes[id_]
        )
    else:
        st.warning("Nenhuma câmera disponível.")
        if disponiveis.motivo:
            st.caption(disponiveis.motivo)

    minutos = st.number_input(
        "Duração (minutos)",
        min_value=DURACAO_MINIMA,
        max_value=DURACAO_MAXIMA,
        value=DURACAO_PADRAO,
        step=1,
    )

    indisponivel = em_andamento or id_escolhida is None
    if st.button("Iniciar sessão", disabled=indisponivel, type="primary"):
        try:
            disparada = launch.iniciar_sessao(
                id_escolhida,
                int(minutos),
                data_dir=data_dir,
                config_dir=config_dir,
            )
        except OutraSessaoEmAndamentoError as falha:
            st.error(str(falha))
            return
        except Exception as falha:  # noqa: BLE001 — a tela nunca mostra traceback
            st.error(f"Não foi possível iniciar a sessão: {falha}")
            return

        problema = launch.aguardar_inicio(disparada)
        if problema is None:
            st.rerun()
        else:
            st.error(f"A sessão não iniciou: {problema}")


def main() -> None:
    load_dotenv()
    st.set_page_config(page_title="Contagem de veículos", layout="centered")
    st.title("Contagem de veículos")
    _formulario(_diretorio_de_cameras(), data_dir_do_ambiente())


main()

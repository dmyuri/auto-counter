"""Script Streamlit da interface da sessão.

Comportamento em `.spec/features/interface-sessao/spec.md`: AC-011.1 (a lista de
câmeras, pelo nome do local, sem campo para digitar id, URL ou endereço),
AC-011.2 (duração inteira de 1 a 15 minutos, padrão 15), AC-011.3 (sem câmera
válida, aviso e botão indisponível) e AC-013.1 (com sessão em andamento, o botão
fica indisponível e a mensagem diz qual).

Também acompanha a sessão: AC-012.1 e AC-012.2 (minutos capturados do total,
perdidos e a fase), AC-012.3 (status e download da planilha), AC-012.4 (fechar e
reabrir a aba reencontra a sessão, e só o botão de encerrar, com confirmação,
pede o fim antecipado), AC-012.5 (processamento cancelado, sem download) e
AC-012.6 (sem planilha, com o status).

E, por `acompanhamento-ao-vivo`, as quantidades por categoria e o tempo da
sessão: AC-016.1 e AC-016.5 (quantidades no processamento, aviso na captura),
AC-017.1 (tempo decorrido) e AC-018.1 a AC-018.4 (quantidades finais e tempo
total no resultado). A tela só exibe o que `ler_progresso` devolve (SUP-058).

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
from auto_counter.pipeline.progress import (
    Andamento,
    Quantidades,
    Resultado,
    Situacao,
    formatar_tempo,
    ler_progresso,
)
from auto_counter.pipeline.state import Fase

MIME_DO_XLSX = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)

ATUALIZACAO_EM_SEGUNDOS = 2
"""De quanto em quanto tempo a área da sessão se relê do disco (D-17)."""

CHAVE_CONFIRMANDO = "confirmando_encerramento"

AVISO_SEM_CONTAGEM_NA_CAPTURA = (
    "A contagem de veículos começa quando a captura terminar."
)
"""AC-016.5: na captura não há quantidade, nem zero (SUP-055)."""

AVISO_DE_ENCERRAR = {
    Fase.CAPTURA: (
        "Encerrar agora? Os minutos já capturados serão processados, e a sessão "
        "terá a duração que realmente aconteceu."
    ),
    Fase.PROCESSAMENTO: (
        "Encerrar agora? A contagem será cancelada, nada será gravado e os "
        "vídeos serão mantidos para reprocessar depois."
    ),
}


def _diretorio_de_cameras() -> Path:
    """`--config-dir`, repassado depois do `--` por `auto-counter ui`."""
    analisador = argparse.ArgumentParser(add_help=False)
    analisador.add_argument("--config-dir", default=str(DIRETORIO_PADRAO))
    argumentos, _ = analisador.parse_known_args(sys.argv[1:])
    return Path(argumentos.config_dir)


def _pedir_confirmacao() -> None:
    st.session_state[CHAVE_CONFIRMANDO] = True


def _voltar() -> None:
    st.session_state[CHAVE_CONFIRMANDO] = False


def _confirmar(data_dir: Path) -> None:
    st.session_state[CHAVE_CONFIRMANDO] = False
    launch.encerrar_sessao(data_dir)


def _quantidades(quantidades: Quantidades) -> None:
    """As cinco métricas, na ordem de D-8; o total já vem somado (SUP-054)."""
    valores = (
        ("Carro", quantidades.carro),
        ("Ônibus", quantidades.onibus),
        ("Caminhão", quantidades.caminhao),
        ("Moto", quantidades.moto),
        ("Total", quantidades.total),
    )
    for coluna, (rotulo, valor) in zip(st.columns(len(valores)), valores):
        coluna.metric(rotulo, valor)


def _andamento(andamento: Andamento, data_dir: Path) -> None:
    """A sessão em curso: fase, progresso e o botão de encerrar (AC-012.1/2)."""
    if andamento.fase is Fase.CAPTURA:
        resolvidos = andamento.capturados + len(andamento.perdidos)
        st.markdown(
            f"**Capturando** — {andamento.capturados} de {andamento.pedidos} "
            f"minutos capturados, {len(andamento.perdidos)} perdidos"
        )
        if andamento.perdidos:
            st.caption(
                "Minutos perdidos: " + ", ".join(str(m) for m in andamento.perdidos)
            )
        total = andamento.pedidos
    else:
        resolvidos = andamento.processados
        st.markdown(
            f"**Processando** — {andamento.processados} de {andamento.a_processar} "
            f"minutos analisados"
        )
        total = andamento.a_processar
    st.progress(min(1.0, resolvidos / total) if total else 0.0)

    if andamento.quantidades is None:
        st.info(AVISO_SEM_CONTAGEM_NA_CAPTURA)
    else:
        _quantidades(andamento.quantidades)
    st.markdown(f"Tempo decorrido: {formatar_tempo(andamento.tempo_decorrido)}")

    if not andamento.pode_encerrar:
        return
    if not st.session_state.get(CHAVE_CONFIRMANDO, False):
        st.button("Encerrar sessão", on_click=_pedir_confirmacao)
        return
    st.warning(AVISO_DE_ENCERRAR[andamento.fase])
    st.button("Confirmar encerramento", on_click=_confirmar, args=(data_dir,))
    st.button("Voltar", on_click=_voltar)


def _tempo_total(resultado: Resultado) -> None:
    """AC-018.1 e AC-018.3; sem instante de término, nada é mostrado (AC-018.4)."""
    if resultado.tempo_total is not None:
        st.markdown(f"Tempo total: {formatar_tempo(resultado.tempo_total)}")


def _resultado(resultado: Resultado) -> None:
    """O desfecho da última sessão (AC-012.3, AC-012.5 e AC-012.6)."""
    if resultado.fase is Fase.CONCLUIDA:
        st.success(f"Sessão concluída — status {resultado.status}.")
        if resultado.aviso:
            st.warning(resultado.aviso)
        if resultado.quantidades is not None:
            _quantidades(resultado.quantidades)
        _tempo_total(resultado)
        if resultado.planilha is not None:
            try:
                dados = resultado.planilha.read_bytes()
            except OSError as falha:
                st.error(f"Não foi possível ler a planilha: {falha}")
                return
            st.download_button(
                "Baixar planilha (XLSX)",
                data=dados,
                file_name=resultado.planilha.name,
                mime=MIME_DO_XLSX,
            )
        elif resultado.mensagem:
            st.warning(resultado.mensagem)
    elif resultado.fase is Fase.SEM_PLANILHA:
        st.warning(
            f"Status da sessão: {resultado.status}. {resultado.mensagem}"
        )
        _tempo_total(resultado)
    elif resultado.fase is Fase.PROCESSAMENTO_CANCELADO:
        st.info(f"Processamento cancelado. {resultado.mensagem}")
        _tempo_total(resultado)
    else:
        st.error(resultado.mensagem or "A sessão falhou.")
        _tempo_total(resultado)


def _area_da_sessao(data_dir: Path, estava_em_andamento: bool) -> None:
    """Acompanha a sessão e mostra o resultado, relendo só do disco (AC-012.4).

    Roda como fragmento que se atualiza sozinho. Quando a sessão começa ou
    termina, pede a página inteira de novo, para o formulário refletir o novo
    estado.
    """
    progresso = ler_progresso(data_dir)
    em_andamento = progresso.situacao in (
        Situacao.EM_ANDAMENTO,
        Situacao.EM_ANDAMENTO_PELO_TERMINAL,
    )
    if em_andamento != estava_em_andamento:
        st.rerun()

    if progresso.situacao is Situacao.EM_ANDAMENTO:
        _andamento(progresso.andamento, data_dir)
    elif progresso.situacao is Situacao.TERMINADA:
        st.session_state[CHAVE_CONFIRMANDO] = False
        _resultado(progresso.resultado)
    elif not em_andamento:
        st.session_state[CHAVE_CONFIRMANDO] = False


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
    data_dir = data_dir_do_ambiente()
    em_andamento = ler_progresso(data_dir).situacao in (
        Situacao.EM_ANDAMENTO,
        Situacao.EM_ANDAMENTO_PELO_TERMINAL,
    )
    st.fragment(run_every=ATUALIZACAO_EM_SEGUNDOS)(_area_da_sessao)(
        data_dir, em_andamento
    )
    _formulario(_diretorio_de_cameras(), data_dir)


main()

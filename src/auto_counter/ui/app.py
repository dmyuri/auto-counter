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

E, por `layout-interface`, a tela tem três painéis (Configuração, ao vivo e
resultados) e um cabeçalho com o estado do sistema e o botão de tema: AC-019.1 a
AC-019.6 (indicador e tema) e AC-023.5 a AC-023.7 (depois do resultado, só "Nova
sessão" libera a configuração, e só nesta aba). O tema é CSS injetado a cada
execução (SUP-062). A escolha de tema e a dispensa do resultado ficam em
`st.session_state`: a interface não grava nada em disco (SUP-058, SUP-064,
SUP-074).

Esta é só a casca (SUP-038): nenhuma regra de captura, contagem ou exportação
mora aqui. O script importa apenas `streamlit`, a biblioteca padrão, `dotenv` e
`auto_counter.pipeline`, e é o `pipeline` que lê o progresso e dispara a sessão.
"""

import argparse
import sys
from dataclasses import dataclass
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
    Progresso,
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
CHAVE_TEMA = "tema"
CHAVE_RESULTADO_DISPENSADO = "resultado_dispensado"
"""A `chave` do resultado que "Nova sessão" dispensou nesta aba (D-9, SUP-074)."""

TEMA_ESCURO = "escuro"
TEMA_CLARO = "claro"

VARIAVEIS_DO_TEMA_ESCURO = {
    "--bg": "#0c0e0d",
    "--panel": "#141715",
    "--panel2": "#1a1e1b",
    "--line": "#262b28",
    "--ink": "#eef1ee",
    "--muted": "#8d958f",
    "--accent": "oklch(0.83 0.19 150)",
    "--accentInk": "#05130a",
    "--accentSoft": "oklch(0.83 0.19 150 / 0.12)",
    "--danger": "oklch(0.7 0.18 25)",
    "--stripe": "#1d211e",
}
VARIAVEIS_DO_TEMA_CLARO = {
    "--bg": "#f3f4f2",
    "--panel": "#ffffff",
    "--panel2": "#f7f8f6",
    "--line": "#dde1dc",
    "--ink": "#111412",
    "--muted": "#596159",
    "--accent": "oklch(0.52 0.15 150)",
    "--accentInk": "#ffffff",
    "--accentSoft": "oklch(0.52 0.15 150 / 0.1)",
    "--danger": "oklch(0.55 0.19 25)",
    "--stripe": "#eceee9",
}
"""As cores dos dois temas, copiadas do protótipo (D-12, SUP-062)."""

CSS_DOS_COMPONENTES = """
.stApp, [data-testid="stHeader"] {
  background: var(--bg); color: var(--ink);
  font-family: 'IBM Plex Sans', system-ui, sans-serif;
}
.stApp p, .stApp label, .stApp li, .stApp h1, .stApp h2, .stApp h3 {
  color: var(--ink);
}
[data-testid="stCaptionContainer"] { color: var(--muted); }
[data-testid="stVerticalBlockBorderWrapper"] {
  background: var(--panel); border-color: var(--line); border-radius: 12px;
}
[data-testid="stMetricValue"], [data-testid="stNumberInput"] input {
  font-family: 'JetBrains Mono', monospace;
}
.stButton > button, .stDownloadButton > button {
  background: var(--panel2); color: var(--ink); border: 1px solid var(--line);
}
.stButton > button[kind="primary"] {
  background: var(--accent); color: var(--accentInk); border-color: var(--accent);
}
.stProgress > div > div { background-color: var(--stripe); }
.stProgress > div > div > div { background-color: var(--accent); }
input, [data-baseweb="select"] > div {
  background: var(--panel2); color: var(--ink); border-color: var(--line);
}
.indicador {
  display: inline-block; padding: 4px 12px; border-radius: 999px;
  background: var(--accentSoft); color: var(--accent);
  border: 1px solid var(--line);
}
"""
"""Regras que aplicam o visual do protótipo sobre os componentes nativos (D-12).

Não pode conter palavras que os testes procuram no texto da página
(`textos(at)` concatena todo `markdown`).
"""

INDICADOR_AGUARDANDO = "Aguardando"
INDICADOR_CAPTURANDO = "Capturando"
INDICADOR_PROCESSANDO = "Processando"
INDICADOR_EM_ANDAMENTO = "Em andamento"
INDICADOR_FINALIZADO = "Finalizado"

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


@dataclass(frozen=True)
class EstadoDaTela:
    """O que está na tela nesta aba, a partir do disco e do que a aba dispensou."""

    indicador: str
    resultado_na_tela: bool
    configuracao_travada: bool
    sessao_em_andamento: bool


def estado_da_tela(progresso: Progresso, dispensado: str | None) -> EstadoDaTela:
    """A regra de apresentação de D-9: indicador, resultado e trava.

    Resultado na tela é a sessão terminada cuja chave esta aba ainda não
    dispensou com "Nova sessão". Só apresentação: nada é contado nem gravado.
    """
    em_andamento = progresso.situacao in (
        Situacao.EM_ANDAMENTO,
        Situacao.EM_ANDAMENTO_PELO_TERMINAL,
    )
    resultado_na_tela = (
        progresso.situacao is Situacao.TERMINADA
        and progresso.resultado.chave != dispensado
    )
    if progresso.situacao is Situacao.EM_ANDAMENTO:
        capturando = progresso.andamento.fase is Fase.CAPTURA
        indicador = INDICADOR_CAPTURANDO if capturando else INDICADOR_PROCESSANDO
    elif progresso.situacao is Situacao.EM_ANDAMENTO_PELO_TERMINAL:
        indicador = INDICADOR_EM_ANDAMENTO
    elif resultado_na_tela:
        indicador = INDICADOR_FINALIZADO
    else:
        indicador = INDICADOR_AGUARDANDO
    return EstadoDaTela(
        indicador=indicador,
        resultado_na_tela=resultado_na_tela,
        configuracao_travada=em_andamento or resultado_na_tela,
        sessao_em_andamento=em_andamento,
    )


def _tela(data_dir: Path) -> tuple[Progresso, EstadoDaTela]:
    progresso = ler_progresso(data_dir)
    return progresso, estado_da_tela(
        progresso, st.session_state.get(CHAVE_RESULTADO_DISPENSADO)
    )


def _css_do_tema(tema: str) -> str:
    variaveis = (
        VARIAVEIS_DO_TEMA_CLARO if tema == TEMA_CLARO else VARIAVEIS_DO_TEMA_ESCURO
    )
    declaracoes = " ".join(f"{nome}: {valor};" for nome, valor in variaveis.items())
    return f":root {{ {declaracoes} }}\n{CSS_DOS_COMPONENTES}"


def _alternar_tema() -> None:
    atual = st.session_state.get(CHAVE_TEMA, TEMA_ESCURO)
    st.session_state[CHAVE_TEMA] = TEMA_ESCURO if atual == TEMA_CLARO else TEMA_CLARO


def _dispensar_resultado(chave: str) -> None:
    """"Nova sessão": esta aba para de mostrar o resultado (AC-023.6, SUP-074)."""
    st.session_state[CHAVE_RESULTADO_DISPENSADO] = chave


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


def _area_da_sessao(data_dir: Path, indicador_da_pagina: str) -> None:
    """Acompanha a sessão e mostra o resultado, relendo só do disco (AC-012.4).

    Roda como fragmento que se atualiza sozinho. Quando o indicador do
    cabeçalho muda (D-10), pede a página inteira de novo, para o cabeçalho, o
    botão principal e os controles acompanharem a troca de fase e o fim da
    sessão sem esperar ação do usuário.
    """
    progresso, tela = _tela(data_dir)
    if tela.indicador != indicador_da_pagina:
        st.rerun()

    if progresso.situacao is Situacao.EM_ANDAMENTO:
        with st.container(border=True):
            _andamento(progresso.andamento, data_dir)
    elif tela.resultado_na_tela:
        st.session_state[CHAVE_CONFIRMANDO] = False
        with st.container(border=True):
            _resultado(progresso.resultado)
    elif not tela.sessao_em_andamento:
        st.session_state[CHAVE_CONFIRMANDO] = False


def _configuracao(
    config_dir: Path, data_dir: Path, progresso: Progresso, tela: EstadoDaTela
) -> None:
    """Painel de Configuração: câmera, duração e o botão principal (D-18)."""
    disponiveis = cameras_disponiveis(config_dir)
    travada = tela.configuracao_travada

    if tela.sessao_em_andamento:
        st.info(progresso.mensagem_de_recusa)

    id_escolhida = None
    if disponiveis.cameras:
        nomes = {camera.id: camera.nome for camera in disponiveis.cameras}
        if st.session_state.get("camera") not in nomes:
            st.session_state.pop("camera", None)
        # Os controles travados continuam desenhados (D-11): o Streamlit descarta
        # o estado de widget que não é desenhado, e é ele que devolve a câmera e
        # a duração anteriores depois de "Nova sessão" (AC-023.6).
        # O usuário lê o nome do local; o id fica só do lado de dentro (AC-011.1).
        id_escolhida = st.selectbox(
            "Câmera",
            options=list(nomes),
            format_func=lambda id_: nomes[id_],
            key="camera",
            disabled=travada,
        )
    else:
        st.warning("Nenhuma câmera disponível.")
        if disponiveis.motivo:
            st.caption(disponiveis.motivo)

    st.session_state.setdefault("duracao", DURACAO_PADRAO)
    minutos = st.number_input(
        "Duração (minutos)",
        min_value=DURACAO_MINIMA,
        max_value=DURACAO_MAXIMA,
        step=1,
        key="duracao",
        disabled=travada,
    )

    if tela.resultado_na_tela:
        st.button(
            "Nova sessão",
            type="primary",
            on_click=_dispensar_resultado,
            args=(progresso.resultado.chave,),
        )
        return

    indisponivel = tela.sessao_em_andamento or id_escolhida is None
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


def _cabecalho(tela: EstadoDaTela) -> None:
    """Título, estado do sistema e botão de tema (US-019)."""
    titulo, indicador, botao = st.columns([5, 2, 2], vertical_alignment="center")
    titulo.title("Contagem de veículos")
    indicador.markdown(
        f'<span class="indicador">{tela.indicador}</span>', unsafe_allow_html=True
    )
    escuro = st.session_state[CHAVE_TEMA] == TEMA_ESCURO
    botao.button(
        "Tema claro" if escuro else "Tema escuro",
        key="botao_tema",
        on_click=_alternar_tema,
    )


def main() -> None:
    load_dotenv()
    st.set_page_config(page_title="Contagem de veículos", layout="wide")
    st.session_state.setdefault(CHAVE_TEMA, TEMA_ESCURO)
    st.markdown(
        f"<style>{_css_do_tema(st.session_state[CHAVE_TEMA])}</style>",
        unsafe_allow_html=True,
    )
    data_dir = data_dir_do_ambiente()
    progresso, tela = _tela(data_dir)

    _cabecalho(tela)
    configuracao, ao_vivo = st.columns([2, 3])
    with configuracao:
        with st.container(border=True):
            _configuracao(_diretorio_de_cameras(), data_dir, progresso, tela)
    with ao_vivo:
        st.fragment(run_every=ATUALIZACAO_EM_SEGUNDOS)(_area_da_sessao)(
            data_dir, tela.indicador
        )


main()

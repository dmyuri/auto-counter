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
sessão" libera a configuração, e só nesta aba). A câmera é escolhida por
cartões com id, nome e prévia: AC-020.1 a AC-020.6 (SUP-065 a SUP-067). A
duração tem atalhos de 5, 10 e 15 minutos: AC-021.1 a AC-021.3. O painel ao vivo
mostra título, participação, taxa, tempo estimado e percentual (AC-022.1 a
AC-022.7), e a sessão é encerrada por "Parar antecipadamente", no painel de
Configuração, com confirmação (AC-023.1, SUP-071). O resultado é o painel
"Sessão finalizada", com o cartão da planilha e a marca "✓ Baixado" (AC-023.2 a
AC-023.4, SUP-073, SUP-075). O tema é CSS injetado a cada
execução (SUP-062). A escolha de tema e a dispensa do resultado ficam em
`st.session_state`: a interface não grava nada em disco (SUP-058, SUP-064,
SUP-074).

Esta é só a casca (SUP-038): nenhuma regra de captura, contagem ou exportação
mora aqui. O script importa apenas `streamlit`, a biblioteca padrão, `dotenv` e
`auto_counter.pipeline`, e é o `pipeline` que lê o progresso e dispara a sessão.

E, por `download-clipes`, o painel de Configuração tem a opção "Manter
clipes de vídeo", desligada por padrão (AC-024.1), repassada a
`launch.iniciar_sessao` ao iniciar (AC-024.2, AC-024.3) e indisponível com
sessão em andamento ou resultado na tela (AC-024.4).

E, no painel "Sessão finalizada", a lista dos clipes mantidos com um botão de
download por clipe e o botão do `.zip` (AC-025.1 a AC-025.4, SUP-073, D-6, D-7),
só com os clipes presentes em disco e o aviso dos ausentes (AC-025.5), nada disso
quando a sessão foi cancelada, ficou sem planilha ou falhou (AC-025.6), e a
mensagem de AC-024.3 quando os clipes não foram mantidos. Nome, tamanho, presença
e `.zip` vêm do `pipeline` (SUP-038).

E, por `upload-videos`, o painel de Configuração tem a escolha da fonte, "Câmera
ao vivo" (padrão) ou "Fazer upload de vídeos" (AC-026.1). Com o upload, a
duração, os atalhos e a opção de manter clipes não aparecem (AC-026.2, AC-024.5)
e voltam com o valor de antes (R-4); os cartões continuam, aparecem o aviso da
câmera e a área de envio, e "Iniciar sessão" não é desenhado. Na fonte ao vivo
nada muda, e a lista de envio nunca entra na sessão (AC-026.4). Com sessão em
andamento ou resultado na tela, a fonte e a área de envio ficam travadas
(AC-026.5).
"""

import argparse
import sys
from dataclasses import dataclass
from functools import partial
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
    previa_da_camera,
)
from auto_counter.pipeline.clipes import montar_zip
from auto_counter.pipeline.lista_envio import aviso_da_camera
from auto_counter.pipeline.lock import OutraSessaoEmAndamentoError
from auto_counter.pipeline.progress import (
    TAXA_SEM_DADO,
    Andamento,
    ClipeParaBaixar,
    Participacoes,
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
# De quanto em quanto tempo a área da sessão se relê do disco (D-17).

CHAVE_CONFIRMANDO = "confirmando_encerramento"
CHAVE_TEMA = "tema"
CHAVE_DURACAO = "duracao"
ATALHOS_DE_DURACAO = (5, 10, 15)
# Os atalhos só escolhem valores dentro de 1 a 15 minutos (AC-011.2, D-15).
CHAVE_PLANILHA_BAIXADA = "planilha_baixada"
# A `chave` do resultado cuja planilha foi baixada nesta aba (D-9, SUP-073).
CHAVE_CAMERA = "camera"
# O id da câmera selecionada nesta aba; padrão, a primeira do registro (D-13).
CHAVE_RESULTADO_DISPENSADO = "resultado_dispensado"
# A `chave` do resultado que "Nova sessão" dispensou nesta aba (D-9, SUP-074).
CHAVE_MANTER_CLIPES = "manter_clipes"
CHAVE_FONTE = "fonte"
FONTE_CAMERA = "camera"
FONTE_UPLOAD = "upload"
ROTULO_DA_FONTE = {FONTE_CAMERA: "Câmera ao vivo", FONTE_UPLOAD: "Fazer upload de vídeos"}
SUBTITULO_DA_FONTE = {
    FONTE_CAMERA: "Acessa o feed e processa em tempo real",
    FONTE_UPLOAD: "Processa arquivos enviados manualmente",
}
CHAVE_ENVIO_GERACAO = "envio_geracao"
# A opção "Manter clipes de vídeo" (AC-024.1, D-8 de `download-clipes`).
CHAVE_CLIPES_BAIXADOS = "clipes_baixados"
# Conjunto de `f"{chave}:{minuto}"` dos clipes cujo botão foi acionado (D-7).
CHAVE_ZIP_BAIXADO = "zip_baixado"
# A `chave` do resultado cujo `.zip` foi baixado nesta aba (D-7, SUP-073).
MIME_DO_MP4 = "video/mp4"
MIME_DO_ZIP = "application/zip"
MENSAGEM_CLIPES_NAO_MANTIDOS = "Clipes não foram mantidos nesta sessão."
# AC-024.3: a sessão terminou sem que a opção estivesse ligada.

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
# As cores dos dois temas, copiadas do protótipo (D-12, SUP-062).

CSS_DOS_COMPONENTES = """
/* base */
.stApp {
  background: var(--bg); color: var(--ink);
  font-family: 'IBM Plex Sans', system-ui, sans-serif;
  font-size: 15px; line-height: 1.45;
}
[data-testid="stHeader"], [data-testid="stToolbar"],
[data-testid="stAppDeployButton"] { display: none; }
[data-testid="stMainBlockContainer"] { max-width: none; padding: 0; gap: 0; }
[data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] li,
.stApp label, .stApp label p { color: var(--ink); }
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p {
  color: var(--muted);
}
.rotulo {
  font-family: 'JetBrains Mono', monospace; font-size: 12px;
  letter-spacing: .1em; text-transform: uppercase; color: var(--muted);
}
.rotulo--acento { color: var(--accent); letter-spacing: 0; text-transform: none; }
.linha-rotulo { display: flex; justify-content: space-between; align-items: baseline; }

/* seletor de fonte: dois blocos lado a lado, o marcado em destaque */
.st-key-fonte, .st-key-fonte [data-testid="stRadio"] { width: 100%; }
.st-key-fonte [data-testid="stWidgetLabel"] { display: none; }
.st-key-fonte [data-testid="stRadioGroup"] {
  display: flex; flex-direction: row; align-items: stretch; gap: 0; width: 100%;
  border: 1px solid var(--line);
}
.st-key-fonte [data-testid="stRadioGroup"] > div {
  flex: 1 1 0; display: flex; align-items: stretch; margin: 0;
}
.st-key-fonte [data-testid="stRadioOption"] {
  flex: 1; margin: 0; padding: 12px 14px; width: 100%; align-items: flex-start;
  background: var(--panel); cursor: pointer;
}
.st-key-fonte [data-testid="stRadioOption"] > div { align-items: flex-start; }
.st-key-fonte [data-testid="stRadioOption"] > div > div:first-child { display: none; }
.st-key-fonte [data-testid="stRadioOption"] [data-testid="stMarkdownContainer"] p {
  margin: 0; font-size: 13px; line-height: 1.35; color: var(--muted);
}
.st-key-fonte [data-testid="stRadioOption"] [data-testid="stMarkdownContainer"] p:first-child {
  font-size: 15px; color: var(--ink);
}
.st-key-fonte [data-testid="stRadioOption"] strong {
  font-family: 'JetBrains Mono', monospace; font-weight: 700; color: var(--ink);
}
.st-key-fonte [data-testid="stRadioOption"]:has(input:checked) { background: var(--accent); }
.st-key-fonte [data-testid="stRadioOption"]:has(input:checked) p,
.st-key-fonte [data-testid="stRadioOption"]:has(input:checked) strong { color: var(--accentInk); }
.st-key-fonte [data-testid="stRadioOption"]:has(input:disabled) { opacity: .55; cursor: not-allowed; }

/* header */
.st-key-cabecalho {
  padding: 16px clamp(16px, 3vw, 32px); border-bottom: 1px solid var(--line);
}
.marca { display: flex; align-items: center; gap: 12px; }
.marca__quadro { width: 12px; height: 12px; background: var(--accent); }
.marca__nome { font-weight: 600; letter-spacing: .02em; color: var(--ink); }
.marca__sub {
  font-family: 'JetBrains Mono', monospace; font-size: 12px; color: var(--muted);
}
.indicador {
  display: flex; align-items: center; justify-content: flex-end; gap: 8px;
  font-family: 'JetBrains Mono', monospace; font-size: 12px;
  text-transform: uppercase; letter-spacing: .08em; color: var(--muted);
}
.indicador::before {
  content: ""; width: 8px; height: 8px; border-radius: 50%;
  background: var(--muted);
}
.indicador[data-estado="ativo"]::before { background: var(--accent); }
.indicador[data-estado="final"]::before { background: var(--ink); }

/* layout */
.st-key-principal {
  max-width: 1440px; margin: 0 auto; width: 100%;
  padding: 24px clamp(16px, 3vw, 32px); gap: 24px;
}
[class*="st-key-painel_"] {
  background: var(--panel); border: 1px solid var(--line);
  padding: 24px; gap: 20px;
}
.st-key-painel_resultados { border-color: var(--accent); }
.st-key-painel_ao_vivo { display: flex; flex-direction: column; }
[class*="st-key-painel_"] h3 {
  font-family: 'JetBrains Mono', monospace; font-size: 12px; font-weight: 400;
  letter-spacing: .1em; text-transform: uppercase; color: var(--muted);
  padding: 0;
}
.st-key-painel_resultados h3 { color: var(--accent); }

/* buttons */
.stApp button {
  font-family: 'JetBrains Mono', monospace; border-radius: 0;
  background: transparent; color: var(--ink); border: 1px solid var(--line);
}
.stApp button * {
  color: inherit; font-family: inherit; font-weight: inherit;
  font-size: inherit; letter-spacing: inherit; text-transform: inherit;
}
.stApp button:hover { border-color: var(--ink); color: var(--ink); }
.stApp button:disabled { opacity: .55; cursor: not-allowed; color: var(--ink); }
.stApp button[data-testid="stBaseButton-primary"]:disabled {
  color: var(--accentInk);
}
[data-testid="stNumberInput"] input:disabled {
  color: var(--ink); -webkit-text-fill-color: var(--ink); opacity: 1;
}
.stApp button[data-testid="stBaseButton-primary"] {
  background: var(--accent); color: var(--accentInk); border: none;
  font-weight: 700;
}
.stApp button[data-testid="stBaseButton-primary"]:hover {
  filter: brightness(1.08); color: var(--accentInk);
}
.st-key-botao_tema { width: 100%; display: flex; justify-content: flex-end; }
.st-key-botao_tema button {
  width: auto; font-size: 12px; min-height: 36px; padding: 0 12px;
}
.st-key-botao_tema button p::before { content: "◐  "; }
.st-key-iniciar_sessao, .st-key-nova_sessao, .st-key-parar_antecipadamente,
.st-key-confirmar_encerramento, .st-key-voltar { width: 100%; }
.st-key-iniciar_sessao button, .st-key-nova_sessao button,
.st-key-parar_antecipadamente button {
  width: 100%; min-height: 56px; font-size: 15px; font-weight: 700;
  letter-spacing: .08em; text-transform: uppercase;
}
.st-key-iniciar_sessao button:disabled { opacity: .4; }
.st-key-confirmar_encerramento button, .st-key-voltar button {
  width: 100%; min-height: 44px;
}
.st-key-parar_antecipadamente button, .st-key-confirmar_encerramento button {
  color: var(--danger); border: 1px solid var(--danger); background: transparent;
}

/* camera cards */
[class*="st-key-cartao_camera_"] {
  position: relative; background: var(--panel2); border: 2px solid var(--line);
  gap: 0;
}
[class*="st-key-cartao_camera_"]:hover { border-color: var(--muted); }
[class*="st-key-cartao_camera_"]:has([data-testid="stBaseButton-primary"]) {
  border-color: var(--accent);
}
[class*="st-key-cartao_camera_"]:has(button:disabled) { opacity: .55; }
[class*="st-key-cartao_camera_"] img {
  display: block; width: 100%; aspect-ratio: 16 / 9; object-fit: cover;
  border-radius: 0;
}
[class*="st-key-cartao_camera_"] [data-testid="stCaptionContainer"] {
  display: flex; align-items: center; justify-content: center;
  aspect-ratio: 16 / 9;
  background: repeating-linear-gradient(
    135deg, var(--stripe) 0 8px, transparent 8px 16px);
}
[class*="st-key-cartao_camera_"] [data-testid="stCaptionContainer"] p {
  font-family: 'JetBrains Mono', monospace; font-size: 11px;
}
[class*="st-key-cartao_camera_"] [data-testid="stMarkdownContainer"] {
  padding: 10px 12px 14px;
}
[class*="st-key-cartao_camera_"] [data-testid="stMarkdownContainer"] p {
  margin: 0; line-height: 1.3;
}
[class*="st-key-cartao_camera_"] code {
  display: block; font-family: 'JetBrains Mono', monospace; font-size: 13px;
  font-weight: 700; background: transparent; color: var(--ink); padding: 0;
}
[class*="st-key-cartao_camera_"] strong {
  display: block; font-size: 13px; font-weight: 400; color: var(--muted);
}
[class*="st-key-camera_"] {
  position: absolute; inset: 0; width: 100% !important; height: 100%;
  z-index: 2;
}
[class*="st-key-camera_"] button {
  width: 100%; height: 100%; opacity: 0; border: none; cursor: pointer;
}
[class*="st-key-camera_"]:has(button[data-testid="stBaseButton-primary"]) {
  inset: 6px 6px auto auto; width: auto !important; height: auto;
}
[class*="st-key-camera_"] button[data-testid="stBaseButton-primary"] {
  width: auto !important; height: auto !important; min-height: 0 !important;
  opacity: 1; padding: 2px 6px !important; font-size: 10px;
  line-height: 1.4; pointer-events: none;
}
[class*="st-key-camera_"] button[data-testid="stBaseButton-primary"] * {
  margin: 0; padding: 0; line-height: 1.4; font-size: 10px;
}

/* duration */
[data-testid="stNumberInput"] input {
  font-family: 'JetBrains Mono', monospace; font-size: 20px; font-weight: 700;
  color: var(--ink);
}
[data-baseweb="input"], [data-baseweb="base-input"],
[data-testid="stNumberInputContainer"] {
  background: var(--panel2); border-radius: 0; border-color: var(--line);
}
[data-testid="stNumberInputContainer"] { border: 1px solid var(--line); }
[class*="st-key-atalho_"] { width: 100%; }
[class*="st-key-atalho_"] button {
  width: 100%; min-height: 44px; font-size: 13px; font-weight: 400;
}
[data-testid="stNumberInput"] input, [data-testid="stNumberInputContainer"] {
  min-height: 44px;
}
[class*="st-key-atalho_"] button[data-testid="stBaseButton-primary"],
[class*="st-key-atalho_"] button[data-testid="stBaseButton-primary"]:disabled {
  background: var(--accentSoft); color: var(--accent);
  border: 1px solid var(--accent); font-weight: 400;
}

/* live panel: the order below puts the total first, like the prototype */
.st-key-painel_ao_vivo > :has(.st-key-total),
.st-key-painel_ao_vivo > :has(.st-key-captura_destaque) { order: 2; }
.st-key-painel_ao_vivo > :has(.st-key-categorias) { order: 3; }
.st-key-painel_ao_vivo > :has(.st-key-tempos) { order: 4; }
.st-key-painel_ao_vivo > :has(.st-key-progresso) { order: 5; }
[data-testid="stMetricValue"] p {
  font-family: 'JetBrains Mono', monospace; font-weight: 700;
  font-variant-numeric: tabular-nums; line-height: 1;
}
[data-testid="stMetricLabel"] p { color: var(--muted); }
.st-key-total {
  background: var(--accentSoft); border: 1px solid var(--line); padding: 20px;
}
.st-key-total [data-testid="stMetricLabel"] p {
  font-family: 'JetBrains Mono', monospace; font-size: 12px;
  letter-spacing: .1em; text-transform: uppercase;
}
.st-key-total [data-testid="stMetricValue"] p {
  font-size: clamp(56px, 9vw, 104px); color: var(--accent);
}
.st-key-categorias [data-testid="stColumn"] {
  position: relative; background: var(--panel2); border: 1px solid var(--line);
  padding: 16px; gap: 10px;
}
.st-key-categorias [data-testid="stMetricLabel"] p { font-size: 14px; }
.st-key-categorias [data-testid="stMetricValue"] p {
  font-size: 44px; color: var(--ink);
}
[class*="st-key-participacao_"] {
  position: absolute; top: 16px; right: 16px; width: auto;
}
[class*="st-key-participacao_"] p {
  font-family: 'JetBrains Mono', monospace; font-size: 11px;
  color: var(--muted); margin: 0;
}
[data-testid="stProgress"] [data-testid="stProgressBarTrack"] {
  background: var(--panel2); border: 1px solid var(--line);
  border-radius: 0; height: 10px;
}
[data-testid="stProgress"] [data-testid="stProgressBarTrack"] > div {
  background: var(--accent); border-radius: 0;
}
.st-key-categorias [data-testid="stProgress"] [data-testid="stProgressBarTrack"] {
  height: 4px; background: var(--line); border: none;
}
.st-key-tempos [data-testid="stColumn"] { gap: 4px; }
[class*="st-key-rotulo_"] [data-testid="stMarkdownContainer"] p {
  font-family: 'JetBrains Mono', monospace; font-size: 12px; margin: 0;
  letter-spacing: .1em; text-transform: uppercase; color: var(--muted);
}
[class*="st-key-valor_"] [data-testid="stMarkdownContainer"] p {
  font-family: 'JetBrains Mono', monospace; font-size: 32px; font-weight: 700;
  line-height: 1.1; margin: 0; font-variant-numeric: tabular-nums;
  color: var(--ink);
}
.st-key-valor_estimado [data-testid="stMarkdownContainer"] p {
  color: var(--muted);
}
.st-key-progresso [data-testid="stMarkdownContainer"] p {
  font-family: 'JetBrains Mono', monospace; font-size: 12px; color: var(--muted);
}
.st-key-taxa p {
  text-align: right; font-family: 'JetBrains Mono', monospace; font-size: 12px;
  color: var(--accent); margin: 0;
}

/* capture: notice in the slot of the total */
.st-key-captura_destaque {
  background: var(--accentSoft); border: 1px solid var(--accent);
  padding: 28px 20px; animation: pulso 2.4s ease-in-out infinite;
}
.st-key-captura_destaque [data-testid="stAlertContainer"] {
  background: transparent !important; border: none !important;
}
.st-key-captura_destaque [data-testid="stAlert"] p {
  font-family: 'JetBrains Mono', monospace; font-size: 15px;
  letter-spacing: .04em;
}
@keyframes pulso { 50% { border-color: var(--line); } }

/* right column: live panel and, below it, the result */
[data-testid="stColumn"]:has(.st-key-painel_ao_vivo) { gap: 24px; }

/* result panel */
.st-key-planilha_cartao {
  background: var(--panel2); border: 1px solid var(--line); padding: 16px;
}
.icone-arquivo {
  display: flex; align-items: center; justify-content: center;
  width: 40px; height: 40px; background: var(--accentSoft);
  border: 1px solid var(--accent); color: var(--accent);
  font-family: 'JetBrains Mono', monospace; font-size: 10px; font-weight: 700;
}
.st-key-planilha_cartao [data-testid="stDownloadButton"] button {
  background: var(--accent); color: var(--accentInk); border: none;
  font-weight: 700;
}

.st-key-clipes_lista {
  background: var(--panel2); border: 1px solid var(--line); padding: 16px;
  gap: 8px;
}
.st-key-clipes_lista [data-testid="stMarkdownContainer"] p { margin: 0; }
[class*="st-key-clipe_"] [data-testid="stDownloadButton"] button {
  width: 100%; min-height: 36px; font-size: 12px;
}
.st-key-clipes_zip [data-testid="stDownloadButton"] button {
  background: var(--accent); color: var(--accentInk); border: none;
  font-weight: 700; width: 100%;
}

/* clip retention toggle */
.st-key-manter_clipes_cartao {
  background: var(--panel2); border: 1px solid var(--line); padding: 16px;
}
.st-key-manter_clipes_cartao [data-testid="stMarkdownContainer"] p { margin: 0; font-size: 14px; }
.st-key-manter_clipes_cartao [data-testid="stCaptionContainer"] p { margin: 2px 0 0; font-size: 12px; }
.st-key-manter_clipes_cartao [data-testid="stCheckbox"] { display: flex; justify-content: flex-end; }
.st-key-manter_clipes_cartao [data-testid="stCheckbox"] label {
  display: flex; align-items: center; cursor: pointer;
}
.st-key-manter_clipes_cartao [data-testid="stCheckbox"] label > div:first-of-type {
  width: 56px; height: 28px; border-radius: 1px; position: relative;
  background: var(--line); border: 1px solid var(--line); flex: none;
  transition: background .15s ease, border-color .15s ease;
}
.st-key-manter_clipes_cartao [data-testid="stCheckbox"] label > div:first-of-type::after {
  content: ""; position: absolute; top: 4px; left: 4px;
  width: 20px; height: 20px; border-radius: 1px;
  background: var(--bg); transition: left .15s ease;
}
.st-key-manter_clipes_cartao [data-testid="stCheckbox"] label:has(input:checked)
> div:first-of-type {
  background: var(--accent); border-color: var(--accent);
}
.st-key-manter_clipes_cartao [data-testid="stCheckbox"] label:has(input:checked)
> div:first-of-type::after {
  left: calc(100% - 24px);
}
.st-key-manter_clipes_cartao [data-testid="stCheckbox"] label > div:first-of-type svg {
  display: none;
}
.st-key-manter_clipes_cartao [data-testid="stCheckbox"]:has(input:disabled) { opacity: .55; }

/* notices */
[data-testid="stAlertContainer"] {
  border-radius: 0; background: var(--accentSoft) !important;
  border: 1px solid var(--accent) !important;
}
[data-testid="stAlert"] * { color: var(--ink); }
"""
# Regras que aplicam o visual do protótipo sobre os componentes nativos (D-12).
#
# Os seletores `st-key-…` vêm das chaves dos contêineres e botões, e os
# `data-testid` são os do Streamlit. Não carrega fonte da internet: a interface
# roda em 127.0.0.1 e tem de funcionar sem rede, então vale o fallback.
#
# Não pode conter palavras que os testes procuram no texto da página
# (`textos(at)` concatena todo `markdown`, inclusive este bloco).

INDICADOR_AGUARDANDO = "Aguardando"
INDICADOR_CAPTURANDO = "Capturando"
INDICADOR_PROCESSANDO = "Processando"
INDICADOR_EM_ANDAMENTO = "Em andamento"
INDICADOR_FINALIZADO = "Finalizado"

ESTADO_DO_INDICADOR = {
    INDICADOR_AGUARDANDO: "parado",
    INDICADOR_CAPTURANDO: "ativo",
    INDICADOR_PROCESSANDO: "ativo",
    INDICADOR_EM_ANDAMENTO: "ativo",
    INDICADOR_FINALIZADO: "final",
}
# Só para o CSS: a cor da bolinha do indicador.

AVISO_SEM_CONTAGEM_NA_CAPTURA = (
    "A contagem de veículos começa quando a captura terminar."
)
# AC-016.5: na captura não há quantidade, nem zero (SUP-055).

MENSAGEM_DO_TERMINAL = (
    "Sessão iniciada pelo terminal: a interface não acompanha o progresso dela."
)
MENSAGEM_SEM_CONTAGEM = "Sem contagem a exibir para esta sessão."
# AC-018.3 e AC-018.4: sessão cancelada, sem planilha, que falhou ou de processo
# morto não mostra quantidade nenhuma, nem zero.

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


def _selecionar_camera(id_camera: str) -> None:
    """Acionar um cartão: só aquela câmera passa a ser a selecionada (AC-020.3)."""
    st.session_state[CHAVE_CAMERA] = id_camera


def _definir_duracao(minutos: int) -> None:
    """Atalho de duração: grava o valor no próprio campo (AC-021.1)."""
    st.session_state[CHAVE_DURACAO] = minutos


def _marcar_baixada(chave: str) -> None:
    """Registra que o botão foi acionado nesta aba (SUP-073).

    Não confirma que o navegador gravou o arquivo: o Streamlit não tem como saber.
    """
    st.session_state[CHAVE_PLANILHA_BAIXADA] = chave


def _marcar_clipe_baixado(chave: str, minuto: int) -> None:
    """Registra o acionamento do botão de um clipe nesta aba (SUP-073)."""
    baixados = set(st.session_state.get(CHAVE_CLIPES_BAIXADOS, ()))
    baixados.add(f"{chave}:{minuto}")
    st.session_state[CHAVE_CLIPES_BAIXADOS] = baixados


def _marcar_zip_baixado(chave: str) -> None:
    """Registra o acionamento do botão do `.zip` nesta aba (SUP-073)."""
    st.session_state[CHAVE_ZIP_BAIXADO] = chave


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


def _categorias(quantidades: Quantidades, participacoes: Participacoes) -> None:
    """Quantidade, participação e barra de cada categoria, e depois o total.

    Os números já vêm prontos de `ler_progresso` (SUP-038); a ordem das métricas
    é a de D-8 de `acompanhamento-ao-vivo`. Na tela, o CSS põe o total acima das
    categorias, grande e em verde, como no protótipo.
    """
    categorias = (
        ("Carro", quantidades.carro, participacoes.carro),
        ("Ônibus", quantidades.onibus, participacoes.onibus),
        ("Caminhão", quantidades.caminhao, participacoes.caminhao),
        ("Moto", quantidades.moto, participacoes.moto),
    )
    with st.container(key="categorias"):
        for coluna, (rotulo, quantidade, participacao) in zip(
            st.columns(len(categorias)), categorias
        ):
            with coluna:
                st.metric(rotulo, quantidade)
                with st.container(key=f"participacao_{rotulo}"):
                    st.markdown(f"{participacao}%")
                st.progress(participacao)
    with st.container(key="total"):
        st.metric("Total", quantidades.total)


def _cabecalho_ao_vivo(titulo: str, taxa: str | None) -> None:
    """O título do painel e, à direita, a taxa (AC-022.1, AC-022.3)."""
    coluna_titulo, coluna_taxa = st.columns([3, 1], vertical_alignment="center")
    coluna_titulo.subheader(titulo)
    if taxa is not None:
        with coluna_taxa:
            with st.container(key="taxa"):
                st.markdown(taxa)


def _corpo_ao_vivo(
    *,
    percentual: int,
    quantidades: Quantidades | None,
    participacoes: Participacoes | None,
    decorrido: str,
    estimado: str,
) -> None:
    """Barra, categorias (ou o aviso da captura) e tempos, na ordem do protótipo.

    Sem `participacoes`, é a captura: nenhuma quantidade, nem zero, e o aviso em
    destaque no lugar do total (AC-016.5, AC-022.7, SUP-055).
    """
    with st.container(key="progresso"):
        st.progress(percentual)
        st.markdown(f"{percentual}% concluído")
    if participacoes is None:
        with st.container(key="captura_destaque"):
            st.info(AVISO_SEM_CONTAGEM_NA_CAPTURA)
    else:
        _categorias(quantidades, participacoes)
    # Rótulo pequeno acima e valor grande abaixo, como no protótipo: são dois
    # elementos, e é o CSS que dá a cada um o seu estilo (AC-017.1, AC-022.5).
    with st.container(key="tempos"):
        coluna_decorrido, coluna_estimado = st.columns(2)
        with coluna_decorrido:
            with st.container(key="rotulo_decorrido"):
                st.markdown("Tempo decorrido")
            with st.container(key="valor_decorrido"):
                st.markdown(decorrido)
        with coluna_estimado:
            with st.container(key="rotulo_estimado"):
                st.markdown("Tempo estimado")
            with st.container(key="valor_estimado"):
                st.markdown(estimado)


def _andamento(andamento: Andamento) -> None:
    """A sessão em curso (D-16): título, fase, progresso, categorias e tempos."""
    _cabecalho_ao_vivo(
        f"Contagem ao vivo · {andamento.nome_camera or andamento.id_camera}",
        andamento.taxa,
    )
    if andamento.fase is Fase.CAPTURA:
        st.markdown(
            f"**Capturando** — {andamento.capturados} de {andamento.pedidos} "
            f"minutos capturados, {len(andamento.perdidos)} perdidos"
        )
        if andamento.perdidos:
            st.caption(
                "Minutos perdidos: " + ", ".join(str(m) for m in andamento.perdidos)
            )
    else:
        st.markdown(
            f"**Processando** — {andamento.processados} de {andamento.a_processar} "
            f"minutos analisados"
        )
    _corpo_ao_vivo(
        percentual=andamento.percentual,
        quantidades=andamento.quantidades,
        participacoes=andamento.participacoes,
        decorrido=formatar_tempo(andamento.tempo_decorrido),
        estimado=(
            "—"
            if andamento.tempo_estimado is None
            else formatar_tempo(andamento.tempo_estimado)
        ),
    )


def _ao_vivo_final(resultado: Resultado) -> None:
    """Os valores finais da sessão concluída, no painel ao vivo (AC-018.1)."""
    _cabecalho_ao_vivo(
        f"Contagem ao vivo · {resultado.nome_camera or resultado.id_camera}",
        resultado.taxa,
    )
    _corpo_ao_vivo(
        percentual=100,
        quantidades=resultado.quantidades,
        participacoes=resultado.participacoes,
        decorrido=(
            "—"
            if resultado.tempo_total is None
            else formatar_tempo(resultado.tempo_total)
        ),
        estimado=formatar_tempo(0),
    )


def _ao_vivo_ocioso() -> None:
    """Sem sessão e sem resultado na tela: zeros e 00:00, como no protótipo.

    Não é captura, então AC-016.5 e SUP-055 não se aplicam.
    """
    _cabecalho_ao_vivo("Contagem ao vivo", TAXA_SEM_DADO)
    _corpo_ao_vivo(
        percentual=0,
        quantidades=Quantidades(carro=0, onibus=0, caminhao=0, moto=0),
        participacoes=Participacoes(carro=0, onibus=0, caminhao=0, moto=0),
        decorrido=formatar_tempo(0),
        estimado=formatar_tempo(0),
    )


def _ao_vivo_sem_numeros(titulo: str, mensagem: str) -> None:
    """Sessão do terminal ou desfecho sem contagem: nenhum número (AC-018.3/4)."""
    _cabecalho_ao_vivo(titulo, None)
    st.caption(mensagem)


def _painel_ao_vivo(progresso: Progresso, tela: EstadoDaTela) -> None:
    """O painel "Contagem ao vivo", sempre na tela, com o conteúdo de cada estado."""
    with st.container(key="painel_ao_vivo"):
        if progresso.situacao is Situacao.EM_ANDAMENTO:
            _andamento(progresso.andamento)
        elif progresso.situacao is Situacao.EM_ANDAMENTO_PELO_TERMINAL:
            _ao_vivo_sem_numeros("Contagem ao vivo", MENSAGEM_DO_TERMINAL)
        elif tela.resultado_na_tela:
            resultado = progresso.resultado
            if resultado.fase is Fase.CONCLUIDA and resultado.quantidades is not None:
                _ao_vivo_final(resultado)
            else:
                titulo = "Contagem ao vivo"
                if resultado.nome_camera:
                    titulo += f" · {resultado.nome_camera}"
                _ao_vivo_sem_numeros(titulo, MENSAGEM_SEM_CONTAGEM)
        else:
            _ao_vivo_ocioso()


def _parar_antecipadamente(andamento: Andamento, data_dir: Path) -> None:
    """O botão de encerrar, com confirmação, no lugar de "Iniciar sessão"."""
    if not andamento.pode_encerrar:
        return
    if not st.session_state.get(CHAVE_CONFIRMANDO, False):
        st.button(
            "Parar antecipadamente",
            key="parar_antecipadamente",
            on_click=_pedir_confirmacao,
        )
        return
    st.warning(AVISO_DE_ENCERRAR[andamento.fase])
    st.button(
        "Confirmar encerramento",
        key="confirmar_encerramento",
        on_click=_confirmar,
        args=(data_dir,),
    )
    st.button("Voltar", key="voltar", on_click=_voltar)


def _tempo_total(resultado: Resultado) -> None:
    """AC-018.1 e AC-018.3; sem instante de término, nada é mostrado (AC-018.4)."""
    if resultado.tempo_total is not None:
        st.markdown(f"Tempo total: {formatar_tempo(resultado.tempo_total)}")


def _desfecho_da_conclusao(resultado: Resultado) -> None:
    """"Concluída · MM:SS" ou "Interrompida pelo usuário · MM:SS" (AC-023.2).

    Substitui a linha "Tempo total" na sessão concluída, para o tempo não
    aparecer duas vezes. Sem o tempo total (estado antigo), só o texto.
    """
    texto = (
        "Interrompida pelo usuário"
        if resultado.encerrada_pelo_usuario
        else "Concluída"
    )
    if resultado.tempo_total is not None:
        texto += f" · {formatar_tempo(resultado.tempo_total)}"
    st.markdown(f"**{texto}**")


def _cartao_da_planilha(resultado: Resultado) -> None:
    """Nome do arquivo, número de registros e o botão de baixar (AC-023.2/3)."""
    try:
        dados = resultado.planilha.read_bytes()
    except OSError as falha:
        st.error(f"Não foi possível ler a planilha: {falha}")
        return
    registros = "—" if resultado.registros is None else resultado.registros
    baixada = st.session_state.get(CHAVE_PLANILHA_BAIXADA) == resultado.chave
    with st.container(key="planilha_cartao"):
        icone, texto, botao = st.columns([1, 5, 3], vertical_alignment="center")
        icone.markdown('<div class="icone-arquivo">XLSX</div>', unsafe_allow_html=True)
        with texto:
            st.markdown(f"**{resultado.planilha.name}**")
            st.caption(f"{registros} registros · contagem por categoria e por minuto")
        with botao:
            st.download_button(
                "✓ Baixado" if baixada else "Baixar .xlsx",
                data=dados,
                file_name=resultado.planilha.name,
                mime=MIME_DO_XLSX,
                on_click=_marcar_baixada,
                args=(resultado.chave,),
            )


def _bytes_do_clipe(caminho: Path) -> bytes:
    return caminho.read_bytes()


def _bytes_do_zip(clipes: tuple[ClipeParaBaixar, ...]) -> bytes:
    return montar_zip([(c.caminho, c.nome) for c in clipes])


def _linha_do_clipe(clipe: ClipeParaBaixar, resultado: Resultado, zip_baixado: bool):
    """Nome, duração, tamanho e o botão de um clipe (AC-025.1, AC-025.3)."""
    baixado = zip_baixado or (
        f"{resultado.chave}:{clipe.minuto}"
        in st.session_state.get(CHAVE_CLIPES_BAIXADOS, ())
    )
    with st.container(key=f"clipe_{clipe.minuto}"):
        nome, duracao, tamanho, botao = st.columns(
            [5, 1, 1.5, 1.5], vertical_alignment="center"
        )
        nome.markdown(clipe.nome)
        duracao.markdown(clipe.duracao)
        tamanho.markdown(clipe.tamanho)
        with botao:
            st.download_button(
                "✓" if baixado else "Baixar",
                data=partial(_bytes_do_clipe, clipe.caminho),
                file_name=clipe.nome,
                mime=MIME_DO_MP4,
                key=f"baixar_clipe_{resultado.chave}_{clipe.minuto}",
                on_click=_marcar_clipe_baixado,
                args=(resultado.chave, clipe.minuto),
            )


def _clipes(resultado: Resultado) -> None:
    """Os clipes mantidos da sessão concluída (D-10, AC-024.3, AC-025.1 a 25.5)."""
    if not resultado.manter_clipes:
        st.info(MENSAGEM_CLIPES_NAO_MANTIDOS)
        return
    if resultado.clipes_ausentes:
        st.warning(f"{resultado.clipes_ausentes} clipes não estão mais em disco.")
    if not resultado.clipes:
        return
    zip_baixado = st.session_state.get(CHAVE_ZIP_BAIXADO) == resultado.chave
    with st.container(key="clipes_lista"):
        st.markdown(f"**{resultado.titulo_dos_clipes}**")
        for clipe in resultado.clipes:
            _linha_do_clipe(clipe, resultado, zip_baixado)
        with st.container(key="clipes_zip"):
            st.download_button(
                "✓ Baixado" if zip_baixado else "Baixar todos (.zip)",
                data=partial(_bytes_do_zip, resultado.clipes),
                file_name=f"{resultado.id_camera}_clipes.zip",
                mime=MIME_DO_ZIP,
                key=f"baixar_zip_{resultado.chave}",
                on_click=_marcar_zip_baixado,
                args=(resultado.chave,),
            )


def _resultado(resultado: Resultado) -> None:
    """O painel "Sessão finalizada" (AC-023.2 a AC-023.4)."""
    st.subheader("Sessão finalizada")
    if resultado.fase is Fase.CONCLUIDA:
        _desfecho_da_conclusao(resultado)
        st.markdown(f"status {resultado.status}")
        if resultado.aviso:
            st.warning(resultado.aviso)
        if resultado.planilha is not None:
            _cartao_da_planilha(resultado)
        elif resultado.mensagem:
            st.warning(resultado.mensagem)
        _clipes(resultado)
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
    """Painel ao vivo e, abaixo dele, o resultado, relendo só do disco (AC-012.4).

    Roda como fragmento que se atualiza sozinho. Quando o indicador do
    cabeçalho muda (D-10), pede a página inteira de novo, para o cabeçalho, o
    botão principal e os controles acompanharem a troca de fase e o fim da
    sessão sem esperar ação do usuário.
    """
    progresso, tela = _tela(data_dir)
    if tela.indicador != indicador_da_pagina:
        st.rerun()

    _painel_ao_vivo(progresso, tela)
    if tela.resultado_na_tela:
        st.session_state[CHAVE_CONFIRMANDO] = False
        with st.container(key="painel_resultados"):
            _resultado(progresso.resultado)
    elif not tela.sessao_em_andamento:
        st.session_state[CHAVE_CONFIRMANDO] = False


def _cartao(camera, config_dir: Path, id_selecionada: str, travada: bool) -> None:
    """Cartão da câmera: prévia ou "sem prévia", id, nome e o botão (D-13).

    A prévia é a imagem fixa que o mantenedor indicou: a interface não acessa a
    câmera para obtê-la (AC-020.2). Id e nome aparecem como texto; não há campo
    para digitar id, URL ou endereço (AC-020.1, SUP-067).
    """
    selecionada = camera.id == id_selecionada
    with st.container(key=f"cartao_camera_{camera.id}"):
        previa = previa_da_camera(camera, config_dir)
        if previa is None:
            st.caption("sem prévia")
        else:
            st.image(previa, width="stretch")
        st.markdown(f"`{camera.id}` **{camera.nome}**")
        st.button(
            "SELECIONADA" if selecionada else "Selecionar",
            key=f"camera_{camera.id}",
            type="primary" if selecionada else "secondary",
            disabled=travada,
            on_click=_selecionar_camera,
            args=(camera.id,),
        )


def _rotulo_da_fonte(fonte: str) -> str:
    """Título em negrito e subtítulo abaixo, como no protótipo."""
    return f"**{ROTULO_DA_FONTE[fonte]}**\n\n{SUBTITULO_DA_FONTE[fonte]}"


def _duracao_e_saida(travada: bool) -> None:
    """Duração, atalhos e a opção de manter clipes: só na fonte ao vivo."""
    st.markdown(
        '<div class="linha-rotulo"><span class="rotulo">Duração</span>'
        f'<span class="rotulo rotulo--acento">máximo {DURACAO_MAXIMA} min</span></div>',
        unsafe_allow_html=True,
    )
    st.session_state.setdefault(CHAVE_DURACAO, DURACAO_PADRAO)
    # Só o atalho igual à duração atual fica destacado; um valor digitado fora
    # de 5, 10 e 15 não destaca nenhum (AC-021.1, AC-021.2). Travados, os
    # atalhos continuam desenhados (D-11, AC-021.3).
    campo, *colunas_dos_atalhos = st.columns([2, 1, 1, 1], vertical_alignment="bottom")
    with campo:
        st.number_input(
            "Duração (minutos)",
            min_value=DURACAO_MINIMA,
            max_value=DURACAO_MAXIMA,
            step=1,
            key=CHAVE_DURACAO,
            disabled=travada,
            label_visibility="collapsed",
        )
    for coluna, atalho in zip(colunas_dos_atalhos, ATALHOS_DE_DURACAO):
        coluna.button(
            f"{atalho} min",
            key=f"atalho_{atalho}",
            type="primary" if st.session_state[CHAVE_DURACAO] == atalho else "secondary",
            disabled=travada,
            on_click=_definir_duracao,
            args=(atalho,),
        )

    st.markdown('<span class="rotulo">Saída</span>', unsafe_allow_html=True)
    st.session_state.setdefault(CHAVE_MANTER_CLIPES, False)
    with st.container(key="manter_clipes_cartao"):
        texto, controle = st.columns([5, 1], vertical_alignment="center")
        with texto:
            st.markdown("**Manter clipes de vídeo**")
            st.caption(
                "Salva os trechos processados para download ao final. A "
                "planilha .xlsx é sempre gerada."
            )
        with controle:
            st.checkbox(
                "Manter clipes de vídeo",
                key=CHAVE_MANTER_CLIPES,
                disabled=travada,
                label_visibility="collapsed",
            )


def _camera_por_id(cameras, id_camera: str | None):
    return next((c for c in cameras if c.id == id_camera), None)


def _area_de_envio(camera, travada: bool) -> None:
    """Aviso da câmera e área de envio da fonte de upload (AC-026.2, D-12).

    O que chega no `file_uploader` é tratado na T-07; aqui só é desenhado,
    sem `type=`, para a recusa por extensão ser a mensagem do app (D-3).
    """
    if camera is not None:
        st.info(aviso_da_camera(camera))
    st.session_state.setdefault(CHAVE_ENVIO_GERACAO, 0)
    st.file_uploader(
        "Vídeos",
        accept_multiple_files=True,
        key=f"envio_{st.session_state[CHAVE_ENVIO_GERACAO]}",
        disabled=travada,
        label_visibility="collapsed",
    )


def _configuracao(
    config_dir: Path, data_dir: Path, progresso: Progresso, tela: EstadoDaTela
) -> None:
    """Painel de Configuração: câmera, duração e o botão principal (D-18)."""
    disponiveis = cameras_disponiveis(config_dir)
    travada = tela.configuracao_travada
    st.markdown('<span class="rotulo">Configuração</span>', unsafe_allow_html=True)
    st.markdown('<span class="rotulo">01 · Fonte</span>', unsafe_allow_html=True)
    st.session_state.setdefault(CHAVE_FONTE, FONTE_CAMERA)
    st.radio(
        "Fonte",
        [FONTE_CAMERA, FONTE_UPLOAD],
        format_func=_rotulo_da_fonte,
        horizontal=True,
        key=CHAVE_FONTE,
        disabled=travada,
        label_visibility="collapsed",
    )
    st.markdown('<span class="rotulo">Câmera</span>', unsafe_allow_html=True)

    if tela.sessao_em_andamento:
        st.info(progresso.mensagem_de_recusa)

    id_escolhida = None
    if disponiveis.cameras:
        ids = [camera.id for camera in disponiveis.cameras]
        # Sem escolha, ou com um id que sumiu do registro, vale a primeira (D-13).
        if st.session_state.get(CHAVE_CAMERA) not in ids:
            st.session_state[CHAVE_CAMERA] = ids[0]
        id_escolhida = st.session_state[CHAVE_CAMERA]
        # Cartões e duração travados continuam desenhados (D-11): o Streamlit
        # descarta o estado de widget que não é desenhado, e é ele que devolve a
        # duração anterior depois de "Nova sessão" (AC-023.6).
        # Três cartões por linha, na ordem do registro (SUP-065).
        cameras = disponiveis.cameras
        for inicio in range(0, len(cameras), 3):
            for coluna, camera in zip(st.columns(3), cameras[inicio : inicio + 3]):
                with coluna:
                    _cartao(camera, config_dir, id_escolhida, travada)
    else:
        st.warning("Nenhuma câmera disponível.")
        if disponiveis.motivo:
            st.caption(disponiveis.motivo)

    if st.session_state[CHAVE_FONTE] == FONTE_CAMERA:
        _duracao_e_saida(travada)
    else:
        # Fonte de upload: duração, atalhos e "Manter clipes" não são
        # desenhados (AC-026.2). Regravar as chaves impede o Streamlit de
        # descartar o valor delas (R-4, D-11).
        for chave in (CHAVE_DURACAO, CHAVE_MANTER_CLIPES):
            if chave in st.session_state:
                st.session_state[chave] = st.session_state[chave]
        _area_de_envio(
            _camera_por_id(disponiveis.cameras, id_escolhida), travada
        )

    if tela.resultado_na_tela:
        st.button(
            "Nova sessão",
            key="nova_sessao",
            type="primary",
            on_click=_dispensar_resultado,
            args=(progresso.resultado.chave,),
        )
        return

    if progresso.situacao is Situacao.EM_ANDAMENTO:
        # Sessão da interface: o botão de iniciar não é desenhado (AC-023.1).
        _parar_antecipadamente(progresso.andamento, data_dir)
        return

    if st.session_state[CHAVE_FONTE] == FONTE_UPLOAD:
        # O botão de processar é da T-08; "Iniciar sessão" é só da câmera ao vivo.
        return

    indisponivel = tela.sessao_em_andamento or id_escolhida is None
    if st.button(
        "Iniciar sessão",
        key="iniciar_sessao",
        disabled=indisponivel,
        type="primary",
    ):
        try:
            disparada = launch.iniciar_sessao(
                id_escolhida,
                int(st.session_state[CHAVE_DURACAO]),
                data_dir=data_dir,
                config_dir=config_dir,
                manter_videos=bool(st.session_state[CHAVE_MANTER_CLIPES]),
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
    """Marca, estado do sistema e botão de tema (US-019)."""
    with st.container(key="cabecalho"):
        marca, indicador, botao = st.columns(
            [6, 2, 1.4], vertical_alignment="center"
        )
        marca.markdown(
            '<div class="marca"><span class="marca__quadro"></span>'
            '<span class="marca__nome">FLUXO</span>'
            '<span class="marca__sub">detecção e contagem de veículos</span></div>',
            unsafe_allow_html=True,
        )
        indicador.markdown(
            f'<span class="indicador" data-estado="{ESTADO_DO_INDICADOR[tela.indicador]}">'
            f"{tela.indicador}</span>",
            unsafe_allow_html=True,
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
    with st.container(key="principal"):
        configuracao, ao_vivo = st.columns([1, 1])
        with configuracao:
            with st.container(key="painel_configuracao"):
                _configuracao(_diretorio_de_cameras(), data_dir, progresso, tela)
        with ao_vivo:
            st.fragment(run_every=ATUALIZACAO_EM_SEGUNDOS)(_area_da_sessao)(
                data_dir, tela.indicador
            )


main()

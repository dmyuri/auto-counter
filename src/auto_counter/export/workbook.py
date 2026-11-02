"""Montagem e gravação do arquivo XLSX — T-10.

Comportamento em `.spec/features/exportacao-xlsx/spec.md`: AC-010.1 (três
abas, nomeadas e ordenadas, e nome do arquivo), AC-010.6 (mesmo conteúdo em
duas exportações) e AC-010.7 (só o banco: sem vídeo e sem rede).

O arquivo cai na raiz do diretório de dados (D-7 de `_tasks.md`), e exportar de
novo sobrescreve o de mesmo nome. Nenhuma célula carrega o instante da
exportação (D-12).
"""

import sqlite3
from pathlib import Path

from openpyxl import Workbook

from auto_counter.export.format import nome_do_arquivo
from auto_counter.export.load import carregar
from auto_counter.export.sheet_events import escrever_eventos
from auto_counter.export.sheet_minutes import escrever_por_minuto
from auto_counter.export.sheet_session import escrever_sessao

ABA_EVENTOS = "Eventos"
ABA_POR_MINUTO = "PorMinuto"
ABA_SESSAO = "Sessao"


def exportar_sessao(
    conexao: sqlite3.Connection, id_sessao: str, *, data_dir: str | Path
) -> Path:
    """Gera o XLSX da sessão em `data_dir` e devolve o caminho gravado.

    Os erros de `carregar` (sessão inexistente, em andamento ou não
    processada) sobem como estão, antes de qualquer arquivo ser criado.
    """
    dados = carregar(conexao, id_sessao)

    pasta = Workbook()
    eventos = pasta.active
    eventos.title = ABA_EVENTOS
    por_minuto = pasta.create_sheet(ABA_POR_MINUTO)
    sessao = pasta.create_sheet(ABA_SESSAO)

    escrever_eventos(eventos, dados)
    escrever_por_minuto(por_minuto, dados)
    escrever_sessao(sessao, dados)

    destino = Path(data_dir) / nome_do_arquivo(dados.sessao)
    destino.parent.mkdir(parents=True, exist_ok=True)
    pasta.save(destino)
    return destino

"""Leitura do progresso da sessão, para a interface — T-13.

Comportamento em `.spec/features/interface-sessao/spec.md`: AC-012.1 a AC-012.6
(o que mostrar de uma sessão em andamento ou terminada) e AC-013.1 (a sessão em
curso, vista pela interface, impede outra).

`ler_progresso` é a **única** função que a interface chama para saber o que
mostrar, e é só leitura: não grava, não apaga nem cria arquivo, e não cria
banco. O banco é aberto em modo somente leitura e só se o arquivo existir. Nada
aqui abre o `manifest.json` (D-9): no Windows, um leitor com o manifest aberto
faz o `os.replace` da captura falhar.

Nada fica em memória entre duas chamadas: o progresso é reencontrado só a partir
do disco (AC-012.4), por isso reabrir a interface mostra a mesma sessão.

Por `acompanhamento-ao-vivo`, a leitura também devolve as quantidades por
categoria e o tempo da sessão, já prontos para exibir: a interface só formata o
que recebe daqui (SUP-038, SUP-058). O relógio é injetável em `agora` (D-7).

Por `layout-interface`, a leitura também devolve o percentual da fase, a
participação de cada categoria, a taxa e o tempo estimado (AC-022.2 a AC-022.6),
todos calculados aqui com inteiros (D-1), para a interface só exibir (SUP-038).
O resultado também traz a chave que o identifica (D-7), o número de registros
gravados e a marca de encerramento pelo usuário (D-8), lidos do banco em modo
somente leitura (AC-023.2, AC-023.6, AC-023.7).

Por `download-clipes` (D-4), só no desfecho `CONCLUIDA` com `manter_videos`,
o resultado também traz a lista dos clipes presentes em disco agora (nome de
SUP-077, duração e tamanho), quantos dos gravados no estado já não estão lá
(AC-025.5) e o título pronto (D-5). Os nomes são calculados sobre **todos**
os clipes do estado, antes de filtrar os ausentes (D-3), para que um clipe
não mude de nome porque outro sumiu. A presença e o tamanho são lidos agora,
no disco; nada é gravado, e o `manifest.json` não é aberto.
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from auto_counter.counting.config import Categoria
from auto_counter.export.format import linha_de_aviso
from auto_counter.pipeline.clipes import formatar_megabytes, nomes_de_download
from auto_counter.pipeline.lock import (
    InfoDaTrava,
    ler_trava,
    mensagem_de_sessao_em_andamento,
)
from auto_counter.pipeline.state import ClipeMantido, EstadoDaSessao, Fase, ler_estado
from auto_counter.storage.connection import caminho_do_banco
from auto_counter.storage.events import contar_eventos
from auto_counter.storage.model import SessaoGravada
from auto_counter.storage.sessions import ler_sessao

ORCAMENTO_POR_MINUTO_EM_SEGUNDOS = 80
"""Orçamento de processamento por minuto de vídeo (SUP-070).

A conta é 59,93 s de clipe × 10 frames analisados por segundo ≈ 600 frames ×
133 ms por frame = 79,8 s, arredondado para cima. O limite de 133 ms é o de
AC-005.4 e os 10 frames por segundo são os de SUP-017, ambos de
`contagem-veiculos`: se o orçamento mudar lá, muda aqui.
"""

TAXA_SEM_DADO = "— veíc/min"
"""Taxa sem nenhum minuto concluído com dado, ou na captura (AC-022.3)."""

MENSAGEM_PROCESSO_MORREU = "o processo da sessão terminou sem concluir"
"""D-9: estado não terminal sem trava viva é um processo que morreu."""


class Situacao(Enum):
    NENHUMA = "NENHUMA"
    EM_ANDAMENTO = "EM_ANDAMENTO"
    EM_ANDAMENTO_PELO_TERMINAL = "EM_ANDAMENTO_PELO_TERMINAL"
    TERMINADA = "TERMINADA"


@dataclass(frozen=True)
class Quantidades:
    """Veículos contados por categoria; o total é a soma delas (SUP-054)."""

    carro: int
    onibus: int
    caminhao: int
    moto: int

    @property
    def total(self) -> int:
        return self.carro + self.onibus + self.caminhao + self.moto


@dataclass(frozen=True)
class Participacoes:
    """Participação de cada categoria no total, em % inteiros de 0 a 100.

    Cada categoria é arredondada sozinha (meio para cima), então a soma pode não
    dar 100 (AC-022.2).
    """

    carro: int
    onibus: int
    caminhao: int
    moto: int


def _participacao(quantidade: int, total: int) -> int:
    """q/T × 100, arredondado com meio para cima, só com inteiros (D-1)."""
    if total == 0:
        return 0
    return (200 * quantidade + total) // (2 * total)


def _participacoes(quantidades: Quantidades | None) -> Participacoes | None:
    if quantidades is None:
        return None
    total = quantidades.total
    return Participacoes(
        carro=_participacao(quantidades.carro, total),
        onibus=_participacao(quantidades.onibus, total),
        caminhao=_participacao(quantidades.caminhao, total),
        moto=_participacao(quantidades.moto, total),
    )


def formatar_taxa(veiculos: int, minutos: int) -> str:
    """V/k com uma casa decimal, vírgula e meio para cima (AC-022.3, R-1).

    Com `minutos` = 0 não há taxa, e o texto é o traço.
    """
    if minutos <= 0:
        return TAXA_SEM_DADO
    decimos = (20 * veiculos + minutos) // (2 * minutos)
    return f"{decimos // 10},{decimos % 10} veíc/min"


def _percentual(resolvidos: int, total: int) -> int:
    """⌊R/M × 100⌋ (AC-022.4); sem minutos a resolver, 0."""
    if total <= 0:
        return 0
    return (100 * resolvidos) // total


def formatar_tempo(segundos: int) -> str:
    """MM:SS, com os minutos passando de 59 sem virar hora (SUP-057)."""
    minutos, resto = divmod(int(segundos), 60)
    return f"{minutos:02d}:{resto:02d}"


def _quantidades(estado: EstadoDaSessao) -> Quantidades | None:
    if estado.quantidades is None:
        return None
    return Quantidades(
        carro=estado.quantidades[Categoria.CARRO.value],
        onibus=estado.quantidades[Categoria.ONIBUS.value],
        caminhao=estado.quantidades[Categoria.CAMINHAO.value],
        moto=estado.quantidades[Categoria.MOTO.value],
    )


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _segundos(inicio: datetime, fim: datetime) -> int:
    """Segundos inteiros de `inicio` a `fim`, truncados e nunca negativos."""
    return max(0, int((fim - inicio).total_seconds()))


@dataclass(frozen=True)
class Andamento:
    """O progresso de uma sessão que a interface sabe acompanhar."""

    nome_camera: str | None
    fase: Fase
    capturados: int
    perdidos: tuple[int, ...]
    pedidos: int
    processados: int
    a_processar: int
    pode_encerrar: bool
    quantidades: Quantidades | None
    """`None` na captura (SUP-055); zeros a partir do processamento."""
    tempo_decorrido: int
    """Segundos desde T0, sem voltar a zero na troca de fase (AC-017.2)."""
    id_camera: str
    """Para o título do painel quando `nome_camera` for `None` (AC-022.1)."""
    percentual: int
    """P = ⌊R/M × 100⌋ da fase atual (AC-022.4)."""
    participacoes: Participacoes | None
    """`None` na captura (AC-022.7); no processamento, AC-022.2."""
    taxa: str
    """Texto pronto: `"X,Y veíc/min"` ou `"— veíc/min"` (AC-022.3)."""
    tempo_estimado: int | None
    """Segundos até o fim da sessão (AC-022.5, AC-022.6); `None` no
    processamento sem o instante Tm (estado de versão anterior)."""


@dataclass(frozen=True)
class ClipeParaBaixar:
    """Um clipe mantido, presente em disco agora, pronto para exibir (D-4)."""

    minuto: int
    caminho: Path
    nome: str
    """Nome de download de SUP-077 (D-3)."""
    duracao: str
    """`formatar_tempo` do segundo medido, ou `"—"` sem medição (D-2)."""
    tamanho_em_bytes: int
    tamanho: str
    """`formatar_megabytes` do tamanho (D-5)."""


def _clipes_para_baixar(
    estado: EstadoDaSessao,
) -> tuple[tuple[ClipeParaBaixar, ...], int, str | None]:
    """Os clipes presentes, quantos ausentes e o título (D-3, D-4, D-5).

    Os nomes são calculados sobre todos os clipes do estado, em ordem de
    minuto, antes de filtrar os ausentes — um clipe não muda de nome porque
    outro sumiu (D-3).
    """
    if not estado.manter_videos or not estado.clipes:
        return (), 0, None

    nomes = nomes_de_download(
        estado.id_camera, [clipe.last_modified for clipe in estado.clipes]
    )
    presentes: list[ClipeParaBaixar] = []
    ausentes = 0
    soma_bytes = 0
    for clipe, nome in zip(estado.clipes, nomes):
        if not clipe.caminho.is_file():
            ausentes += 1
            continue
        tamanho_em_bytes = clipe.caminho.stat().st_size
        soma_bytes += tamanho_em_bytes
        presentes.append(
            ClipeParaBaixar(
                minuto=clipe.minuto,
                caminho=clipe.caminho,
                nome=nome,
                duracao=(
                    "—"
                    if clipe.duracao_segundos is None
                    else formatar_tempo(clipe.duracao_segundos)
                ),
                tamanho_em_bytes=tamanho_em_bytes,
                tamanho=formatar_megabytes(tamanho_em_bytes),
            )
        )
    titulo = (
        None
        if not presentes
        else f"Clipes · {len(presentes)} arquivos · {formatar_megabytes(soma_bytes)}"
    )
    return tuple(presentes), ausentes, titulo


@dataclass(frozen=True)
class Resultado:
    """O desfecho da última sessão."""

    fase: Fase
    status: str | None
    aviso: str | None
    planilha: Path | None
    mensagem: str | None
    chave: str = ""
    """Identidade do resultado: `<pid>:<iniciada_em>` do estado (D-7). Uma sessão
    nova tem chave nova, então o que a aba dispensou ou baixou não vaza para ela."""
    quantidades: Quantidades | None = None
    """Só na sessão concluída (SUP-060)."""
    tempo_total: int | None = None
    """`None` sem instante de término: processo morto ou estado antigo."""
    registros: int | None = None
    """Eventos gravados da sessão (AC-008.2); só em `CONCLUIDA`. `None` se o
    banco não pôde ser lido."""
    encerrada_pelo_usuario: bool = False
    """A sessão registra encerramento pelo usuário (AC-003.6); só em `CONCLUIDA`."""
    nome_camera: str | None = None
    id_camera: str = ""
    """Para o título do painel ao vivo, que continua na tela depois do fim."""
    participacoes: Participacoes | None = None
    """Só na sessão concluída: é o que o painel ao vivo mostra no fim (AC-018.1)."""
    taxa: str = TAXA_SEM_DADO
    """Só na sessão concluída; nos demais desfechos, o traço (AC-018.3, AC-018.4)."""
    manter_clipes: bool = False
    """A escolha feita ao iniciar (`estado.manter_videos`), SUP-080."""
    clipes: tuple[ClipeParaBaixar, ...] = ()
    """Só na sessão concluída com a opção e ao menos um clipe presente."""
    clipes_ausentes: int = 0
    """Clipes gravados no estado que já não estão em disco (AC-025.5)."""
    titulo_dos_clipes: str | None = None
    """`"Clipes · k arquivos · X MB"` (D-5), ou `None` sem clipe presente."""


@dataclass(frozen=True)
class Progresso:
    situacao: Situacao
    mensagem_de_recusa: str | None = None
    andamento: Andamento | None = None
    resultado: Resultado | None = None


def _tempo_estimado(estado: EstadoDaSessao, agora: datetime) -> int | None:
    """Previsão pelo orçamento de processamento, e não pela velocidade medida.

    Captura (AC-022.5): o que falta da duração pedida, contado de T0, mais o
    orçamento de cada minuto que ainda vai ser processado (o perdido não entra).
    Processamento (AC-022.6): o orçamento dos minutos que faltam, descontado o
    tempo que o minuto em análise já gastou, sem cair abaixo do orçamento dos
    minutos seguintes. Os segundos são fracionários; só o resultado é truncado.
    """
    orcamento = ORCAMENTO_POR_MINUTO_EM_SEGUNDOS
    if estado.fase is Fase.CAPTURA:
        pedidos = estado.duracao_pedida
        decorrido = (agora - estado.iniciada_em).total_seconds()
        a_capturar = max(0, pedidos * 60 - decorrido)
        a_processar = (pedidos - len(estado.minutos_perdidos)) * orcamento
        return int(a_capturar + a_processar)

    faltam = estado.minutos_a_processar - estado.minutos_processados
    if faltam <= 0:
        return 0
    if estado.minuto_em_analise_desde is None:
        return None
    gasto = (agora - estado.minuto_em_analise_desde).total_seconds()
    return int(max((faltam - 1) * orcamento, faltam * orcamento - gasto))


def _andamento(estado: EstadoDaSessao, agora: datetime) -> Andamento:
    quantidades = _quantidades(estado)
    na_captura = estado.fase is Fase.CAPTURA
    if na_captura:
        percentual = _percentual(
            len(estado.minutos_capturados) + len(estado.minutos_perdidos),
            estado.duracao_pedida,
        )
        taxa = TAXA_SEM_DADO
    else:
        percentual = _percentual(
            estado.minutos_processados, estado.minutos_a_processar
        )
        taxa = formatar_taxa(
            estado.veiculos_nos_minutos_com_dado, estado.minutos_com_dado
        )
    return Andamento(
        nome_camera=estado.nome_camera,
        fase=estado.fase,
        capturados=len(estado.minutos_capturados),
        perdidos=estado.minutos_perdidos,
        pedidos=estado.duracao_pedida,
        processados=estado.minutos_processados,
        a_processar=estado.minutos_a_processar,
        pode_encerrar=not estado.fase.terminal,
        quantidades=quantidades,
        tempo_decorrido=_segundos(estado.iniciada_em, agora),
        id_camera=estado.id_camera,
        percentual=percentual,
        participacoes=None if na_captura else _participacoes(quantidades),
        taxa=taxa,
        tempo_estimado=_tempo_estimado(estado, agora),
    )


def _sessao_do_banco(
    data_dir: Path, id_sessao: str | None
) -> tuple[SessaoGravada, int] | None:
    """A sessão e o número dos seus eventos, na mesma conexão somente leitura.

    `None` se o banco não existe, não abre ou não tem a sessão (D-8).
    """
    caminho = caminho_do_banco(data_dir)
    if id_sessao is None or not caminho.is_file():
        return None
    try:
        conexao = sqlite3.connect(f"{caminho.as_uri()}?mode=ro", uri=True)
        try:
            conexao.row_factory = sqlite3.Row
            sessao = ler_sessao(conexao, id_sessao)
            return sessao, contar_eventos(conexao, id_sessao)
        finally:
            conexao.close()
    except (sqlite3.Error, KeyError):
        return None


def _chave(estado: EstadoDaSessao) -> str:
    """D-7: `<pid>:<iniciada_em>`, estável entre leituras do mesmo resultado."""
    return f"{estado.pid}:{estado.iniciada_em.isoformat()}"


def _resultado(data_dir: Path, estado: EstadoDaSessao) -> Resultado:
    chave = _chave(estado)
    if not estado.fase.terminal:
        return Resultado(
            fase=Fase.FALHOU,
            status=estado.status,
            aviso=None,
            planilha=None,
            mensagem=MENSAGEM_PROCESSO_MORREU,
            chave=chave,
            nome_camera=estado.nome_camera,
            id_camera=estado.id_camera,
        )

    tempo_total = (
        None
        if estado.terminada_em is None
        else _segundos(estado.iniciada_em, estado.terminada_em)
    )

    if estado.fase is not Fase.CONCLUIDA:
        return Resultado(
            fase=estado.fase,
            status=estado.status,
            aviso=None,
            planilha=None,
            mensagem=estado.mensagem,
            chave=chave,
            tempo_total=tempo_total,
            nome_camera=estado.nome_camera,
            id_camera=estado.id_camera,
        )

    do_banco = _sessao_do_banco(data_dir, estado.id_sessao)
    sessao, registros = (None, None) if do_banco is None else do_banco
    status = estado.status
    aviso = None
    if sessao is not None and sessao.status is not None:
        status = sessao.status.value
        aviso = linha_de_aviso(sessao)

    quantidades = _quantidades(estado)
    planilha = Path(estado.planilha) if estado.planilha else None
    mensagem = estado.mensagem
    if planilha is not None and not planilha.is_file():
        mensagem = f"a planilha não está mais em {planilha}"
        planilha = None
    clipes, clipes_ausentes, titulo_dos_clipes = _clipes_para_baixar(estado)
    return Resultado(
        fase=Fase.CONCLUIDA,
        status=status,
        aviso=aviso,
        planilha=planilha,
        mensagem=mensagem,
        chave=chave,
        quantidades=quantidades,
        tempo_total=tempo_total,
        registros=registros,
        encerrada_pelo_usuario=(
            False if sessao is None else sessao.encerrada_pelo_usuario
        ),
        nome_camera=estado.nome_camera,
        id_camera=estado.id_camera,
        participacoes=_participacoes(quantidades),
        taxa=formatar_taxa(
            estado.veiculos_nos_minutos_com_dado, estado.minutos_com_dado
        ),
        manter_clipes=estado.manter_videos,
        clipes=clipes,
        clipes_ausentes=clipes_ausentes,
        titulo_dos_clipes=titulo_dos_clipes,
    )


def _com_trava_viva(
    info: InfoDaTrava, estado: EstadoDaSessao | None, agora: datetime
) -> Progresso | None:
    """O progresso de uma sessão em curso, ou `None` se o estado já terminou."""
    recusa = mensagem_de_sessao_em_andamento(info)
    do_run = (
        info.comando == "run" and estado is not None and estado.pid == info.pid
    )
    if not do_run:
        # D-15: iniciada pelo terminal (ou sem estado do mesmo processo). Não há
        # progresso a mostrar, só o fato de que há uma sessão.
        return Progresso(Situacao.EM_ANDAMENTO_PELO_TERMINAL, mensagem_de_recusa=recusa)
    if estado.fase.terminal:
        # O processo terminou de gravar o desfecho e ainda não soltou a trava.
        return None
    return Progresso(
        Situacao.EM_ANDAMENTO, mensagem_de_recusa=recusa, andamento=_andamento(estado, agora)
    )


def ler_progresso(data_dir: str | Path, *, agora: datetime | None = None) -> Progresso:
    """O que a interface deve mostrar agora, lido só do disco.

    `agora` é o relógio da leitura (D-7), padrão UTC atual. Só o tempo
    decorrido depende dele; o tempo total vem do instante de término gravado.
    """
    data_dir = Path(data_dir)
    agora = _agora() if agora is None else agora
    estado = ler_estado(data_dir)

    info = ler_trava(data_dir)
    if info is not None:
        progresso = _com_trava_viva(info, estado, agora)
        if progresso is not None:
            return progresso

    if estado is None:
        return Progresso(Situacao.NENHUMA)
    return Progresso(Situacao.TERMINADA, resultado=_resultado(data_dir, estado))

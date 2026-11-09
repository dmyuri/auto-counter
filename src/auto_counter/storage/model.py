"""Dataclasses de leitura do que está persistido — T-03.

Comportamento em `.spec/features/persistencia-resultados/spec.md`. Nenhuma
classe aqui grava nada: são as formas em que o código lê de volta o que
`sessions.py` (T-03), `events.py` (T-05) e `minutes.py` (T-06) gravaram.
Congeladas, no mesmo estilo das demais dataclasses do projeto — o que foi
lido do banco é fato consumado daquele instante.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from auto_counter.capture.status import StatusDaSessao
from auto_counter.counting.config import Categoria


class OrigemDaSessao(Enum):
    """De onde vieram os vídeos da sessão (AC-030.1).

    O valor é o próprio nome, que é o que a coluna `origem` guarda. As sessões
    gravadas antes de `processamento-upload` são `CAMERA` (SUP-096).
    """

    CAMERA = "CAMERA"
    UPLOAD = "UPLOAD"


@dataclass(frozen=True)
class VideoGravado:
    """Uma linha de `video_da_sessao`: um vídeo enviado (AC-030.1)."""

    posicao: int
    nome_original: str
    duracao_segundos: int
    sha256: str
    minuto_inicial: int
    minuto_final: int


class EstadoDoMinuto(Enum):
    """SUP-028: minuto sem dado é uma coluna de estado, e nenhuma outra
    coisa — nunca ausência de linha, nunca contagem nula fazendo as vezes de
    estado. É a distinção que sustenta AC-008.3 e AC-008.4.
    """

    CAPTURADO = "CAPTURADO"
    SEM_DADO = "SEM_DADO"


@dataclass(frozen=True)
class AgregadoDoMinuto:
    """Uma linha da tabela `minuto`: a contagem de um minuto ordinal da sessão.

    O minuto é o ordinal da sessão (1..duração real, D-4 de
    `_tasks.md`), não minuto de relógio. As oito contagens são nomeadas pelos
    papéis `sentido_a` / `sentido_b` (D-6), nunca pelos rótulos de uma câmera
    específica — recalibrar uma câmera pode trocar os dois rótulos.

    Em minuto `SEM_DADO` as oito contagens são `None`; em minuto `CAPTURADO`
    são inteiros, zero inclusive (AC-008.3 e AC-008.4). O schema (T-02) já
    recusa a mistura pelo CHECK — este objeto só espelha o que foi aceito.
    """

    minuto: int
    estado: EstadoDoMinuto
    motivo: str | None
    sentido_a_carro: int | None
    sentido_a_moto: int | None
    sentido_a_onibus: int | None
    sentido_a_caminhao: int | None
    sentido_b_carro: int | None
    sentido_b_moto: int | None
    sentido_b_onibus: int | None
    sentido_b_caminhao: int | None


@dataclass(frozen=True)
class SessaoGravada:
    """O que está gravado na linha de `sessao`, como `ler_sessao` devolve.

    Espelha os campos de AC-008.1. `status` nulo significa sessão ainda em
    captura — momento 1 de D-1 (`abrir_sessao`), antes do momento 2
    (`fechar_captura`) gravar o desfecho.
    """

    id_sessao: str
    id_camera: str
    nome_camera: str | None
    criada_em: datetime
    inicio: datetime | None
    fim: datetime | None
    duracao_pedida: int
    duracao_real: int | None
    encerrada_pelo_usuario: bool
    status: StatusDaSessao | None
    minutos_perdidos_quantidade: int
    minutos_perdidos: tuple[int, ...]
    versao_do_modelo: str | None
    amostragem: int | None
    limiar_de_confianca: float | None
    sentido_a: str | None
    sentido_b: str | None
    origem: OrigemDaSessao = OrigemDaSessao.CAMERA
    videos: tuple[VideoGravado, ...] = ()
    """Só na sessão de upload, em ordem de posição."""


@dataclass(frozen=True)
class SessaoNoHistorico:
    """Uma linha do histórico de US-009 — o que `listar_sessoes` (T-09)
    devolve. Definida aqui porque é a mesma leitura da tabela `sessao` desta
    tarefa, só que mais estreita e com o total de eventos ao lado (AC-009.2).
    """

    id_sessao: str
    id_camera: str
    criada_em: datetime
    inicio: datetime | None
    fim: datetime | None
    status: StatusDaSessao | None
    total_de_eventos: int
    origem: OrigemDaSessao = OrigemDaSessao.CAMERA


@dataclass(frozen=True)
class EventoGravado:
    """Uma linha da tabela `evento`, como `ler_eventos` devolve.

    Não reaproveita `counting.events.Evento`: ele exige `indice_do_frame` e
    `posicao_na_linha`, que o schema não guarda, e inventar esses valores
    seria mentir sobre o evento lido.
    """

    id_de_rastreio: str
    sentido: str
    timestamp: datetime
    categoria: Categoria
    confianca: float
    minuto: int
    video: int | None = None
    deslocamento: int | None = None
    """Só no evento de upload (SUP-100): vídeo de origem e segundos desde o
    início dele."""

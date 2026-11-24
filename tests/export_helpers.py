"""Helper dos testes de `exportacao-xlsx`: grava uma sessão completa no banco.

Usa as funções reais de `storage` (as mesmas de `persistir_sessao`), sem passar
por manifest, `eventos.json` ou vídeo. Não grava nenhum arquivo além do banco.
"""

from datetime import datetime, timedelta, timezone

from auto_counter.capture.status import StatusDaSessao
from auto_counter.counting.config import Categoria
from auto_counter.counting.events import Evento, MinutoNaoProcessado
from auto_counter.storage.events import gravar_eventos
from auto_counter.storage.model import OrigemDaSessao, VideoGravado
from auto_counter.storage.minutes import agregar, gravar_agregados
from auto_counter.storage.sessions import (
    abrir_sessao,
    completar_processamento,
    fechar_captura,
    gravar_videos,
)

ID_SESSAO = "000013-20260907T110000Z"
ID_CAMERA = "000013"
NOME_CAMERA = "Praça Exemplo"
SENTIDO_A = "Icaraí"
SENTIDO_B = "Centro"
INICIO = datetime(2026, 9, 7, 11, 0, 5, tzinfo=timezone.utc)
VERSAO_DO_MODELO = "yolo11n.onnx@abc123def456"


def evento(
    *,
    minuto: int,
    id_de_rastreio: str,
    sentido: str = SENTIDO_A,
    categoria: Categoria = Categoria.CARRO,
    confianca: float = 0.9,
    segundos: int = 10,
    video: int | None = None,
    deslocamento: int | None = None,
) -> Evento:
    return Evento(
        timestamp=INICIO + timedelta(minutes=minuto - 1, seconds=segundos),
        categoria=categoria,
        sentido=sentido,
        id_de_rastreio=id_de_rastreio,
        confianca=confianca,
        minuto=minuto,
        indice_do_frame=5,
        posicao_na_linha=0.5,
        video=video,
        deslocamento_segundos=deslocamento,
    )


def gravar_sessao(
    conexao,
    *,
    id_sessao: str = ID_SESSAO,
    id_camera: str = ID_CAMERA,
    nome_camera: str | None = NOME_CAMERA,
    sentido_a: str = SENTIDO_A,
    sentido_b: str = SENTIDO_B,
    duracao_pedida: int = 2,
    duracao_real: int | None = None,
    encerrada_pelo_usuario: bool = False,
    encerrada_por_servidor_indisponivel: bool = False,
    status: StatusDaSessao | None = StatusDaSessao.COMPLETA,
    minutos_perdidos: tuple[int, ...] = (),
    eventos: tuple[Evento, ...] = (),
    minutos_processados: tuple[int, ...] | None = None,
    minutos_nao_processados: tuple[MinutoNaoProcessado, ...] = (),
    inicio: datetime = INICIO,
    processada: bool = True,
    origem: OrigemDaSessao = OrigemDaSessao.CAMERA,
    videos: tuple[VideoGravado, ...] = (),
    amostragem: int = 3,
) -> None:
    """Grava a sessão pelos três momentos de D-1.

    `status=None` deixa a sessão em andamento (só `abrir_sessao`).
    `processada=False` para no fim da captura, sem versão do modelo nem
    agregados.
    """
    duracao_real = duracao_pedida if duracao_real is None else duracao_real

    abrir_sessao(
        conexao,
        id_sessao=id_sessao,
        id_camera=id_camera,
        criada_em=inicio,
        duracao_pedida=duracao_pedida,
        sentido_a=sentido_a,
        sentido_b=sentido_b,
        nome_camera=nome_camera,
        origem=origem,
    )
    if status is None:
        return

    fechar_captura(
        conexao,
        id_sessao,
        inicio=inicio,
        fim=inicio + timedelta(minutes=duracao_real),
        duracao_real=duracao_real,
        encerrada_pelo_usuario=encerrada_pelo_usuario,
        status=status,
        minutos_perdidos=minutos_perdidos,
        encerrada_por_servidor_indisponivel=encerrada_por_servidor_indisponivel,
    )
    if not processada:
        return

    completar_processamento(
        conexao,
        id_sessao,
        versao_do_modelo=VERSAO_DO_MODELO,
        amostragem=amostragem,
        limiar_de_confianca=0.35,
    )

    if minutos_processados is None:
        minutos_processados = tuple(
            m for m in range(1, duracao_real + 1) if m not in minutos_perdidos
        )
    gravar_eventos(conexao, id_sessao, eventos)
    if videos:
        gravar_videos(conexao, id_sessao, videos)
    gravar_agregados(
        conexao,
        id_sessao,
        agregar(
            eventos,
            duracao_real=duracao_real,
            minutos_processados=minutos_processados,
            minutos_nao_processados=minutos_nao_processados,
            sentido_a=sentido_a,
            sentido_b=sentido_b,
        ),
    )
    conexao.commit()

"""Download do clipe com até 3 tentativas dentro da janela — T-04.

Critério coberto, de `.spec/features/captura-clipes/spec.md`:

- AC-004.1 — quando a requisição de um clipe falha por erro de rede, timeout ou
  resposta HTTP de erro, o sistema repete até 3 tentativas com espera crescente
  **dentro da janela daquele minuto**, e só depois marca o minuto como não
  capturado.

SUP-008 é a restrição que amarra o retry: a janela de espera de um clipe novo é
de 90 s e as 3 tentativas precisam caber nela. Os valores concretos do backoff
não estão na spec — estão fixados em T-04 do `_tasks.md` (esperas de 3 s e 8 s,
timeout de 20 s por tentativa, pior caso 71 s) — e é contra esses valores que os
testes daqui afirmam.

`dormir` e `agora` entram injetados (D-7): esta suíte não gasta 71 s de relógio.
Nenhum teste toca o servidor da NitTrans: todo acesso HTTP passa por transporte
dublê, e o relógio falso é avançado pelo próprio dublê para simular o tempo que
uma tentativa gasta até estourar o timeout.

Quem traduz `DownloadFalhouError` em "minuto não capturado" é o laço de captura
(T-07): esta função não conhece minuto.
"""

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from auto_counter.capture.download import (
    ESPERAS_ENTRE_TENTATIVAS,
    TEMPO_LIMITE_POR_TENTATIVA,
    TENTATIVAS_MAXIMAS,
    DownloadFalhouError,
    baixar,
)

URL_DO_CLIPE = "https://exemplo.invalido/videos/000013/last_video.mp4"

INICIO = datetime(2026, 9, 7, 12, 0, 0, tzinfo=timezone.utc)
"""Instante em que a janela do minuto começa, no relógio falso."""

JANELA_DO_MINUTO = 90.0
"""Segundos de janela por minuto, conforme SUP-008. Número normativo."""

CONTEUDO_DO_CLIPE = b"\x00\x00\x00\x18ftypmp42 bytes de um clipe valido"


class RelogioFalso:
    """Relógio injetável que só avança quando alguém o manda avançar (D-7)."""

    def __init__(self, inicio: datetime = INICIO):
        self.instante = inicio

    def agora(self) -> datetime:
        return self.instante

    def avanca(self, segundos: float) -> None:
        self.instante += timedelta(seconds=segundos)

    def decorrido(self) -> float:
        return (self.instante - INICIO).total_seconds()


class DormirFalso:
    """Registra as esperas pedidas e as reflete no relógio falso."""

    def __init__(self, relogio: RelogioFalso):
        self.relogio = relogio
        self.esperas: list[float] = []

    def __call__(self, segundos: float) -> None:
        self.esperas.append(segundos)
        self.relogio.avanca(segundos)


def cliente_que_responde(relogio: RelogioFalso, *respostas) -> httpx.Client:
    """Cliente HTTP dublê. Cada item é uma `httpx.Response` ou uma exceção.

    Uma tentativa que falha é cobrada do relógio falso como se tivesse gasto o
    timeout inteiro (`TEMPO_LIMITE_POR_TENTATIVA`): é o pior caso que SUP-008
    obriga a caber na janela de 90 s. A última resposta se repete quando há
    mais requisições do que respostas.
    """
    pedidos: list[httpx.Request] = []
    fila = list(respostas)

    def responder(pedido: httpx.Request) -> httpx.Response:
        pedidos.append(pedido)
        resposta = fila.pop(0) if len(fila) > 1 else fila[0]
        if isinstance(resposta, Exception):
            relogio.avanca(TEMPO_LIMITE_POR_TENTATIVA)
            raise resposta
        if resposta.status_code >= 400:
            relogio.avanca(TEMPO_LIMITE_POR_TENTATIVA)
        return resposta

    cliente = httpx.Client(transport=httpx.MockTransport(responder))
    cliente.pedidos = pedidos
    return cliente


def prazo_da_janela(segundos: float = JANELA_DO_MINUTO) -> datetime:
    """Fim da janela daquele minuto, contado do início no relógio falso."""
    return INICIO + timedelta(seconds=segundos)


def test_AC_004_1_falha_de_rede_e_repetida_com_espera_crescente_ate_tres_tentativas(
    tmp_path,
):
    relogio = RelogioFalso()
    dormir = DormirFalso(relogio)
    cliente = cliente_que_responde(relogio, httpx.ConnectError("sem rota"))
    destino = tmp_path / "minuto-01.mp4"

    with pytest.raises(DownloadFalhouError) as erro:
        baixar(
            cliente,
            URL_DO_CLIPE,
            destino,
            prazo=prazo_da_janela(),
            dormir=dormir,
            agora=relogio.agora,
        )

    assert len(cliente.pedidos) == TENTATIVAS_MAXIMAS == 3
    assert [pedido.method for pedido in cliente.pedidos] == ["GET", "GET", "GET"]
    # Espera crescente entre as tentativas, nos valores fixados em T-04.
    assert dormir.esperas == [3.0, 8.0] == list(ESPERAS_ENTRE_TENTATIVAS)
    # A mensagem diz o que falhou e quantas tentativas houve.
    assert "3" in str(erro.value)
    # E nenhum arquivo meia-boca fica no diretório da sessão.
    assert not destino.exists()


def test_AC_004_1_resposta_http_de_erro_tambem_conta_como_tentativa(tmp_path):
    relogio = RelogioFalso()
    dormir = DormirFalso(relogio)
    cliente = cliente_que_responde(relogio, httpx.Response(503))

    with pytest.raises(DownloadFalhouError) as erro:
        baixar(
            cliente,
            URL_DO_CLIPE,
            tmp_path / "minuto-01.mp4",
            prazo=prazo_da_janela(),
            dormir=dormir,
            agora=relogio.agora,
        )

    assert len(cliente.pedidos) == 3
    assert dormir.esperas == [3.0, 8.0]
    assert "503" in str(erro.value)


def test_AC_004_1_sucesso_na_segunda_tentativa_nao_dispara_a_terceira(tmp_path):
    relogio = RelogioFalso()
    dormir = DormirFalso(relogio)
    cliente = cliente_que_responde(
        relogio,
        httpx.ReadTimeout("estourou o tempo de leitura"),
        httpx.Response(200, content=CONTEUDO_DO_CLIPE),
    )
    destino = tmp_path / "minuto-01.mp4"

    caminho = baixar(
        cliente,
        URL_DO_CLIPE,
        destino,
        prazo=prazo_da_janela(),
        dormir=dormir,
        agora=relogio.agora,
    )

    assert len(cliente.pedidos) == 2
    assert dormir.esperas == [3.0]
    assert caminho == destino
    assert destino.read_bytes() == CONTEUDO_DO_CLIPE


def test_AC_004_1_as_tres_tentativas_cabem_na_janela_de_noventa_segundos(tmp_path):
    # SUP-008: as 3 tentativas de AC-004.1 precisam caber na janela de 90 s.
    pior_caso = TENTATIVAS_MAXIMAS * TEMPO_LIMITE_POR_TENTATIVA + sum(
        ESPERAS_ENTRE_TENTATIVAS
    )
    assert pior_caso == 71.0
    assert pior_caso <= JANELA_DO_MINUTO

    relogio = RelogioFalso()
    dormir = DormirFalso(relogio)
    cliente = cliente_que_responde(relogio, httpx.ConnectError("sem rota"))

    with pytest.raises(DownloadFalhouError):
        baixar(
            cliente,
            URL_DO_CLIPE,
            tmp_path / "minuto-01.mp4",
            prazo=prazo_da_janela(),
            dormir=dormir,
            agora=relogio.agora,
        )

    # E o pior caso de verdade, medido no relógio falso, também cabe na janela.
    assert relogio.decorrido() == pior_caso
    assert relogio.decorrido() <= JANELA_DO_MINUTO


def test_AC_004_1_prazo_da_janela_interrompe_o_retry_antes_da_terceira_tentativa(
    tmp_path,
):
    # Janela curta: sobra tempo para a segunda tentativa (3 + 20 a partir do
    # segundo 20), mas não para a terceira (8 + 20 a partir do segundo 43). O
    # prazo tem precedência sobre a contagem de tentativas.
    relogio = RelogioFalso()
    dormir = DormirFalso(relogio)
    cliente = cliente_que_responde(relogio, httpx.ConnectError("sem rota"))

    with pytest.raises(DownloadFalhouError) as erro:
        baixar(
            cliente,
            URL_DO_CLIPE,
            tmp_path / "minuto-01.mp4",
            prazo=prazo_da_janela(45.0),
            dormir=dormir,
            agora=relogio.agora,
        )

    assert len(cliente.pedidos) == 2
    assert dormir.esperas == [3.0]
    assert "prazo" in str(erro.value).lower()


def test_AC_004_1_prazo_ja_vencido_nao_dispara_nenhuma_requisicao(tmp_path):
    relogio = RelogioFalso()
    dormir = DormirFalso(relogio)
    cliente = cliente_que_responde(relogio, httpx.Response(200, content=b"x"))

    with pytest.raises(DownloadFalhouError):
        baixar(
            cliente,
            URL_DO_CLIPE,
            tmp_path / "minuto-01.mp4",
            prazo=INICIO - timedelta(seconds=1),
            dormir=dormir,
            agora=relogio.agora,
        )

    assert cliente.pedidos == []
    assert dormir.esperas == []


def test_AC_004_1_arquivo_parcial_de_tentativa_que_falhou_e_apagado_antes_da_proxima(
    tmp_path,
):
    # O destino nunca pode ficar com bytes de duas tentativas.
    relogio = RelogioFalso()
    dormir = DormirFalso(relogio)
    destino = tmp_path / "minuto-01.mp4"
    destino.write_bytes(b"sobra de uma tentativa anterior")
    cliente = cliente_que_responde(
        relogio,
        httpx.Response(500),
        httpx.Response(200, content=CONTEUDO_DO_CLIPE),
    )

    baixar(
        cliente,
        URL_DO_CLIPE,
        destino,
        prazo=prazo_da_janela(),
        dormir=dormir,
        agora=relogio.agora,
    )

    assert destino.read_bytes() == CONTEUDO_DO_CLIPE

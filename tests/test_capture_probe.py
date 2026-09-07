"""Checagem de clipe novo por HEAD (ETag e Last-Modified) — T-03.

Critério coberto, de `.spec/features/captura-clipes/spec.md`:

- AC-003.2 — quando o servidor responde com o mesmo ETag da checagem anterior,
  o sistema **não baixa o conteúdo de novo** e aguarda a próxima checagem.

Implementa também SUP-008 (a checagem é uma requisição HEAD) e SUP-009 (a
identidade do clipe é o ETag, sua referência de tempo é o Last-Modified do
servidor, e o relógio local é gravado à parte apenas como diagnóstico).

Nenhum teste aqui toca o servidor da NitTrans: todo acesso HTTP passa por um
transporte dublê (D-7), e o teste afirma explicitamente que nenhuma requisição
diferente de HEAD sai do módulo — é assim que "não baixa o conteúdo" (AC-003.2)
vira observável.

D-4 define que ETag ou Last-Modified ausente numa checagem não produz clipe
identificável: `checar` devolve `None` e o chamador aguarda a próxima janela,
sem exceção crua escapando (`CLAUDE.md`).
"""

from datetime import datetime, timezone

import httpx
import pytest

from auto_counter.capture.probe import Checagem, checar, e_novo

URL_DO_CLIPE = "https://exemplo.invalido/videos/000013/last_video.mp4"

RELOGIO_LOCAL = datetime(2026, 9, 7, 12, 0, 30, tzinfo=timezone.utc)
"""Relógio local injetado (D-7). Só diagnóstico: não define tempo de sessão."""


def relogio_fixo(instante: datetime = RELOGIO_LOCAL):
    """Relógio injetável: a suíte não depende do relógio real da máquina."""
    return lambda: instante


def cliente_que_responde(*respostas) -> httpx.Client:
    """Cliente HTTP dublê. Cada item é uma `httpx.Response` ou uma exceção.

    A última resposta se repete se houver mais requisições do que respostas,
    para que o teste não precise contar checagens que não está afirmando.
    """
    pedidos = []
    fila = list(respostas)

    def responder(pedido: httpx.Request) -> httpx.Response:
        pedidos.append(pedido)
        resposta = fila.pop(0) if len(fila) > 1 else fila[0]
        if isinstance(resposta, Exception):
            raise resposta
        return resposta

    cliente = httpx.Client(transport=httpx.MockTransport(responder))
    cliente.pedidos = pedidos
    return cliente


def resposta_com(etag: str | None, last_modified: str | None) -> httpx.Response:
    """Resposta de HEAD com os headers que o servidor da NitTrans envia."""
    headers = {}
    if etag is not None:
        headers["ETag"] = etag
    if last_modified is not None:
        headers["Last-Modified"] = last_modified
    return httpx.Response(200, headers=headers)


def test_AC_003_2_etag_igual_ao_da_checagem_anterior_nao_baixa_o_conteudo():
    cliente = cliente_que_responde(
        resposta_com('"abc123"', "Sun, 07 Sep 2026 12:00:00 GMT"),
        resposta_com('"abc123"', "Sun, 07 Sep 2026 12:00:00 GMT"),
    )

    anterior = checar(cliente, URL_DO_CLIPE, agora=relogio_fixo())
    seguinte = checar(cliente, URL_DO_CLIPE, agora=relogio_fixo())

    assert anterior is not None and seguinte is not None
    # Mesmo ETag da checagem anterior: não é clipe novo (AC-003.2).
    assert e_novo(seguinte, {anterior.etag}) is False
    # E nada além de HEAD saiu daqui: o conteúdo não foi baixado de novo.
    assert [pedido.method for pedido in cliente.pedidos] == ["HEAD", "HEAD"]


def test_AC_003_2_etag_diferente_e_reconhecido_como_clipe_novo():
    cliente = cliente_que_responde(
        resposta_com('"abc123"', "Sun, 07 Sep 2026 12:00:00 GMT"),
        resposta_com('"def456"', "Sun, 07 Sep 2026 12:01:00 GMT"),
    )

    anterior = checar(cliente, URL_DO_CLIPE, agora=relogio_fixo())
    seguinte = checar(cliente, URL_DO_CLIPE, agora=relogio_fixo())

    assert e_novo(seguinte, {anterior.etag}) is True
    # A referência de tempo é o Last-Modified do servidor, em UTC (SUP-009).
    assert seguinte.last_modified == datetime(
        2026, 9, 7, 12, 1, 0, tzinfo=timezone.utc
    )
    # O relógio local viaja à parte, só como diagnóstico (SUP-009).
    assert seguinte.relogio_local == RELOGIO_LOCAL
    assert seguinte.last_modified != seguinte.relogio_local


def test_AC_003_2_etag_ja_aceito_na_sessao_nao_vira_um_segundo_minuto():
    # AC-003.1 exige N clipes distintos: o guarda é o conjunto de ETags já
    # aceitos, não só o da checagem imediatamente anterior.
    cliente = cliente_que_responde(
        resposta_com('"minuto-1"', "Sun, 07 Sep 2026 12:00:00 GMT")
    )

    checagem = checar(cliente, URL_DO_CLIPE, agora=relogio_fixo())

    assert e_novo(checagem, {"minuto-1", "minuto-2", "minuto-3"}) is False
    assert e_novo(checagem, {"minuto-2", "minuto-3"}) is True


@pytest.mark.parametrize(
    "etag_novo, etags_aceitos",
    [
        # Aspas e o prefixo `W/` de ETag fraco não podem fazer o mesmo clipe
        # parecer dois.
        ('W/"abc123"', {'"abc123"'}),
        ('"abc123"', {'W/"abc123"'}),
        ("abc123", {'"abc123"'}),
        ('"abc123"', {"abc123"}),
    ],
)
def test_AC_003_2_etag_igual_a_menos_de_aspas_ou_prefixo_fraco_nao_e_clipe_novo(
    etag_novo, etags_aceitos
):
    cliente = cliente_que_responde(
        resposta_com(etag_novo, "Sun, 07 Sep 2026 12:00:00 GMT")
    )

    checagem = checar(cliente, URL_DO_CLIPE, agora=relogio_fixo())

    assert e_novo(checagem, etags_aceitos) is False


@pytest.mark.parametrize(
    "resposta",
    [
        # Sem ETag o clipe não tem identidade; sem Last-Modified não tem a
        # referência de tempo que AC-003.4 exige. Nos dois casos, D-4.
        resposta_com(None, "Sun, 07 Sep 2026 12:00:00 GMT"),
        resposta_com('"abc123"', None),
        resposta_com(None, None),
        # Last-Modified que não parseia cai no mesmo caminho.
        resposta_com('"abc123"', "ontem de tarde"),
        # E falha de rede ou HTTP de erro também: nenhuma exceção crua sai daqui.
        httpx.Response(404),
        httpx.Response(500),
        httpx.ConnectError("sem rota para o host"),
        httpx.ReadTimeout("estourou o tempo de leitura"),
    ],
)
def test_AC_003_2_checagem_sem_os_headers_necessarios_nao_produz_clipe_novo(resposta):
    cliente = cliente_que_responde(resposta)

    checagem = checar(cliente, URL_DO_CLIPE, agora=relogio_fixo())

    assert checagem is None
    # A checagem que não produz clipe identificável não baixa nada: só HEAD.
    assert [pedido.method for pedido in cliente.pedidos] in ([], ["HEAD"])
    # E `e_novo` sobre ela é falso, sem estourar (D-4).
    assert e_novo(checagem, set()) is False


def test_AC_003_2_checagem_e_um_head_na_url_do_clipe_e_nunca_um_get():
    cliente = cliente_que_responde(
        resposta_com('"abc123"', "Sun, 07 Sep 2026 12:00:00 GMT")
    )

    checar(cliente, URL_DO_CLIPE, agora=relogio_fixo())

    assert len(cliente.pedidos) == 1
    assert cliente.pedidos[0].method == "HEAD"
    assert str(cliente.pedidos[0].url) == URL_DO_CLIPE


def test_AC_003_2_checagem_carrega_o_etag_normalizado_para_o_manifest():
    # T-06 grava o ETag; guardar a forma normalizada é o que impede o mesmo
    # clipe de aparecer com duas identidades no manifest da sessão.
    cliente = cliente_que_responde(
        resposta_com('W/"abc123"', "Sun, 07 Sep 2026 12:00:00 GMT")
    )

    checagem = checar(cliente, URL_DO_CLIPE, agora=relogio_fixo())

    assert isinstance(checagem, Checagem)
    assert checagem.etag == "abc123"

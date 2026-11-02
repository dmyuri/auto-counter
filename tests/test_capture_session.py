"""Laço de captura: a costura de T-01 a T-06 — T-07.

Critérios cobertos, de `.spec/features/captura-clipes/spec.md`:

- AC-003.1 — há exatamente N clipes **distintos** gravados em disco, cada um
  associado ao seu número de minuto, ao seu ETag e ao seu Last-Modified.
- AC-003.2 — com o mesmo ETag da checagem anterior o conteúdo **não** é baixado
  de novo e o sistema aguarda a próxima checagem.
- AC-004.2 — ETag parado por toda a janela marca o minuto como não capturado e
  a captura segue para o minuto seguinte, **sem interromper a sessão**.
- AC-004.3 — clipe ilegível não derruba a sessão: o arquivo é descartado e a
  janela daquele minuto continua sendo checada.

Os números normativos de SUP-008 governam a suíte: checagem HEAD a cada 10 s e
janela de 90 s por minuto. A janela do minuto k começa quando o minuto k-1 é
resolvido (`_tasks.md`, §Restrições estruturais), e o minuto 1 aceita o clipe
que já está no servidor (D-2).

O relógio, a espera e o cliente HTTP são injetados (D-7): esta suíte não espera
relógio real e não toca o servidor da NitTrans. O servidor dublê é dirigido pelo
tempo falso — ele publica um ETag novo em instantes marcados —, que é como a
URL real se comporta e é o que permite escrever "o ETag ficou parado durante a
janela" sem contar requisições na mão.

Os vídeos da suíte são gerados de verdade por `cv2.VideoWriter` em diretório
temporário, porque o laço passa o clipe baixado por `capture.readable.e_legivel`
e um dublê ali provaria outra coisa. Cada ETag publica um vídeo **de conteúdo
próprio**: desde AC-004.7 o mesmo arquivo republicado com ETag novo é recusado,
então reusar os mesmos bytes faria o servidor dublê republicar sem querer. Nenhuma fixture de vídeo entra no
repositório. Se o codec `mp4v` não existir na máquina, o teste **falha** —
`audit.py` trata teste pulado igual a teste que falhou.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import cv2
import httpx
import numpy as np
import pytest

from auto_counter.cameras.model import Camera
from auto_counter.cameras.url import VARIAVEL_BASE_URL
from auto_counter.capture.manifest import NOME_DO_MANIFEST, ler
from auto_counter.capture.session import (
    INTERVALO_ENTRE_CHECAGENS,
    JANELA_DO_MINUTO,
    capturar,
)
from auto_counter.capture.status import StatusDaSessao

BASE_URL = "https://exemplo.invalido/videos"
ID_CAMERA = "000013"

INICIO = datetime(2026, 9, 7, 12, 0, 0, tzinfo=timezone.utc)
"""Relógio local no instante do comando. Só nomeia o diretório (D-5)."""

LAST_MODIFIED_BASE = datetime(2026, 9, 7, 11, 30, 0, tzinfo=timezone.utc)
"""Referência de tempo do servidor, deslocada do relógio local de propósito.

AC-003.4 e SUP-009: o período da sessão sai do Last-Modified, nunca do relógio
local. Com os dois coincidindo, o teste não conseguiria distinguir um do outro.
"""

LARGURA = 320
ALTURA = 240
QUADROS = 30

LIXO = b"isto nao e um container de video" * 40


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


def video_valido(caminho: Path, semente: int = 0) -> bytes:
    """Bytes de um MP4 curto e legível, escrito com `cv2.VideoWriter`.

    `semente` muda o conteúdo dos quadros, e com ele os bytes do arquivo: é o
    que permite publicar clipes distintos, como AC-003.1 exige e AC-004.7
    passou a conferir pelo conteúdo, e não pelo ETag.
    """
    escritor = cv2.VideoWriter(
        str(caminho), cv2.VideoWriter_fourcc(*"mp4v"), 30.0, (LARGURA, ALTURA)
    )
    assert escritor.isOpened(), (
        "o codec mp4v não está disponível nesta máquina e a fixture de vídeo "
        "válido não pôde ser gerada"
    )
    try:
        for indice in range(QUADROS):
            valor = (indice * 8 + semente * 37) % 256
            escritor.write(np.full((ALTURA, LARGURA, 3), valor, dtype=np.uint8))
    finally:
        escritor.release()
    return caminho.read_bytes()


class ServidorFalso:
    """A URL da NitTrans dublada: publica um ETag novo em instantes marcados.

    `publicacoes` é uma lista de `(segundo, etag)` no relógio falso: o clipe
    publicado a qualquer momento é o da última publicação já ocorrida. Essa
    forma — e não uma fila de respostas por requisição — é o que permite dizer
    "o ETag ficou parado durante toda a janela" sem depender de quantas
    checagens o laço faz.

    HEAD devolve `ETag` e `Last-Modified`; GET devolve o conteúdo daquele ETag.
    """

    def __init__(
        self,
        relogio: RelogioFalso,
        publicacoes: list[tuple[float, str]],
        conteudo_por_etag: dict[str, bytes],
    ):
        self.relogio = relogio
        self.publicacoes = sorted(publicacoes)
        self.conteudo_por_etag = conteudo_por_etag
        self.pedidos: list[tuple[str, float]] = []

    def _publicado(self) -> tuple[float, str]:
        decorrido = self.relogio.decorrido()
        atual = self.publicacoes[0]
        for publicacao in self.publicacoes:
            if publicacao[0] <= decorrido:
                atual = publicacao
        return atual

    def _responder(self, pedido: httpx.Request) -> httpx.Response:
        self.pedidos.append((pedido.method, self.relogio.decorrido()))
        segundo, etag = self._publicado()
        instante = LAST_MODIFIED_BASE + timedelta(seconds=segundo)
        cabecalhos = {
            "ETag": '"' + etag + '"',
            "Last-Modified": instante.strftime("%a, %d %b %Y %H:%M:%S GMT"),
        }
        if pedido.method == "HEAD":
            return httpx.Response(200, headers=cabecalhos)
        return httpx.Response(
            200, headers=cabecalhos, content=self.conteudo_por_etag[etag]
        )

    def cliente(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self._responder))

    def metodos(self) -> list[str]:
        return [metodo for metodo, _ in self.pedidos]

    def instantes(self, metodo: str) -> list[float]:
        return [segundo for feito, segundo in self.pedidos if feito == metodo]


@pytest.fixture
def camera() -> Camera:
    return Camera(
        id=ID_CAMERA,
        nome="Av. Exemplo",
        sentido_a="centro",
        sentido_b="bairro",
        linha={"p1": {"x": 0, "y": 360}, "p2": {"x": 1279, "y": 360}},
    )


@pytest.fixture(autouse=True)
def base_url_no_ambiente(monkeypatch):
    """A URL vem de `cameras.url.url_do_clipe`, que lê o ambiente (AC-001.5)."""
    monkeypatch.setenv(VARIAVEL_BASE_URL, BASE_URL)


@pytest.fixture
def clipe_legivel(tmp_path) -> bytes:
    return video_valido(tmp_path / "fixture-video.mp4")


@pytest.fixture
def clipes_legiveis(tmp_path):
    """Fábrica de clipes legíveis **distintos**, um por ETag.

    Devolve o dicionário de conteúdo do `ServidorFalso` já com bytes próprios
    para cada ETag. Publicar o mesmo vídeo em ETags diferentes é, desde
    AC-004.7, a republicação que o laço recusa — o que provaria outra coisa em
    todo teste que só quer "um clipe novo a cada minuto".
    """

    def gerar(*etags: str) -> dict[str, bytes]:
        return {
            etag: video_valido(
                tmp_path / f"fixture-video-{indice:02d}.mp4", semente=indice + 1
            )
            for indice, etag in enumerate(etags)
        }

    return gerar


def executa(camera, tmp_path, servidor, relogio, minutos: int):
    """Roda o laço com relógio, espera e transporte HTTP falsos (D-7)."""
    return capturar(
        camera,
        minutos,
        data_dir=tmp_path / "data",
        cliente=servidor.cliente(),
        agora=relogio.agora,
        dormir=DormirFalso(relogio),
    )


def test_AC_003_1_captura_sem_falhas_grava_exatamente_n_clipes_distintos_em_disco(
    camera, tmp_path, clipes_legiveis
):
    relogio = RelogioFalso()
    servidor = ServidorFalso(
        relogio,
        [(0.0, "clipe-a"), (60.0, "clipe-b"), (120.0, "clipe-c")],
        clipes_legiveis("clipe-a", "clipe-b", "clipe-c"),
    )

    resultado = executa(camera, tmp_path, servidor, relogio, minutos=3)

    # Exatamente N clipes em disco, um por minuto, na ordem da sessão.
    videos = sorted(p.name for p in resultado.dir_sessao.glob("*.mp4"))
    assert videos == ["minuto-01.mp4", "minuto-02.mp4", "minuto-03.mp4"]
    assert resultado.status is StatusDaSessao.COMPLETA
    assert resultado.minutos_perdidos == ()

    # E o manifest em disco associa cada clipe ao minuto, ao ETag e ao
    # Last-Modified (AC-003.1) — a afirmação é sobre o arquivo, não sobre o
    # objeto em memória.
    gravado = ler(resultado.dir_sessao)
    assert [item.minuto for item in gravado.minutos_capturados] == [1, 2, 3]
    etags = [item.etag for item in gravado.minutos_capturados]
    assert etags == ["clipe-a", "clipe-b", "clipe-c"]
    assert len(set(etags)) == 3
    assert [item.arquivo for item in gravado.minutos_capturados] == videos
    assert [item.last_modified for item in gravado.minutos_capturados] == [
        LAST_MODIFIED_BASE,
        LAST_MODIFIED_BASE + timedelta(seconds=60),
        LAST_MODIFIED_BASE + timedelta(seconds=120),
    ]
    # AC-003.4: o período vem do Last-Modified, não do relógio do comando.
    assert gravado.inicio == LAST_MODIFIED_BASE
    assert gravado.fim == LAST_MODIFIED_BASE + timedelta(seconds=120)


def test_AC_003_2_etag_repetido_na_janela_nao_baixa_o_conteudo_de_novo(
    camera, tmp_path, clipes_legiveis
):
    relogio = RelogioFalso()
    servidor = ServidorFalso(
        relogio,
        [(0.0, "clipe-a"), (60.0, "clipe-b")],
        clipes_legiveis("clipe-a", "clipe-b"),
    )

    resultado = executa(camera, tmp_path, servidor, relogio, minutos=2)

    assert resultado.status is StatusDaSessao.COMPLETA
    metodos = servidor.metodos()
    # Dois clipes aceitos, dois GET: as checagens com o mesmo ETag da anterior
    # não baixaram conteúdo nenhum (AC-003.2).
    assert metodos.count("GET") == 2
    assert servidor.instantes("GET") == [0.0, 60.0]
    # Minuto 1 aceita o clipe já publicado (D-2) na checagem de t=0. A janela do
    # minuto 2 começa aí e vai checando a cada 10 s (SUP-008) — t=0, 10, ... 60 —
    # até o ETag mudar em t=60.
    assert metodos.count("HEAD") == 8
    assert servidor.instantes("HEAD") == [
        0.0,
        0.0,
        10.0,
        20.0,
        30.0,
        40.0,
        50.0,
        60.0,
    ]


def test_AC_004_2_etag_parado_por_toda_a_janela_marca_o_minuto_como_nao_capturado(
    camera, tmp_path, clipe_legivel
):
    relogio = RelogioFalso()
    # O servidor parou de atualizar o arquivo depois do primeiro clipe.
    servidor = ServidorFalso(relogio, [(0.0, "clipe-a")], {"clipe-a": clipe_legivel})

    resultado = executa(camera, tmp_path, servidor, relogio, minutos=2)

    # O minuto 2 esgotou a janela de 90 s sem clipe novo.
    assert [item.minuto for item in resultado.minutos_perdidos] == [2]
    assert resultado.minutos_perdidos[0].motivo
    assert [item.minuto for item in resultado.minutos_capturados] == [1]
    # Um único GET: o ETag repetido nunca virou download (AC-003.2).
    assert servidor.metodos().count("GET") == 1
    # A janela do minuto 2 durou os 90 s de SUP-008, e nem um segundo a mais.
    assert relogio.decorrido() == JANELA_DO_MINUTO
    # base = N pedido (SUP-013): 1 perdido em 2 é mais de 20%.
    assert resultado.status is StatusDaSessao.INVALIDA

    gravado = ler(resultado.dir_sessao)
    assert [item.minuto for item in gravado.minutos_perdidos] == [2]
    assert gravado.status is StatusDaSessao.INVALIDA


def test_AC_004_2_minuto_perdido_nao_interrompe_a_sessao_e_a_captura_segue(
    camera, tmp_path, clipes_legiveis
):
    relogio = RelogioFalso()
    # Buraco na publicação: entre t=60 e t=200 o arquivo não é atualizado, e a
    # janela do minuto 3 (que começa quando o minuto 2 é aceito, em t=60) se
    # esgota em t=150 sem clipe novo.
    servidor = ServidorFalso(
        relogio,
        [(0.0, "clipe-a"), (60.0, "clipe-b"), (200.0, "clipe-c"), (260.0, "clipe-d")],
        clipes_legiveis("clipe-a", "clipe-b", "clipe-c", "clipe-d"),
    )

    resultado = executa(camera, tmp_path, servidor, relogio, minutos=5)

    # A sessão não parou no minuto perdido: os minutos 4 e 5 foram capturados.
    assert [item.minuto for item in resultado.minutos_capturados] == [1, 2, 4, 5]
    assert [item.minuto for item in resultado.minutos_perdidos] == [3]
    assert sorted(p.name for p in resultado.dir_sessao.glob("*.mp4")) == [
        "minuto-01.mp4",
        "minuto-02.mp4",
        "minuto-04.mp4",
        "minuto-05.mp4",
    ]
    # 1 perdido em 5 pedidos é exatamente 20%: DEGRADADA, não INVALIDA.
    assert resultado.status is StatusDaSessao.DEGRADADA
    assert resultado.duracao_pedida == 5
    # AC-003.4: o fim é o Last-Modified do último clipe **capturado**.
    assert resultado.inicio == LAST_MODIFIED_BASE
    assert resultado.fim == LAST_MODIFIED_BASE + timedelta(seconds=260)


def test_AC_004_3_clipe_ilegivel_nao_derruba_a_sessao_e_o_minuto_segue_a_janela(
    camera, tmp_path, clipe_legivel
):
    relogio = RelogioFalso()
    # O primeiro clipe publicado é lixo; o servidor publica um clipe legível em
    # t=60, ainda dentro da janela de 90 s do minuto 1.
    servidor = ServidorFalso(
        relogio,
        [(0.0, "clipe-quebrado"), (60.0, "clipe-bom")],
        {"clipe-quebrado": LIXO, "clipe-bom": clipe_legivel},
    )

    resultado = executa(camera, tmp_path, servidor, relogio, minutos=1)

    # Nenhuma exceção escapou e o minuto foi capturado com o clipe seguinte.
    assert resultado.status is StatusDaSessao.COMPLETA
    assert resultado.minutos_perdidos == ()
    assert [item.etag for item in resultado.minutos_capturados] == ["clipe-bom"]
    # O arquivo ilegível foi descartado e não sobrou no diretório da sessão.
    clipe = resultado.dir_sessao / "minuto-01.mp4"
    assert clipe.read_bytes() == clipe_legivel
    assert sorted(p.name for p in resultado.dir_sessao.iterdir()) == [
        NOME_DO_MANIFEST,
        "minuto-01.mp4",
    ]
    # A checagem seguiu de 10 em 10 s dentro do que sobrou da janela (SUP-008).
    assert INTERVALO_ENTRE_CHECAGENS == 10.0
    assert relogio.decorrido() == 60.0


@pytest.fixture
def outro_clipe_legivel(tmp_path, clipe_legivel) -> bytes:
    """Um segundo clipe legível, de conteúdo comprovadamente diferente.

    Os testes de AC-004.7 precisam separar "clipe republicado" de "clipe novo",
    e para isso os dois vídeos têm de ser legíveis e ter bytes diferentes.
    """
    conteudo = video_valido(tmp_path / "fixture-video-alternativo.mp4", semente=7)
    assert conteudo != clipe_legivel
    return conteudo


def test_AC_004_7_conteudo_igual_ao_do_clipe_anterior_com_etag_novo_nao_abre_minuto(
    camera, tmp_path, clipe_legivel
):
    """AC-004.7: ETag novo com o mesmo vídeo dentro não vira minuto.

    É o caso da sessão `000013-20260908T050407Z`, em que o servidor trocou o
    Last-Modified sem trocar o arquivo e o mesmo vídeo entrou como minuto 1 e
    minuto 2. O ETag identifica o recurso, não o conteúdo (SUP-051).
    """
    relogio = RelogioFalso()
    servidor = ServidorFalso(
        relogio,
        [(0.0, "clipe-a"), (20.0, "clipe-a-republicado")],
        {"clipe-a": clipe_legivel, "clipe-a-republicado": clipe_legivel},
    )

    resultado = executa(camera, tmp_path, servidor, relogio, minutos=2)

    # O minuto 2 não existe como captura: o clipe repetido não abre minuto.
    assert [item.minuto for item in resultado.minutos_capturados] == [1]
    assert [item.minuto for item in resultado.minutos_perdidos] == [2]

    # E o arquivo baixado foi descartado, em vez de ficar no diretório da
    # sessão fingindo ser material capturado.
    assert sorted(p.name for p in resultado.dir_sessao.iterdir()) == [
        NOME_DO_MANIFEST,
        "minuto-01.mp4",
    ]


def test_AC_004_7_conteudo_repetido_por_toda_a_janela_marca_o_minuto_como_nao_capturado(
    camera, tmp_path, clipe_legivel, outro_clipe_legivel
):
    """AC-004.7: janela inteira sem conteúdo inédito → minuto não capturado.

    Mesma regra de AC-004.2, e como lá a sessão **segue** para o minuto
    seguinte. O motivo registrado precisa distinguir esta perda das outras:
    quem ler o manifest depois tem de saber que o servidor republicou o mesmo
    arquivo, e não que o ETag ficou parado.
    """
    relogio = RelogioFalso()
    servidor = ServidorFalso(
        relogio,
        [
            (0.0, "clipe-a"),
            (20.0, "republicado-1"),
            (50.0, "republicado-2"),
            (80.0, "republicado-3"),
            (95.0, "clipe-b"),
        ],
        {
            "clipe-a": clipe_legivel,
            "republicado-1": clipe_legivel,
            "republicado-2": clipe_legivel,
            "republicado-3": clipe_legivel,
            "clipe-b": outro_clipe_legivel,
        },
    )

    resultado = executa(camera, tmp_path, servidor, relogio, minutos=3)

    (perdido,) = resultado.minutos_perdidos
    assert perdido.minuto == 2
    assert "repetido" in perdido.motivo

    # A sessão não foi interrompida: o minuto 3 foi capturado normalmente,
    # com o clipe inédito publicado depois.
    assert [item.minuto for item in resultado.minutos_capturados] == [1, 3]
    assert [item.etag for item in resultado.minutos_capturados] == [
        "clipe-a",
        "clipe-b",
    ]


def test_AC_004_7_conteudo_inedito_depois_do_repetido_dentro_da_janela_e_aceito(
    camera, tmp_path, clipe_legivel, outro_clipe_legivel
):
    """AC-004.7: recusar o repetido não encerra a janela daquele minuto.

    O servidor pode republicar e, em seguida, publicar o clipe de verdade —
    mesmo caminho que AC-004.3 já usa para o clipe ilegível.
    """
    relogio = RelogioFalso()
    servidor = ServidorFalso(
        relogio,
        [(0.0, "clipe-a"), (10.0, "republicado"), (40.0, "clipe-b")],
        {
            "clipe-a": clipe_legivel,
            "republicado": clipe_legivel,
            "clipe-b": outro_clipe_legivel,
        },
    )

    resultado = executa(camera, tmp_path, servidor, relogio, minutos=2)

    assert resultado.status is StatusDaSessao.COMPLETA
    assert resultado.minutos_perdidos == ()
    assert [item.etag for item in resultado.minutos_capturados] == [
        "clipe-a",
        "clipe-b",
    ]
    assert (resultado.dir_sessao / "minuto-02.mp4").read_bytes() == outro_clipe_legivel

    # O hash de conteúdo de cada minuto ficou gravado (SUP-051), e são
    # diferentes entre si — é o que sustenta o "clipes distintos" de AC-003.1.
    gravado = ler(resultado.dir_sessao)
    hashes = [item.sha256 for item in gravado.minutos_capturados]
    assert all(hashes)
    assert len(set(hashes)) == 2


def test_AC_004_7_minuto_perdido_por_conteudo_repetido_entra_no_calculo_do_status(
    camera, tmp_path, clipe_legivel
):
    """AC-004.7: a perda por conteúdo repetido conta como minuto perdido.

    Consequência aceita pelo autor do projeto: o minuto realmente não tem vídeo
    próprio, então entra no denominador de AC-004.5 e AC-004.6 como qualquer
    outra perda. Aqui é 1 de 2 minutos, ou seja, mais de 20% (SUP-013).
    """
    relogio = RelogioFalso()
    servidor = ServidorFalso(
        relogio,
        [(0.0, "clipe-a"), (20.0, "clipe-a-republicado")],
        {"clipe-a": clipe_legivel, "clipe-a-republicado": clipe_legivel},
    )

    resultado = executa(camera, tmp_path, servidor, relogio, minutos=2)

    assert resultado.status is StatusDaSessao.INVALIDA
    assert [item.minuto for item in resultado.minutos_perdidos] == [2]

    # E a perda ficou registrada em disco, com o motivo (AC-004.5).
    gravado = ler(resultado.dir_sessao)
    (perdido,) = gravado.minutos_perdidos
    assert perdido.minuto == 2
    assert "repetido" in perdido.motivo


def test_AC_003_1_sessao_com_clipe_republicado_grava_apenas_clipes_distintos(
    camera, tmp_path, clipe_legivel, outro_clipe_legivel
):
    """AC-003.1: os clipes em disco são distintos, e não só os ETags.

    Sem AC-004.7 esta sessão gravaria dois arquivos de conteúdo idêntico em
    minutos diferentes, e `contagem-veiculos` contaria os mesmos veículos duas
    vezes — o que US-007 existe para evitar e a janela de emenda não pegaria,
    porque a repetição é do clipe inteiro, não dos 2 s do corte.
    """
    relogio = RelogioFalso()
    servidor = ServidorFalso(
        relogio,
        [(0.0, "clipe-a"), (10.0, "republicado"), (40.0, "clipe-b")],
        {
            "clipe-a": clipe_legivel,
            "republicado": clipe_legivel,
            "clipe-b": outro_clipe_legivel,
        },
    )

    resultado = executa(camera, tmp_path, servidor, relogio, minutos=2)

    videos = sorted(resultado.dir_sessao.glob("*.mp4"))
    assert [caminho.name for caminho in videos] == [
        "minuto-01.mp4",
        "minuto-02.mp4",
    ]
    conteudos = [caminho.read_bytes() for caminho in videos]
    assert len(set(conteudos)) == 2


def test_AC_012_1_o_gancho_recebe_cada_minuto_resolvido_em_ordem_com_o_desfecho(
    camera, tmp_path, clipes_legiveis
):
    relogio = RelogioFalso()
    # Minuto 2 perdido (janela de 0 a 90 s sem clipe novo); o minuto 3 pega o
    # clipe publicado em t=100.
    servidor = ServidorFalso(
        relogio,
        [(0.0, "clipe-a"), (100.0, "clipe-c")],
        clipes_legiveis("clipe-a", "clipe-c"),
    )
    chamadas: list[tuple[int, bool]] = []

    capturar(
        camera,
        3,
        data_dir=tmp_path / "data",
        cliente=servidor.cliente(),
        agora=relogio.agora,
        dormir=DormirFalso(relogio),
        ao_resolver_minuto=lambda minuto, capturado: chamadas.append(
            (minuto, capturado)
        ),
    )

    assert chamadas == [(1, True), (2, False), (3, True)]


def test_AC_012_1_o_gancho_e_chamado_depois_do_manifest_gravado(
    camera, tmp_path, clipes_legiveis
):
    relogio = RelogioFalso()
    servidor = ServidorFalso(
        relogio,
        [(0.0, "clipe-a"), (100.0, "clipe-c")],
        clipes_legiveis("clipe-a", "clipe-c"),
    )
    visto: list[tuple[list[int], list[int]]] = []

    def observador(minuto: int, capturado: bool) -> None:
        dir_sessao = next((tmp_path / "data" / "sessions").iterdir())
        gravado = ler(dir_sessao)
        visto.append(
            (
                [item.minuto for item in gravado.minutos_capturados],
                [item.minuto for item in gravado.minutos_perdidos],
            )
        )

    capturar(
        camera,
        3,
        data_dir=tmp_path / "data",
        cliente=servidor.cliente(),
        agora=relogio.agora,
        dormir=DormirFalso(relogio),
        ao_resolver_minuto=observador,
    )

    # Em cada chamada, o manifest em disco já traz o minuto que acabou de ser
    # resolvido.
    assert visto == [([1], []), ([1], [2]), ([1, 3], [2])]

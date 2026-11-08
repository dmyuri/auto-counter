"""Processamento da sessão inteira, minuto a minuto — T-12.

Critérios cobertos, de `.spec/features/contagem-veiculos/spec.md`:

- AC-007.1 — um cruzamento no fim de um clipe e outro de assinatura compatível
  no início do clipe imediatamente seguinte contam uma vez só;
- AC-007.2 — assinaturas diferentes nos dois lados da emenda contam duas vezes;
- AC-007.3 — o rastreador reinicia a cada clipe e nenhum id de rastreio se
  repete entre os minutos da sessão;
- AC-007.4 — minuto perdido entre dois clipes quebra a adjacência e desliga a
  janela de deduplicação; e a sessão `INVALIDA` é processada normalmente
  (SUP-021).

Mais os dois ramos de D-4: clipe ausente vira minuto não processado e a sessão
segue; sessão sem nenhum clipe em disco falha com erro explícito.

Os clipes são vídeos sintéticos escritos com `cv2.VideoWriter`, e o detector e
o ByteTrack são dublês (D-8) — nenhum teste aqui carrega o `.onnx`. Se o codec
`mp4v` não existir na máquina, o teste **falha**: `audit.py` trata teste pulado
igual a teste que falhou.

A linha é a mesma dos testes de T-09 e T-11: vertical, de `(100, 0)` a
`(100, 200)`. A normal de SUP-003 aponta para a esquerda, então quem anda da
direita para a esquerda recebe `sentido_a`.

Cada clipe tem 6 quadros e amostragem 3, ou seja **dois** frames analisados por
clipe — o mínimo para haver cruzamento — e 0,2 s de duração, bem dentro da
janela de 2 s de AC-007.1 dos dois lados do corte.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import cv2
import numpy as np
import pytest
import supervision as sv

from auto_counter.cameras.model import Camera, Linha, Ponto
from auto_counter.capture.manifest import ManifestDaSessao, nome_do_arquivo_do_minuto
from auto_counter.capture.status import StatusDaSessao
from auto_counter.counting.config import Categoria, ConfiguracaoDoProcessamento
from auto_counter.counting import sampling
from auto_counter.counting.events import NOME_DO_ARQUIVO_DE_EVENTOS
from auto_counter.counting.events import ler as ler_eventos
from auto_counter.counting.session import (
    ProcessamentoCancelado,
    SessaoSemClipes,
    processar_sessao,
)
from auto_counter.counting.sampling import (
    MOTIVO_NAO_ABRE,
    AmostragemDoClipe,
    FrameAmostrado,
)

LARGURA = 128
ALTURA = 48
FPS = 30.0
QUADROS_POR_CLIPE = 6
AMOSTRAGEM = 3
ID_CAMERA = "000013"
ID_SESSAO = "000013-20260504T123000Z"
VERSAO_DO_MODELO = "yolo11n.onnx@0123456789ab"
PRIMEIRO_LAST_MODIFIED = datetime(2026, 5, 4, 12, 30, 0, tzinfo=timezone.utc)

CLASSE_COCO_POR_CATEGORIA = {
    Categoria.CARRO: 2,
    Categoria.MOTO: 3,
    Categoria.ONIBUS: 5,
    Categoria.CAMINHAO: 7,
}

DIREITA = (110.0, 40.0)
ESQUERDA = (90.0, 40.0)
CRUZA_PARA_A_ESQUERDA = (DIREITA, ESQUERDA)
"""As duas posições analisadas de um clipe em que o veículo cruza a linha."""


def camera() -> Camera:
    """A câmera do teste, com os rótulos de sentido dela (AC-001.1)."""
    return Camera(
        resolucao={"largura": 1280, "altura": 720},
        id=ID_CAMERA,
        nome="Praça Renascença",
        sentido_a="CENTRO",
        sentido_b="ICARAI",
        linha=Linha(p1=Ponto(x=100, y=0), p2=Ponto(x=100, y=200)),
    )


class DetectorDuble:
    """Dublê do detector (D-8): um roteiro de posições e categorias.

    O roteiro é consumido na ordem dos frames **analisados**, atravessando os
    clipes da sessão: o item `i` é o `i`-ésimo frame que chegou ao detector,
    seja de que minuto for. É isso que deixa o teste fabricar um cruzamento no
    fim de um clipe e outro no início do seguinte. Item `None` é frame sem
    ninguém em cena.
    """

    def __init__(self, roteiro, confianca: float = 0.9):
        self._roteiro = list(roteiro)
        self._confianca = confianca
        self.chamadas = 0

    def detectar(self, frame: np.ndarray) -> sv.Detections:
        indice = self.chamadas
        self.chamadas += 1
        if indice >= len(self._roteiro) or self._roteiro[indice] is None:
            return sv.Detections.empty()
        posicao, categoria = self._roteiro[indice]
        x, y = posicao
        return sv.Detections(
            xyxy=np.array([[x - 5.0, y - 20.0, x + 5.0, y]], dtype=np.float32),
            confidence=np.array([self._confianca], dtype=np.float32),
            class_id=np.array([CLASSE_COCO_POR_CATEGORIA[categoria]], dtype=int),
            data={"categoria": np.array([categoria.value])},
        )


class ByteTrackDuble:
    """Dublê do `ByteTrack` (D-8): id fixo para o único veículo em cena.

    O id é **o mesmo** em todos os clipes de propósito: é assim que AC-007.3
    fica verificável — se `processar_sessao` reaproveitasse o rastreador, ou
    não compusesse o id com o minuto (D-9), os ids da sessão colidiriam.
    """

    def __init__(self, id_do_bytetrack: int = 7):
        self._id = id_do_bytetrack

    def update_with_detections(self, deteccoes):
        if len(deteccoes) == 0:
            return deteccoes
        return sv.Detections(
            xyxy=deteccoes.xyxy,
            confidence=deteccoes.confidence,
            class_id=deteccoes.class_id,
            tracker_id=np.array([self._id] * len(deteccoes), dtype=int),
            data=dict(deteccoes.data),
        )


def roteiro_do_clipe(posicoes, categoria: Categoria = Categoria.CARRO):
    """As duas entradas de roteiro de um clipe com um veículo em cena."""
    return [(posicao, categoria) for posicao in posicoes]


def escreve_clipe(caminho: Path) -> Path:
    """Um MP4 válido e curto, do tamanho fixo de todos os clipes do teste."""
    escritor = cv2.VideoWriter(
        str(caminho), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (LARGURA, ALTURA)
    )
    assert escritor.isOpened(), (
        "o codec mp4v não está disponível nesta máquina e a fixture de vídeo "
        "válido não pôde ser gerada"
    )
    try:
        for _ in range(QUADROS_POR_CLIPE):
            escritor.write(np.zeros((ALTURA, LARGURA, 3), dtype=np.uint8))
    finally:
        escritor.release()
    assert caminho.exists() and caminho.stat().st_size > 0
    return caminho


def monta_sessao(
    tmp_path: Path,
    *,
    minutos_capturados,
    minutos_perdidos=(),
    minutos_sem_arquivo=(),
    status: StatusDaSessao = StatusDaSessao.COMPLETA,
) -> Path:
    """Cria o diretório da sessão com manifest e clipes, e devolve o caminho.

    `minutos_sem_arquivo` são minutos que o manifest declara capturados mas
    cujo `.mp4` não existe em disco — o ramo de clipe ausente de D-4.
    """
    dir_sessao = tmp_path / "sessions" / ID_SESSAO
    manifest = ManifestDaSessao(
        dir_sessao,
        id_sessao=ID_SESSAO,
        id_camera=ID_CAMERA,
        duracao_pedida=max([*minutos_capturados, *minutos_perdidos], default=0),
        status=status,
    )
    dir_sessao.mkdir(parents=True, exist_ok=True)
    for minuto in sorted([*minutos_capturados, *minutos_perdidos]):
        if minuto in minutos_perdidos:
            manifest.registrar_perda(minuto, motivo="ETag parado na janela")
            continue
        manifest.registrar_minuto(
            minuto,
            etag=f"etag-{minuto}",
            last_modified=PRIMEIRO_LAST_MODIFIED + timedelta(minutes=minuto - 1),
            relogio_local=PRIMEIRO_LAST_MODIFIED + timedelta(minutes=minuto - 1),
        )
        if minuto not in minutos_sem_arquivo:
            escreve_clipe(dir_sessao / nome_do_arquivo_do_minuto(minuto))
    return dir_sessao


def processa(dir_sessao: Path, detector: DetectorDuble, **extra):
    """Roda `processar_sessao` com os dublês e a configuração do teste."""
    return processar_sessao(
        dir_sessao,
        camera=camera(),
        detector=detector,
        config=ConfiguracaoDoProcessamento(amostragem=AMOSTRAGEM),
        versao_do_modelo=VERSAO_DO_MODELO,
        fabrica_de_bytetrack=lambda: ByteTrackDuble(),
        **extra,
    )


def test_AC_007_1_veiculo_na_emenda_entre_dois_minutos_adjacentes_conta_uma_vez(
    tmp_path,
):
    """Mesma categoria, mesmo sentido e mesma posição nos dois lados do corte.

    Os minutos 1 e 2 são consecutivos e os dois foram capturados, então são
    adjacentes: o cruzamento do início do minuto 2 é a continuação do que
    aconteceu no fim do minuto 1, e não gera evento novo.
    """
    dir_sessao = monta_sessao(tmp_path, minutos_capturados=(1, 2))
    detector = DetectorDuble(
        roteiro_do_clipe(CRUZA_PARA_A_ESQUERDA)
        + roteiro_do_clipe(CRUZA_PARA_A_ESQUERDA)
    )

    resultado = processa(dir_sessao, detector)

    assert len(resultado.eventos) == 1
    assert resultado.eventos[0].minuto == 1
    assert resultado.minutos_processados == (1, 2)


def test_AC_007_2_veiculos_distintos_na_emenda_contam_os_dois(tmp_path):
    """Categorias diferentes nos dois lados do corte são veículos diferentes.

    A assinatura de SUP-019 é categoria + sentido + posição; basta a categoria
    divergir para que o pareamento da emenda não aconteça e os dois cruzamentos
    contem.
    """
    dir_sessao = monta_sessao(tmp_path, minutos_capturados=(1, 2))
    detector = DetectorDuble(
        roteiro_do_clipe(CRUZA_PARA_A_ESQUERDA, Categoria.CARRO)
        + roteiro_do_clipe(CRUZA_PARA_A_ESQUERDA, Categoria.ONIBUS)
    )

    resultado = processa(dir_sessao, detector)

    assert len(resultado.eventos) == 2
    assert [evento.minuto for evento in resultado.eventos] == [1, 2]
    assert {evento.categoria for evento in resultado.eventos} == {
        Categoria.CARRO,
        Categoria.ONIBUS,
    }


def test_AC_007_3_ids_de_rastreio_da_sessao_inteira_nao_se_repetem_entre_minutos(
    tmp_path,
):
    """Três minutos, o mesmo id de ByteTrack, e três ids de rastreio distintos.

    Os cruzamentos têm categorias diferentes só para que a emenda não suprima
    nenhum deles — o que está sob teste aqui é o id, e o teste precisa dos três
    eventos para poder compará-los.
    """
    dir_sessao = monta_sessao(tmp_path, minutos_capturados=(1, 2, 3))
    detector = DetectorDuble(
        roteiro_do_clipe(CRUZA_PARA_A_ESQUERDA, Categoria.CARRO)
        + roteiro_do_clipe(CRUZA_PARA_A_ESQUERDA, Categoria.ONIBUS)
        + roteiro_do_clipe(CRUZA_PARA_A_ESQUERDA, Categoria.CAMINHAO)
    )

    resultado = processa(dir_sessao, detector)

    ids = [evento.id_de_rastreio for evento in resultado.eventos]
    assert len(ids) == 3
    assert len(set(ids)) == 3
    assert ids == ["1:7", "2:7", "3:7"]


def test_AC_007_4_minuto_perdido_entre_dois_clipes_desliga_a_janela_de_deduplicacao(
    tmp_path,
):
    """Minutos 1 e 3 capturados, minuto 2 perdido: os dois cruzamentos contam.

    As assinaturas são idênticas — o mesmo par que AC-007.1 deduplicaria. O que
    muda é só a adjacência: os clipes não se tocam no tempo, então nenhum
    cruzamento de um pode ser a continuação do outro.
    """
    dir_sessao = monta_sessao(
        tmp_path,
        minutos_capturados=(1, 3),
        minutos_perdidos=(2,),
        status=StatusDaSessao.DEGRADADA,
    )
    detector = DetectorDuble(
        roteiro_do_clipe(CRUZA_PARA_A_ESQUERDA)
        + roteiro_do_clipe(CRUZA_PARA_A_ESQUERDA)
    )

    resultado = processa(dir_sessao, detector)

    assert len(resultado.eventos) == 2
    assert [evento.minuto for evento in resultado.eventos] == [1, 3]
    assert resultado.minutos_processados == (1, 3)
    assert [item.minuto for item in resultado.minutos_nao_processados] == [2]


def test_AC_007_4_sessao_invalida_e_processada_normalmente(tmp_path):
    """SUP-021: o status qualifica o resultado, não impede o processamento."""
    dir_sessao = monta_sessao(
        tmp_path, minutos_capturados=(1,), status=StatusDaSessao.INVALIDA
    )
    detector = DetectorDuble(roteiro_do_clipe(CRUZA_PARA_A_ESQUERDA))

    resultado = processa(dir_sessao, detector)

    assert len(resultado.eventos) == 1
    assert resultado.minutos_processados == (1,)
    assert (dir_sessao / NOME_DO_ARQUIVO_DE_EVENTOS).exists()


def test_minuto_com_clipe_ausente_vira_minuto_sem_dado_e_a_sessao_segue(tmp_path):
    """D-4: o minuto sem `.mp4` é registrado com motivo e a sessão continua.

    E, pela mesma regra de AC-007.4, o minuto não processado quebra a
    adjacência: os cruzamentos dos minutos 1 e 3 contam os dois, mesmo com
    assinatura compatível.
    """
    dir_sessao = monta_sessao(
        tmp_path, minutos_capturados=(1, 2, 3), minutos_sem_arquivo=(2,)
    )
    detector = DetectorDuble(
        roteiro_do_clipe(CRUZA_PARA_A_ESQUERDA)
        + roteiro_do_clipe(CRUZA_PARA_A_ESQUERDA)
    )

    resultado = processa(dir_sessao, detector)

    assert resultado.minutos_processados == (1, 3)
    nao_processados = resultado.minutos_nao_processados
    assert [item.minuto for item in nao_processados] == [2]
    assert nao_processados[0].motivo
    assert [evento.minuto for evento in resultado.eventos] == [1, 3]

    gravado = ler_eventos(dir_sessao)
    assert gravado.minutos_processados == (1, 3)
    assert [item.minuto for item in gravado.minutos_nao_processados] == [2]
    assert len(gravado.eventos) == 2


def test_sessao_sem_nenhum_clipe_em_disco_falha_com_erro_explicito(tmp_path):
    """D-4: contagem zerada não pode sair com cara de resultado válido.

    Nem o `eventos.json` pode ficar no disco: a sessão provavelmente já foi
    descartada por D-5, e um arquivo zerado ali seria lido depois como se
    nenhum veículo tivesse passado.
    """
    dir_sessao = monta_sessao(
        tmp_path, minutos_capturados=(1, 2), minutos_sem_arquivo=(1, 2)
    )
    detector = DetectorDuble([])

    with pytest.raises(SessaoSemClipes):
        processa(dir_sessao, detector)

    assert not (dir_sessao / NOME_DO_ARQUIVO_DE_EVENTOS).exists()


class ParadaDuble:
    """A parada de AC-012.5, ligada à mão pelo teste."""

    def __init__(self) -> None:
        self.pedida = False

    def foi_pedida(self) -> bool:
        return self.pedida


def test_AC_012_2_o_gancho_recebe_cada_minuto_capturado_resolvido(tmp_path):
    """Processado ou não, todo minuto capturado é resolvido e informado.

    O minuto 2 tem o clipe ausente (D-4) e é resolvido como não processado; o
    minuto 3, perdido na captura, nunca virou clipe e não é anunciado.
    """
    dir_sessao = monta_sessao(
        tmp_path,
        minutos_capturados=(1, 2, 4),
        minutos_perdidos=(3,),
        minutos_sem_arquivo=(2,),
        status=StatusDaSessao.DEGRADADA,
    )
    detector = DetectorDuble(
        roteiro_do_clipe(CRUZA_PARA_A_ESQUERDA)
        + roteiro_do_clipe(CRUZA_PARA_A_ESQUERDA)
    )
    resolvidos: list[int] = []

    processa(dir_sessao, detector, ao_resolver_minuto=resolvidos.append)

    assert resolvidos == [1, 2, 4]


def test_AC_012_5_parada_pedida_levanta_processamento_cancelado_antes_do_proximo_clipe(
    tmp_path,
):
    dir_sessao = monta_sessao(tmp_path, minutos_capturados=(1, 2, 3))
    detector = DetectorDuble(
        roteiro_do_clipe(CRUZA_PARA_A_ESQUERDA, Categoria.CARRO)
        + roteiro_do_clipe(CRUZA_PARA_A_ESQUERDA, Categoria.ONIBUS)
        + roteiro_do_clipe(CRUZA_PARA_A_ESQUERDA, Categoria.CAMINHAO)
    )
    parada = ParadaDuble()

    def ao_resolver(minuto: int) -> None:
        if minuto == 1:
            parada.pedida = True

    with pytest.raises(ProcessamentoCancelado) as cancelamento:
        processa(
            dir_sessao, detector, parada=parada, ao_resolver_minuto=ao_resolver
        )

    # Dois frames analisados por clipe: só o clipe do minuto 1 chegou ao detector.
    assert detector.chamadas == 2
    assert ID_SESSAO in str(cancelamento.value)


def test_AC_012_5_parada_pedida_antes_do_primeiro_clipe_nao_grava_eventos(tmp_path):
    dir_sessao = monta_sessao(tmp_path, minutos_capturados=(1, 2))
    detector = DetectorDuble(roteiro_do_clipe(CRUZA_PARA_A_ESQUERDA))
    parada = ParadaDuble()
    parada.pedida = True

    with pytest.raises(ProcessamentoCancelado):
        processa(dir_sessao, detector, parada=parada)

    assert detector.chamadas == 0
    assert not (dir_sessao / NOME_DO_ARQUIVO_DE_EVENTOS).exists()


def test_parada_nunca_pedida_nao_altera_o_processamento(tmp_path):
    dir_sessao = monta_sessao(tmp_path, minutos_capturados=(1, 2))
    detector = DetectorDuble(
        roteiro_do_clipe(CRUZA_PARA_A_ESQUERDA, Categoria.CARRO)
        + roteiro_do_clipe(CRUZA_PARA_A_ESQUERDA, Categoria.ONIBUS)
    )

    resultado = processa(dir_sessao, detector, parada=ParadaDuble())

    assert resultado.minutos_processados == (1, 2)
    assert len(resultado.eventos) == 2


def test_o_modulo_de_contagem_nao_importa_httpx():
    import ast

    import auto_counter.counting.session as modulo

    arvore = ast.parse(Path(modulo.__file__).read_text(encoding="utf-8"))
    importados = set()
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            importados.update(alias.name.split(".")[0] for alias in no.names)
        elif isinstance(no, ast.ImportFrom) and no.module:
            importados.add(no.module.split(".")[0])
            if no.module == "auto_counter.capture":
                importados.update(alias.name for alias in no.names)

    assert "httpx" not in importados
    assert "session" not in importados  # `capture.session` traria o `httpx`


class Registro:
    """Os ganchos de `acompanhamento-ao-vivo`, gravando a ordem em que chegam."""

    def __init__(self) -> None:
        self.chamadas: list[tuple] = []

    def aceitar(self, minuto, evento) -> None:
        self.chamadas.append(("aceito", minuto, evento))

    def descartar(self, minuto) -> None:
        self.chamadas.append(("descartado", minuto))

    def resolver(self, minuto) -> None:
        self.chamadas.append(("resolvido", minuto))

    @property
    def publicados(self):
        return [c[2] for c in self.chamadas if c[0] == "aceito"]

    @property
    def descartados(self):
        return [c[1] for c in self.chamadas if c[0] == "descartado"]

    def processa(self, dir_sessao, detector):
        return processa(
            dir_sessao,
            detector,
            ao_aceitar_evento=self.aceitar,
            ao_descartar_minuto=self.descartar,
            ao_resolver_minuto=self.resolver,
        )


def ordenados(eventos):
    return sorted(eventos, key=lambda e: (e.minuto, e.indice_do_frame, e.id_de_rastreio))


def test_AC_016_2_cada_evento_aceito_e_publicado_antes_do_minuto_terminar(tmp_path):
    dir_sessao = monta_sessao(tmp_path, minutos_capturados=(1, 2))
    detector = DetectorDuble(
        roteiro_do_clipe(CRUZA_PARA_A_ESQUERDA, Categoria.CARRO)
        + roteiro_do_clipe(CRUZA_PARA_A_ESQUERDA, Categoria.ONIBUS)
    )
    registro = Registro()

    registro.processa(dir_sessao, detector)

    assert [(c[0], c[1]) for c in registro.chamadas] == [
        ("aceito", 1),
        ("resolvido", 1),
        ("aceito", 2),
        ("resolvido", 2),
    ]


def test_AC_016_3_duplicata_da_emenda_nunca_e_publicada(tmp_path):
    """O cenário de AC-007.1: o cruzamento do minuto 2 repete o do minuto 1."""
    dir_sessao = monta_sessao(tmp_path, minutos_capturados=(1, 2))
    detector = DetectorDuble(
        roteiro_do_clipe(CRUZA_PARA_A_ESQUERDA)
        + roteiro_do_clipe(CRUZA_PARA_A_ESQUERDA)
    )
    registro = Registro()

    registro.processa(dir_sessao, detector)

    assert [e.minuto for e in registro.publicados] == [1]


def test_AC_016_3_publicados_sao_exatamente_os_eventos_gravados(tmp_path):
    dir_sessao = monta_sessao(tmp_path, minutos_capturados=(1, 2, 3))
    detector = DetectorDuble(
        roteiro_do_clipe(CRUZA_PARA_A_ESQUERDA, Categoria.CARRO)
        + roteiro_do_clipe(CRUZA_PARA_A_ESQUERDA, Categoria.CARRO)  # duplicata
        + roteiro_do_clipe(CRUZA_PARA_A_ESQUERDA, Categoria.MOTO)
    )
    registro = Registro()

    resultado = registro.processa(dir_sessao, detector)

    assert len(registro.publicados) == 2
    assert ordenados(registro.publicados) == ordenados(resultado.eventos)
    assert ordenados(registro.publicados) == ordenados(ler_eventos(dir_sessao).eventos)


def test_AC_006_6_mesmo_rastreio_no_mesmo_sentido_e_publicado_uma_vez(tmp_path):
    """Um rastreio que oscila sobre a linha: ida, volta e ida de novo.

    A segunda ida é o mesmo par (rastreio, sentido) e não gera publicação.
    """
    dir_sessao = monta_sessao(tmp_path, minutos_capturados=(1,))
    escritor = cv2.VideoWriter(
        str(dir_sessao / nome_do_arquivo_do_minuto(1)),
        cv2.VideoWriter_fourcc(*"mp4v"),
        FPS,
        (LARGURA, ALTURA),
    )
    for _ in range(4 * AMOSTRAGEM):
        escritor.write(np.zeros((ALTURA, LARGURA, 3), dtype=np.uint8))
    escritor.release()
    detector = DetectorDuble(
        roteiro_do_clipe((DIREITA, ESQUERDA, DIREITA, ESQUERDA))
    )
    registro = Registro()

    registro.processa(dir_sessao, detector)

    sentidos = [e.sentido for e in registro.publicados]
    assert sentidos.count("CENTRO") == 1
    assert len(sentidos) == len(set(sentidos))


def test_AC_016_6_minuto_perdido_e_clipe_sem_frame_nao_publicam_nada(tmp_path):
    """Perdido na captura, arquivo ausente e arquivo ilegível: nada é somado.

    Só o minuto 1 tem cruzamento; os demais não podem publicar evento algum.
    """
    dir_sessao = monta_sessao(
        tmp_path,
        minutos_capturados=(1, 2, 3, 5),
        minutos_perdidos=(4,),
        minutos_sem_arquivo=(2,),
        status=StatusDaSessao.DEGRADADA,
    )
    (dir_sessao / nome_do_arquivo_do_minuto(3)).write_bytes(b"isto nao e um mp4")
    detector = DetectorDuble(roteiro_do_clipe(CRUZA_PARA_A_ESQUERDA))
    registro = Registro()

    registro.processa(dir_sessao, detector)

    assert [e.minuto for e in registro.publicados] == [1]


class AmostragemQueFalhaNoFim(AmostragemDoClipe):
    """Entrega os frames 0 e 3 e então falha, como o `except` de `sampling.py`."""

    def __iter__(self):
        self.fps = FPS
        for indice in (0, 3):
            self.total_de_frames = indice + 1
            yield FrameAmostrado(
                indice=indice, imagem=np.zeros((ALTURA, LARGURA, 3), dtype=np.uint8)
            )
        self.motivo = MOTIVO_NAO_ABRE


def test_AC_016_8_clipe_que_falha_no_meio_publica_e_depois_descarta_o_minuto(
    tmp_path, monkeypatch
):
    dir_sessao = monta_sessao(tmp_path, minutos_capturados=(1, 2))
    real = sampling.frames_amostrados

    def falha_no_minuto_2(caminho, amostragem):
        if Path(caminho).name == nome_do_arquivo_do_minuto(2):
            return AmostragemQueFalhaNoFim(caminho, amostragem)
        return real(caminho, amostragem)

    monkeypatch.setattr(
        "auto_counter.counting.clip.frames_amostrados", falha_no_minuto_2
    )
    detector = DetectorDuble(
        roteiro_do_clipe(CRUZA_PARA_A_ESQUERDA, Categoria.CARRO)
        + roteiro_do_clipe(CRUZA_PARA_A_ESQUERDA, Categoria.ONIBUS)
    )
    registro = Registro()

    resultado = registro.processa(dir_sessao, detector)

    assert [(c[0], c[1]) for c in registro.chamadas] == [
        ("aceito", 1),
        ("resolvido", 1),
        ("aceito", 2),
        ("descartado", 2),
        ("resolvido", 2),
    ]
    assert [e.minuto for e in resultado.eventos] == [1]


# --- layout-interface: gancho `ao_iniciar_minuto` (T-03) ---


class RegistroComInicio(Registro):
    """`Registro` com o gancho que marca o início de cada minuto (SUP-070)."""

    def iniciar(self, minuto) -> None:
        self.chamadas.append(("iniciado", minuto))

    def processa(self, dir_sessao, detector):
        return processa(
            dir_sessao,
            detector,
            ao_iniciar_minuto=self.iniciar,
            ao_aceitar_evento=self.aceitar,
            ao_descartar_minuto=self.descartar,
            ao_resolver_minuto=self.resolver,
        )


def test_AC_022_6_ao_iniciar_minuto_e_chamado_antes_do_clipe_de_cada_minuto(tmp_path):
    dir_sessao = monta_sessao(tmp_path, minutos_capturados=(1, 2))
    detector = DetectorDuble(
        roteiro_do_clipe(CRUZA_PARA_A_ESQUERDA, Categoria.CARRO)
        + roteiro_do_clipe(CRUZA_PARA_A_ESQUERDA, Categoria.ONIBUS)
    )
    registro = RegistroComInicio()

    registro.processa(dir_sessao, detector)

    assert [(c[0], c[1]) for c in registro.chamadas] == [
        ("iniciado", 1),
        ("aceito", 1),
        ("resolvido", 1),
        ("iniciado", 2),
        ("aceito", 2),
        ("resolvido", 2),
    ]


def test_AC_022_6_minuto_perdido_na_captura_nao_chama_ao_iniciar_minuto(tmp_path):
    dir_sessao = monta_sessao(
        tmp_path,
        minutos_capturados=(1, 3),
        minutos_perdidos=(2,),
        status=StatusDaSessao.DEGRADADA,
    )
    detector = DetectorDuble(
        roteiro_do_clipe(CRUZA_PARA_A_ESQUERDA)
        + roteiro_do_clipe(CRUZA_PARA_A_ESQUERDA)
    )
    iniciados: list[int] = []

    processa(dir_sessao, detector, ao_iniciar_minuto=iniciados.append)

    assert iniciados == [1, 3]


def test_AC_022_6_clipe_que_falha_tambem_chama_ao_iniciar_minuto(
    tmp_path, monkeypatch
):
    dir_sessao = monta_sessao(tmp_path, minutos_capturados=(1, 2))
    real = sampling.frames_amostrados

    def falha_no_minuto_2(caminho, amostragem):
        if Path(caminho).name == nome_do_arquivo_do_minuto(2):
            return AmostragemQueFalhaNoFim(caminho, amostragem)
        return real(caminho, amostragem)

    monkeypatch.setattr(
        "auto_counter.counting.clip.frames_amostrados", falha_no_minuto_2
    )
    detector = DetectorDuble(
        roteiro_do_clipe(CRUZA_PARA_A_ESQUERDA, Categoria.CARRO)
        + roteiro_do_clipe(CRUZA_PARA_A_ESQUERDA, Categoria.ONIBUS)
    )
    registro = RegistroComInicio()

    registro.processa(dir_sessao, detector)

    # Os eventos publicados antes da falha não interessam aqui: a ordem que
    # importa é inicia → descarta → resolve.
    assert [
        (c[0], c[1]) for c in registro.chamadas if c[0] != "aceito"
    ] == [
        ("iniciado", 1),
        ("resolvido", 1),
        ("iniciado", 2),
        ("descartado", 2),
        ("resolvido", 2),
    ]


def test_AC_022_6_parada_antes_do_minuto_nao_chama_ao_iniciar_minuto(tmp_path):
    dir_sessao = monta_sessao(tmp_path, minutos_capturados=(1, 2))
    detector = DetectorDuble(
        roteiro_do_clipe(CRUZA_PARA_A_ESQUERDA, Categoria.CARRO)
        + roteiro_do_clipe(CRUZA_PARA_A_ESQUERDA, Categoria.ONIBUS)
    )
    parada = ParadaDuble()
    iniciados: list[int] = []

    def ao_resolver(minuto: int) -> None:
        if minuto == 1:
            parada.pedida = True

    with pytest.raises(ProcessamentoCancelado):
        processa(
            dir_sessao,
            detector,
            parada=parada,
            ao_iniciar_minuto=iniciados.append,
            ao_resolver_minuto=ao_resolver,
        )

    assert iniciados == [1]


def test_sem_ao_iniciar_minuto_o_resultado_e_identico(tmp_path):
    def roda(raiz: Path, **extra):
        dir_sessao = monta_sessao(raiz, minutos_capturados=(1, 2))
        detector = DetectorDuble(
            roteiro_do_clipe(CRUZA_PARA_A_ESQUERDA, Categoria.CARRO)
            + roteiro_do_clipe(CRUZA_PARA_A_ESQUERDA, Categoria.ONIBUS)
        )
        resultado = processa(dir_sessao, detector, **extra)
        return resultado, (dir_sessao / NOME_DO_ARQUIVO_DE_EVENTOS).read_bytes()

    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    sem, bytes_sem = roda(tmp_path / "a")
    com, bytes_com = roda(tmp_path / "b", ao_iniciar_minuto=lambda minuto: None)

    assert com.eventos == sem.eventos
    assert com.minutos_processados == sem.minutos_processados
    assert bytes_com == bytes_sem

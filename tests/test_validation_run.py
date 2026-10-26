"""Testes da execução da validação de ponta a ponta, sem rede.

Comportamento definido em `.spec/features/validacao-acuracia/spec.md`:
AC-014.4, AC-014.5 e AC-015.1, com D-3 e D-10 da lista de tarefas. O conjunto de
referência é sintético, montado em `tmp_path` (manifest, CSVs e vídeos escritos
por `cv2.VideoWriter`), e o detector é um dublê roteirizado para produzir
números conhecidos. Nenhum teste aqui carrega o `.onnx` nem lê o
`tests/ground_truth/` real. Nenhum leva o ID AC-014.3 no nome (D-9).
"""

import socket
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import cv2
import numpy as np
import pytest
import supervision as sv

from auto_counter.cameras.model import Camera, Linha, Ponto
from auto_counter.cameras.registry import Registro
from auto_counter.counting.config import Categoria, ConfiguracaoDoProcessamento
from auto_counter.validation.automatic import ClipeDeReferenciaIlegivelError
from auto_counter.validation.model import Condicao
from auto_counter.validation.run import (
    CameraDoClipeAusenteError,
    VideosDeReferenciaAusentesError,
    executar_validacao,
)
from tests.conftest import rede_bloqueada

LARGURA = 128
ALTURA = 48
FPS = 30.0
AMOSTRAGEM = 3
ID_CAMERA = "000013"
A = "Icaraí"
B = "Centro"
VERSAO_DO_MODELO = "yolo11n.onnx@0123456789ab"
EXECUTADO_EM = datetime(2026, 10, 26, 12, 0, 0, tzinfo=timezone.utc)
BASE = datetime(2026, 9, 8, 20, 15, 0, tzinfo=timezone.utc)
LAST_MODIFIED = {
    "pico": BASE,
    "fora_pico": BASE + timedelta(days=1),
    "noturno": BASE + timedelta(days=2),
    "chuva": BASE + timedelta(days=3),
}
CABECALHO = "instante_s,categoria,sentido\n"

DIREITA = (110.0, 40.0)
ESQUERDA = (90.0, 40.0)
CRUZA_PARA_A_ESQUERDA = (DIREITA, ESQUERDA)
CLASSE_COCO_POR_CATEGORIA = {
    Categoria.CARRO: 2,
    Categoria.MOTO: 3,
    Categoria.ONIBUS: 5,
    Categoria.CAMINHAO: 7,
}


def camera() -> Camera:
    return Camera(
        id=ID_CAMERA,
        nome="Praça Renascença",
        sentido_a=A,
        sentido_b=B,
        linha=Linha(p1=Ponto(x=100, y=0), p2=Ponto(x=100, y=200)),
    )


def registro() -> Registro:
    return Registro(cameras=[camera()], rejeicoes=[])


class DetectorDuble:
    """Roteiro de posições e categorias, consumido na ordem dos frames analisados."""

    def __init__(self, roteiro):
        self._roteiro = list(roteiro)
        self.chamadas = 0

    def detectar(self, frame: np.ndarray) -> sv.Detections:
        indice = self.chamadas
        self.chamadas += 1
        if indice >= len(self._roteiro) or self._roteiro[indice] is None:
            return sv.Detections.empty()
        (x, y), categoria = self._roteiro[indice]
        return sv.Detections(
            xyxy=np.array([[x - 5.0, y - 20.0, x + 5.0, y]], dtype=np.float32),
            confidence=np.array([0.9], dtype=np.float32),
            class_id=np.array([CLASSE_COCO_POR_CATEGORIA[categoria]], dtype=int),
            data={"categoria": np.array([categoria.value])},
        )


class ByteTrackDuble:
    def update_with_detections(self, deteccoes):
        if len(deteccoes) == 0:
            return deteccoes
        return sv.Detections(
            xyxy=deteccoes.xyxy,
            confidence=deteccoes.confidence,
            class_id=deteccoes.class_id,
            tracker_id=np.array([7] * len(deteccoes), dtype=int),
            data=dict(deteccoes.data),
        )


def um_cruzamento(categoria: Categoria = Categoria.CARRO):
    """Duas entradas de roteiro: o veículo cruza a linha no clipe (sentido A)."""
    return [(posicao, categoria) for posicao in CRUZA_PARA_A_ESQUERDA]


SEM_VEICULO = [None, None]
"""Os dois frames analisados de um clipe sem ninguém em cena."""


def escreve_video(caminho: Path) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    escritor = cv2.VideoWriter(
        str(caminho), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (LARGURA, ALTURA)
    )
    assert escritor.isOpened(), (
        "o codec mp4v não está disponível nesta máquina e a fixture de vídeo "
        "válido não pôde ser gerada"
    )
    try:
        for _ in range(6):
            escritor.write(np.zeros((ALTURA, LARGURA, 3), dtype=np.uint8))
    finally:
        escritor.release()


def monta_conjunto(
    raiz: Path,
    *,
    com_chuva: bool = False,
    csvs: dict[str, str] | None = None,
    sem_video=(),
    video_corrompido=(),
) -> Path:
    """Manifest, CSVs e vídeos sintéticos. Cada CSV tem, por padrão, um carro no
    sentido A a 0 s, que é o que o detector roteirizado produz."""
    condicoes = ["pico", "fora_pico", "noturno"] + (["chuva"] if com_chuva else [])
    raiz.mkdir(parents=True, exist_ok=True)
    manifest = "versao: 1\nclipes:\n" + "".join(
        f"  - condicao: {c}\n"
        f'    camera: "{ID_CAMERA}"\n'
        f'    last_modified: "{LAST_MODIFIED[c].isoformat()}"\n'
        f"    etag: '\"etag-{c}\"'\n"
        for c in condicoes
    )
    (raiz / "manifest.yaml").write_text(manifest, encoding="utf-8")
    for c in condicoes:
        conteudo = (csvs or {}).get(c, CABECALHO + f"0,CARRO,{A}\n")
        (raiz / f"{c}.csv").write_text(conteudo, encoding="utf-8")
        if c in sem_video:
            continue
        if c in video_corrompido:
            (raiz / "clipes").mkdir(exist_ok=True)
            (raiz / "clipes" / f"{c}.mp4").write_bytes(b"isto nao e um mp4")
        else:
            escreve_video(raiz / "clipes" / f"{c}.mp4")
    return raiz


def executa(raiz: Path, tmp_path: Path, detector, *, executado_em=EXECUTADO_EM, rotulo="1"):
    return executar_validacao(
        raiz,
        registro=registro(),
        detector=detector,
        config=ConfiguracaoDoProcessamento(amostragem=AMOSTRAGEM),
        versao_do_modelo=VERSAO_DO_MODELO,
        dir_trabalho=tmp_path / f"trabalho-{rotulo}",
        data_dir_do_relatorio=tmp_path / "dados",
        executado_em=executado_em,
        fabrica_de_bytetrack=ByteTrackDuble,
    )


def roteiro_que_acerta_tudo(com_chuva: bool = False):
    return um_cruzamento() * (4 if com_chuva else 3)


def roteiro_com_fora_pico_sem_veiculo():
    return um_cruzamento() + SEM_VEICULO + um_cruzamento()


def test_AC_014_4_validacao_com_clipe_fora_do_limite_reprova_com_clipe_metrica_e_valor(
    tmp_path,
):
    raiz = monta_conjunto(tmp_path / "gt")

    resultado, _ = executa(raiz, tmp_path, DetectorDuble(roteiro_com_fora_pico_sem_veiculo()))

    assert resultado.veredito.passou is False
    por_chave = {(v.condicao, v.metrica, v.sentido): v for v in resultado.veredito.violacoes}
    erro = por_chave[(Condicao.FORA_PICO, "erro de contagem", A)]
    assert erro.valor == 1
    assert (erro.numerador, erro.denominador) == (1, 1)
    assert (Condicao.FORA_PICO, "acerto de categoria", None) in por_chave
    assert all(chave[0] is Condicao.FORA_PICO for chave in por_chave)
    pico, fora_pico, noturno = resultado.clipes
    assert pico.veredito.passou and noturno.veredito.passou
    assert fora_pico.veredito.passou is False


def test_AC_014_5_validacao_roda_sem_nenhuma_requisicao_de_rede(tmp_path, sem_rede):
    raiz = monta_conjunto(tmp_path / "gt")

    resultado, _ = executa(raiz, tmp_path, DetectorDuble(roteiro_que_acerta_tudo()))

    assert sem_rede == []
    assert resultado.veredito.passou is True
    assert [c.clipe.condicao for c in resultado.clipes] == [
        Condicao.PICO,
        Condicao.FORA_PICO,
        Condicao.NOTURNO,
    ]


def test_AC_014_5_duas_execucoes_sobre_a_mesma_entrada_dao_o_mesmo_veredito(tmp_path):
    raiz = monta_conjunto(tmp_path / "gt")

    um, caminho_um = executa(
        raiz, tmp_path, DetectorDuble(roteiro_com_fora_pico_sem_veiculo()), rotulo="1"
    )
    outro, caminho_outro = executa(
        raiz,
        tmp_path,
        DetectorDuble(roteiro_com_fora_pico_sem_veiculo()),
        executado_em=EXECUTADO_EM + timedelta(minutes=7),
        rotulo="2",
    )

    assert caminho_um != caminho_outro
    assert um.veredito == outro.veredito
    assert um.clipes == outro.clipes
    texto_um = caminho_um.read_text(encoding="utf-8").splitlines()
    texto_outro = caminho_outro.read_text(encoding="utf-8").splitlines()
    diferentes = [(a, b) for a, b in zip(texto_um, texto_outro) if a != b]
    assert len(texto_um) == len(texto_outro)
    assert len(diferentes) == 1 and diferentes[0][0].startswith("Executado em")


def test_AC_015_1_validacao_reprovada_tambem_grava_o_relatorio(tmp_path):
    raiz = monta_conjunto(tmp_path / "gt")

    resultado, caminho = executa(
        raiz, tmp_path, DetectorDuble(roteiro_com_fora_pico_sem_veiculo())
    )

    assert resultado.veredito.passou is False
    assert caminho == tmp_path / "dados" / "validacao" / "relatorio-20261026T120000Z.txt"
    texto = caminho.read_text(encoding="utf-8")
    assert "VEREDITO DO CONJUNTO: REPROVADO" in texto
    assert "clipe fora_pico: erro de contagem no sentido Icaraí = 100.00% (1/1)" in texto


def test_AC_015_1_chuva_sem_video_e_reportada_como_nao_medida_sem_interromper(tmp_path):
    raiz = monta_conjunto(tmp_path / "gt", com_chuva=True, sem_video=("chuva",))

    resultado, caminho = executa(raiz, tmp_path, DetectorDuble(roteiro_que_acerta_tudo()))

    chuva = resultado.clipes[-1]
    assert chuva.clipe.condicao is Condicao.CHUVA
    assert chuva.medicao is None
    assert "ausente" in chuva.motivo_nao_medido
    assert resultado.veredito.passou is True
    texto = caminho.read_text(encoding="utf-8")
    assert "não medido" in texto
    assert "VEREDITO DO CONJUNTO: APROVADO" in texto


def test_AC_015_1_chuva_ilegivel_e_reportada_como_nao_medida_sem_falhar(tmp_path):
    raiz = monta_conjunto(tmp_path / "gt", com_chuva=True, video_corrompido=("chuva",))

    resultado, caminho = executa(raiz, tmp_path, DetectorDuble(roteiro_que_acerta_tudo()))

    chuva = resultado.clipes[-1]
    assert chuva.medicao is None
    assert "ilegível" in chuva.motivo_nao_medido
    assert resultado.veredito.passou is True
    assert "ilegível" in caminho.read_text(encoding="utf-8")


def test_AC_015_1_chuva_medida_aparece_no_relatorio_sem_alterar_o_veredito(tmp_path):
    # a chuva tem um veículo manual e nenhum automático: fora dos limites
    raiz = monta_conjunto(tmp_path / "gt", com_chuva=True)
    roteiro = um_cruzamento() * 3 + SEM_VEICULO

    resultado, caminho = executa(raiz, tmp_path, DetectorDuble(roteiro))

    chuva = resultado.clipes[-1]
    assert chuva.medicao is not None
    assert chuva.veredito.passou is False
    assert resultado.veredito.passou is True
    assert "medição fora da meta" in caminho.read_text(encoding="utf-8")


def test_video_obrigatorio_ausente_interrompe_antes_de_processar_e_nomeia_todos(tmp_path):
    raiz = monta_conjunto(tmp_path / "gt", sem_video=("fora_pico", "noturno"))
    detector = DetectorDuble(roteiro_que_acerta_tudo())

    with pytest.raises(VideosDeReferenciaAusentesError) as erro:
        executa(raiz, tmp_path, detector)

    assert [c.condicao for c in erro.value.clipes] == [Condicao.FORA_PICO, Condicao.NOTURNO]
    assert "fora_pico" in str(erro.value) and "noturno" in str(erro.value)
    assert detector.chamadas == 0
    assert not (tmp_path / "trabalho-1").exists()
    assert not (tmp_path / "dados").exists()


def test_video_obrigatorio_ilegivel_interrompe_antes_de_processar_com_clipe_e_motivo(
    tmp_path,
):
    raiz = monta_conjunto(tmp_path / "gt", video_corrompido=("noturno",))
    detector = DetectorDuble(roteiro_que_acerta_tudo())

    with pytest.raises(ClipeDeReferenciaIlegivelError) as erro:
        executa(raiz, tmp_path, detector)

    assert erro.value.condicao is Condicao.NOTURNO
    assert erro.value.motivo
    assert "noturno" in str(erro.value)
    # o pico e o fora de pico estavam bons, mas nenhum foi processado
    assert detector.chamadas == 0
    assert not (tmp_path / "trabalho-1").exists()


def test_o_video_ilegivel_continua_no_disco_depois_da_validacao(tmp_path):
    raiz = monta_conjunto(tmp_path / "gt", video_corrompido=("noturno",))
    video = raiz / "clipes" / "noturno.mp4"

    with pytest.raises(ClipeDeReferenciaIlegivelError):
        executa(raiz, tmp_path, DetectorDuble([]))

    assert video.read_bytes() == b"isto nao e um mp4"


def test_camera_do_clipe_ausente_do_registro_e_erro_citando_o_id(tmp_path):
    raiz = monta_conjunto(tmp_path / "gt")

    with pytest.raises(CameraDoClipeAusenteError) as erro:
        executar_validacao(
            raiz,
            registro=Registro(cameras=[], rejeicoes=[]),
            detector=DetectorDuble([]),
            config=ConfiguracaoDoProcessamento(amostragem=AMOSTRAGEM),
            versao_do_modelo=VERSAO_DO_MODELO,
            dir_trabalho=tmp_path / "trabalho",
            data_dir_do_relatorio=tmp_path / "dados",
            executado_em=EXECUTADO_EM,
            fabrica_de_bytetrack=ByteTrackDuble,
        )

    assert ID_CAMERA in str(erro.value)


def test_rede_bloqueada_registra_e_recusa_toda_tentativa_de_conexao():
    with rede_bloqueada() as tentativas:
        with pytest.raises(OSError):
            socket.create_connection(("localhost", 9))
        with pytest.raises(OSError):
            socket.getaddrinfo("localhost", 80)
        with pytest.raises(OSError):
            socket.socket().connect(("127.0.0.1", 9))
        with pytest.raises(OSError):
            socket.socket().connect_ex(("127.0.0.1", 9))

    assert len(tentativas) == 4

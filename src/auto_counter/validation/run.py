"""Execução da validação de acurácia de ponta a ponta (AC-014.4, AC-014.5,
AC-015.1).

Junta o conjunto de referência, a contagem automática, as métricas, o veredito
e o relatório. A validação usa apenas os clipes e as contagens manuais em disco:
este módulo não importa nem constrói cliente HTTP e não lê `.env` (AC-014.5).

A função não faz `assert` nem `pytest.fail`: traduzir o veredito em teste é
trabalho do teste de acurácia. E nunca apaga vídeo: o vídeo de referência é
insubstituível, e `capture.readable.descartar` apagaria o arquivo.
"""

import hashlib
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from auto_counter.cameras.model import Camera
from auto_counter.cameras.registry import Registro
from auto_counter.capture.readable import e_legivel
from auto_counter.counting.clip import DetectorDoClipe
from auto_counter.counting.config import ConfiguracaoDoProcessamento
from auto_counter.counting.tracking import RastreadorDoSupervision, criar_bytetrack
from auto_counter.validation.automatic import (
    ClipeDeReferenciaIlegivelError,
    contar_clipe,
)
from auto_counter.validation.ground_truth import (
    carregar_conjunto,
    ler_contagem_manual,
    videos_ausentes,
)
from auto_counter.validation.metrics import medir_clipe
from auto_counter.validation.model import (
    ClipeDeReferencia,
    ClipeMedido,
    ResultadoDaValidacao,
)
from auto_counter.validation.report import gravar_relatorio, montar_relatorio
from auto_counter.validation.verdict import veredito_do_clipe, veredito_do_conjunto


class CameraDoClipeAusenteError(LookupError):
    """O id de câmera do manifest não existe no registro de câmeras."""

    def __init__(self, id_camera: str, condicao: str) -> None:
        self.id_camera = id_camera
        super().__init__(
            f"o clipe {condicao!r} é da câmera {id_camera!r}, que não existe no "
            f"registro de câmeras; a calibração de uma câmera nunca é "
            f"reaproveitada em outra"
        )


class VideosDeReferenciaAusentesError(FileNotFoundError):
    """Faltam vídeos obrigatórios nesta máquina (SUP-044, D-10)."""

    def __init__(self, clipes: tuple[ClipeDeReferencia, ...]) -> None:
        self.clipes = clipes
        nomes = ", ".join(
            f"{c.condicao.value} ({c.caminho_video})" for c in clipes
        )
        super().__init__(f"vídeos de referência ausentes: {nomes}")


def _sha256(caminho: Path) -> str:
    resumo = hashlib.sha256()
    with caminho.open("rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(1024 * 1024), b""):
            resumo.update(bloco)
    return resumo.hexdigest()


def _camera_do_clipe(registro: Registro, clipe: ClipeDeReferencia) -> Camera:
    for camera in registro.cameras:
        if camera.id == clipe.id_camera:
            return camera
    raise CameraDoClipeAusenteError(clipe.id_camera, clipe.condicao.value)


def executar_validacao(
    raiz: Path,
    *,
    registro: Registro,
    detector: DetectorDoClipe,
    config: ConfiguracaoDoProcessamento,
    versao_do_modelo: str,
    dir_trabalho: Path,
    data_dir_do_relatorio: Path,
    executado_em: datetime,
    fabrica_de_bytetrack: Callable[[], RastreadorDoSupervision] = criar_bytetrack,
) -> tuple[ResultadoDaValidacao, Path]:
    """Roda a validação sobre o conjunto de `raiz` e grava o relatório.

    O relatório é gravado antes de devolver, passe ou não a validação (D-11).
    Vídeo obrigatório ausente ou ilegível interrompe antes de processar qualquer
    clipe; a chuva ausente ou ilegível vira "não medida" no relatório.
    """
    conjunto = carregar_conjunto(raiz)

    cameras = {clipe.condicao: _camera_do_clipe(registro, clipe) for clipe in conjunto.clipes}
    manuais = {
        clipe.condicao: ler_contagem_manual(
            clipe.caminho_csv,
            rotulos=(cameras[clipe.condicao].sentido_a, cameras[clipe.condicao].sentido_b),
        )
        for clipe in conjunto.clipes
    }

    ausentes = videos_ausentes(conjunto)
    if ausentes:
        raise VideosDeReferenciaAusentesError(ausentes)

    ilegiveis_da_chuva: dict = {}
    for clipe in conjunto.clipes:
        if not clipe.caminho_video.is_file() or e_legivel(clipe.caminho_video):
            continue
        if clipe.condicao.obrigatoria:
            raise ClipeDeReferenciaIlegivelError(
                clipe.condicao,
                f"o vídeo {clipe.caminho_video} não abre ou não tem o primeiro "
                f"e o último frame decodificáveis",
            )
        ilegiveis_da_chuva[clipe.condicao] = "vídeo ilegível"

    medidos: list[ClipeMedido] = []
    for clipe in conjunto.clipes:
        camera = cameras[clipe.condicao]
        rotulos = (camera.sentido_a, camera.sentido_b)
        sha256_csv = _sha256(clipe.caminho_csv)

        def nao_medido(motivo: str) -> ClipeMedido:
            return ClipeMedido(
                clipe=clipe,
                camera=camera,
                sha256_video=(
                    _sha256(clipe.caminho_video) if clipe.caminho_video.is_file() else None
                ),
                sha256_csv=sha256_csv,
                medicao=None,
                veredito=None,
                motivo_nao_medido=motivo,
            )

        if not clipe.condicao.obrigatoria and not clipe.caminho_video.is_file():
            medidos.append(
                nao_medido(f"vídeo ausente em {clipe.caminho_video}")
            )
            continue
        if clipe.condicao in ilegiveis_da_chuva:
            medidos.append(nao_medido(ilegiveis_da_chuva[clipe.condicao]))
            continue

        try:
            contagem = contar_clipe(
                clipe,
                camera=camera,
                detector=detector,
                config=config,
                versao_do_modelo=versao_do_modelo,
                dir_trabalho=dir_trabalho,
                fabrica_de_bytetrack=fabrica_de_bytetrack,
            )
        except ClipeDeReferenciaIlegivelError as falha:
            if clipe.condicao.obrigatoria:
                raise
            medidos.append(nao_medido(f"vídeo ilegível: {falha.motivo}"))
            continue

        medicao = medir_clipe(
            manuais[clipe.condicao], contagem.veiculos, rotulos=rotulos
        )
        medidos.append(
            ClipeMedido(
                clipe=clipe,
                camera=camera,
                sha256_video=contagem.sha256_do_video,
                sha256_csv=sha256_csv,
                medicao=medicao,
                veredito=veredito_do_clipe(clipe.condicao, medicao),
                motivo_nao_medido=None,
            )
        )

    resultado = ResultadoDaValidacao(
        clipes=tuple(medidos),
        veredito=veredito_do_conjunto(
            [m.veredito for m in medidos if m.veredito is not None]
        ),
        versao_do_modelo=versao_do_modelo,
        configuracao=config,
    )
    texto = montar_relatorio(resultado, executado_em=executado_em)
    caminho = gravar_relatorio(
        texto, data_dir=data_dir_do_relatorio, executado_em=executado_em
    )
    return resultado, caminho

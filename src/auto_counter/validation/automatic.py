"""Contagem automática de um clipe de referência (AC-014.1, AC-014.5).

Cada clipe percorre o caminho real da entrega: `processar_sessao`,
`persistir_sessao` e leitura dos eventos do banco (D-4). Tudo num diretório de
trabalho temporário: nunca no banco do usuário e nunca dentro de
`tests/ground_truth/`, de onde o vídeo é só lido e copiado.

Cada clipe é uma sessão própria de um minuto (D-6): não há emenda, rastreador,
id nem buffer compartilhado entre clipes de referência.
"""

import hashlib
import shutil
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

from auto_counter.cameras.model import Camera
from auto_counter.capture import manifest as manifest_da_captura
from auto_counter.capture.status import classificar
from auto_counter.counting.clip import DetectorDoClipe
from auto_counter.counting.config import ConfiguracaoDoProcessamento
from auto_counter.counting.session import SessaoSemClipes, processar_sessao
from auto_counter.counting.tracking import RastreadorDoSupervision, criar_bytetrack
from auto_counter.storage.connection import conectar
from auto_counter.storage.events import ler_eventos
from auto_counter.storage.persist import persistir_sessao
from auto_counter.validation.model import (
    ClipeDeReferencia,
    Condicao,
    ContagemAutomatica,
    VeiculoAutomatico,
)

_MINUTO_DO_CLIPE = 1


class ClipeDeReferenciaIlegivelError(RuntimeError):
    """O vídeo de referência não pôde ser processado (D-3).

    Erro nomeado, com a condição e o motivo, no lugar de uma exceção crua: o
    autor precisa saber qual clipe repor.
    """

    def __init__(self, condicao: Condicao, motivo: str) -> None:
        self.condicao = condicao
        self.motivo = motivo
        super().__init__(
            f"o clipe de referência {condicao.value!r} não pôde ser "
            f"processado: {motivo}"
        )


def _sha256(caminho: Path) -> str:
    resumo = hashlib.sha256()
    with caminho.open("rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(1024 * 1024), b""):
            resumo.update(bloco)
    return resumo.hexdigest()


def contar_clipe(
    clipe: ClipeDeReferencia,
    *,
    camera: Camera,
    detector: DetectorDoClipe,
    config: ConfiguracaoDoProcessamento,
    versao_do_modelo: str,
    dir_trabalho: Path,
    fabrica_de_bytetrack: Callable[[], RastreadorDoSupervision] = criar_bytetrack,
) -> ContagemAutomatica:
    """Conta um clipe de referência pelo caminho real da entrega.

    Não escolhe detector, configuração nem modelo: recebe tudo por parâmetro.
    A contagem vem da leitura dos eventos gravados no banco, não do resultado
    em memória (D-4).
    """
    if camera.id != clipe.id_camera:
        raise ValueError(
            f"o clipe {clipe.condicao.value!r} é da câmera {clipe.id_camera!r}, "
            f"mas a câmera recebida é a {camera.id!r}; a calibração de uma "
            f"câmera nunca é reaproveitada em outra"
        )

    id_sessao = manifest_da_captura.id_da_sessao(camera.id, clipe.last_modified)
    dir_sessao = manifest_da_captura.diretorio_da_sessao(dir_trabalho, id_sessao)
    dir_sessao.mkdir(parents=True, exist_ok=True)

    arquivo_do_minuto = manifest_da_captura.nome_do_arquivo_do_minuto(_MINUTO_DO_CLIPE)
    copia = dir_sessao / arquivo_do_minuto
    shutil.copyfile(clipe.caminho_video, copia)
    sha256 = _sha256(copia)

    manifest = manifest_da_captura.ManifestDaSessao.criar(
        dir_sessao,
        id_sessao=id_sessao,
        id_camera=camera.id,
        duracao_pedida=1,
        manter_videos=True,
    )
    manifest.registrar_minuto(
        _MINUTO_DO_CLIPE,
        etag=clipe.etag,
        last_modified=clipe.last_modified,
        relogio_local=clipe.last_modified,
        sha256=sha256,
    )
    manifest.fechar(classificar(1, []), duracao_real=1)

    try:
        resultado = processar_sessao(
            dir_sessao,
            camera=camera,
            detector=detector,
            config=config,
            versao_do_modelo=versao_do_modelo,
            fabrica_de_bytetrack=fabrica_de_bytetrack,
        )
    except SessaoSemClipes as falha:
        raise ClipeDeReferenciaIlegivelError(
            clipe.condicao, f"o clipe não pôde ser processado ({falha})"
        ) from falha
    for nao_processado in resultado.minutos_nao_processados:
        if nao_processado.minuto == _MINUTO_DO_CLIPE:
            raise ClipeDeReferenciaIlegivelError(
                clipe.condicao, nao_processado.motivo
            )

    with conectar(dir_trabalho) as conexao:
        persistir_sessao(conexao, dir_sessao, camera=camera)
        gravados = ler_eventos(conexao, id_sessao)

    veiculos = []
    for evento in gravados:
        deslocamento = (evento.timestamp - clipe.last_modified).total_seconds()
        if deslocamento < 0 or deslocamento != int(deslocamento):
            raise ValueError(
                f"o evento {evento.id_de_rastreio!r} tem deslocamento "
                f"{deslocamento} s desde o Last-Modified do clipe "
                f"{clipe.condicao.value!r}; o esperado é um número inteiro não "
                f"negativo, e isso indica que o Last-Modified usado no "
                f"processamento não é o do manifest de referência"
            )
        veiculos.append(
            VeiculoAutomatico(
                instante_s=Decimal(int(deslocamento)),
                categoria=evento.categoria,
                sentido=evento.sentido,
                id_de_rastreio=evento.id_de_rastreio,
            )
        )
    return ContagemAutomatica(
        veiculos=tuple(veiculos), id_sessao=id_sessao, sha256_do_video=sha256
    )

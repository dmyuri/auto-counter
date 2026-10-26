"""Leitura do conjunto de referência: `manifest.yaml` e CSVs de contagem manual.

Formato definido em SUP-044, SUP-045 e D-1 da feature `validacao-acuracia`.
Nada aqui resolve câmera nem lê o registro: os rótulos dos sentidos chegam por
parâmetro.
"""

import csv
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from auto_counter.counting.config import Categoria
from auto_counter.validation.model import (
    ClipeDeReferencia,
    Condicao,
    ConjuntoDeReferencia,
    VeiculoManual,
)

RAIZ_PADRAO = Path("tests/ground_truth")
NOME_DO_MANIFEST = "manifest.yaml"

_CABECALHO = ["instante_s", "categoria", "sentido"]
_DURACAO_DO_CLIPE_EM_SEGUNDOS = Decimal(60)


class ConjuntoDeReferenciaInvalidoError(ValueError):
    """Manifest ou CSV de referência fora do formato definido na spec."""


class _EntradaDoManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    condicao: str
    camera: str
    last_modified: datetime
    etag: str


class _Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    versao: Literal[1]
    clipes: list[_EntradaDoManifest]


def carregar_conjunto(raiz: Path = RAIZ_PADRAO) -> ConjuntoDeReferencia:
    """Lê e valida `<raiz>/manifest.yaml`.

    Não confere a existência dos vídeos: vídeo ausente não é erro de formato,
    é máquina sem os arquivos (SUP-044), e quem trata é `videos_ausentes`.
    """
    caminho = raiz / NOME_DO_MANIFEST
    try:
        bruto = yaml.safe_load(caminho.read_text(encoding="utf-8"))
    except OSError as erro:
        raise ConjuntoDeReferenciaInvalidoError(
            f"{caminho}: não foi possível ler o manifest ({erro})"
        ) from erro
    except yaml.YAMLError as erro:
        raise ConjuntoDeReferenciaInvalidoError(
            f"{caminho}: YAML inválido ({erro})"
        ) from erro

    try:
        manifest = _Manifest.model_validate(bruto)
    except ValidationError as erro:
        raise ConjuntoDeReferenciaInvalidoError(
            f"{caminho}: manifest inválido (a versão aceita é 1):\n{erro}"
        ) from erro

    por_condicao: dict[Condicao, ClipeDeReferencia] = {}
    for entrada in manifest.clipes:
        try:
            condicao = Condicao(entrada.condicao)
        except ValueError:
            validas = ", ".join(c.value for c in Condicao)
            raise ConjuntoDeReferenciaInvalidoError(
                f"{caminho}: condição {entrada.condicao!r} desconhecida; "
                f"as válidas são {validas}"
            ) from None
        if condicao in por_condicao:
            raise ConjuntoDeReferenciaInvalidoError(
                f"{caminho}: condição {condicao.value!r} repetida"
            )
        if entrada.last_modified.tzinfo is None:
            raise ConjuntoDeReferenciaInvalidoError(
                f"{caminho}: last_modified de {condicao.value!r} sem fuso horário "
                f"({entrada.last_modified.isoformat()}); grave com fuso explícito, "
                f"como em +00:00"
            )
        por_condicao[condicao] = ClipeDeReferencia(
            condicao=condicao,
            id_camera=entrada.camera,
            last_modified=entrada.last_modified.astimezone(timezone.utc),
            etag=entrada.etag,
            caminho_csv=raiz / f"{condicao.value}.csv",
            caminho_video=raiz / "clipes" / f"{condicao.value}.mp4",
        )

    faltando = [c.value for c in Condicao if c.obrigatoria and c not in por_condicao]
    if faltando:
        raise ConjuntoDeReferenciaInvalidoError(
            f"{caminho}: condição obrigatória ausente: {', '.join(faltando)}"
        )

    clipes = tuple(por_condicao[c] for c in Condicao if c in por_condicao)
    for clipe in clipes:
        if not clipe.caminho_csv.is_file():
            raise ConjuntoDeReferenciaInvalidoError(
                f"{caminho}: o clipe {clipe.condicao.value!r} está listado, mas o "
                f"CSV de contagem manual não existe em {clipe.caminho_csv}"
            )
    return ConjuntoDeReferencia(raiz=raiz, clipes=clipes)


def ler_contagem_manual(
    caminho_csv: Path, *, rotulos: tuple[str, str]
) -> tuple[VeiculoManual, ...]:
    """Lê o CSV de contagem manual no formato de D-1."""
    try:
        with caminho_csv.open(encoding="utf-8-sig", newline="") as arquivo:
            linhas = list(csv.reader(arquivo))
    except OSError as erro:
        raise ConjuntoDeReferenciaInvalidoError(
            f"{caminho_csv}: não foi possível ler o CSV ({erro})"
        ) from erro

    def recusar(numero: int, motivo: str) -> ConjuntoDeReferenciaInvalidoError:
        return ConjuntoDeReferenciaInvalidoError(
            f"{caminho_csv}, linha {numero}: {motivo}"
        )

    if not linhas:
        raise recusar(
            1, "arquivo vazio; o cabeçalho esperado é instante_s,categoria,sentido"
        )
    if linhas[0] != _CABECALHO:
        if any(";" in campo for campo in linhas[0]):
            raise recusar(
                1,
                "o arquivo parece salvo pelo Excel em pt-BR; salve com vírgula "
                "como separador e ponto decimal",
            )
        raise recusar(
            1,
            f"cabeçalho {','.join(linhas[0])!r} diferente do esperado "
            f"'instante_s,categoria,sentido'",
        )

    veiculos: list[VeiculoManual] = []
    for numero, campos in enumerate(linhas[1:], start=2):
        if len(campos) != 3:
            raise recusar(numero, f"esperadas 3 colunas, encontradas {len(campos)}")
        texto_instante, texto_categoria, sentido = campos

        try:
            instante = Decimal(texto_instante)
        except InvalidOperation:
            raise recusar(
                numero, f"instante {texto_instante!r} não é um decimal"
            ) from None
        if not instante.is_finite():
            raise recusar(numero, f"instante {texto_instante!r} não é finito")
        if instante < 0 or instante >= _DURACAO_DO_CLIPE_EM_SEGUNDOS:
            raise recusar(
                numero,
                f"instante {texto_instante!r} fora do intervalo [0, 60) s do clipe",
            )

        try:
            categoria = Categoria(texto_categoria)
        except ValueError:
            validas = ", ".join(c.value for c in Categoria)
            raise recusar(
                numero,
                f"categoria {texto_categoria!r} desconhecida; as válidas são {validas}",
            ) from None

        if sentido not in rotulos:
            raise recusar(
                numero,
                f"sentido {sentido!r} fora dos rótulos da câmera; os esperados "
                f"são {rotulos[0]!r} e {rotulos[1]!r}",
            )

        veiculos.append(
            VeiculoManual(
                linha=numero, instante_s=instante, categoria=categoria, sentido=sentido
            )
        )
    return tuple(veiculos)


def videos_ausentes(conjunto: ConjuntoDeReferencia) -> tuple[ClipeDeReferencia, ...]:
    """Clipes obrigatórios cujo vídeo não existe. Chuva nunca entra (D-10)."""
    return tuple(
        clipe
        for clipe in conjunto.clipes
        if clipe.condicao.obrigatoria and not clipe.caminho_video.is_file()
    )

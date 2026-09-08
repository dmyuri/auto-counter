"""O evento e o `eventos.json` da sessão — T-07.

Critérios cobertos, de `.spec/features/contagem-veiculos/spec.md`:

- AC-006.1 — na parte de **durabilidade**: o evento registrado carrega
  timestamp, categoria, sentido e id de rastreio. Quem decide *quando* um
  cruzamento vira evento é T-09; aqui prova-se que, uma vez registrado, ele
  chega ao disco com os quatro campos e volta de lá igual.

Alimenta AC-008.1 e AC-008.2 de `persistencia-resultados`: a configuração
efetivamente usada — limiar (SUP-016), amostragem (SUP-017) e versão do modelo
(SUP-027) — fica gravada junto dos eventos, e a distinção entre minuto sem
veículo e minuto sem vídeo (AC-008.4, D-4) sai das duas listas de minutos.

Implementa D-1 (o arquivo é `eventos.json`, no diretório da sessão, ao lado do
`manifest.json`) e D-9 (o id de rastreio é `<minuto>:<id do ByteTrack>`).

Timestamps em ISO 8601 UTC com fuso explícito (SUP-030), como
`capture/manifest.py` já faz.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from auto_counter.counting.config import Categoria, ConfiguracaoDoProcessamento
from auto_counter.counting.events import (
    Evento,
    MinutoNaoProcessado,
    RegistroDeEventos,
    id_de_rastreio_composto,
    ler,
)

INICIO = datetime(2026, 3, 4, 12, 30, 0, tzinfo=timezone.utc)
VERSAO_DO_MODELO = "yolo11n.onnx@0123456789ab"


def evento(
    *,
    segundos: int = 0,
    categoria: Categoria = Categoria.CARRO,
    sentido: str = "CENTRO",
    minuto: int = 1,
    id_bytetrack: int = 17,
    confianca: float = 0.87,
    indice_do_frame: int = 900,
    posicao_na_linha: float = 0.42,
) -> Evento:
    """Um evento plausível, para que cada teste destaque só o que muda nele."""
    return Evento(
        timestamp=INICIO + timedelta(seconds=segundos),
        categoria=categoria,
        sentido=sentido,
        id_de_rastreio=id_de_rastreio_composto(minuto, id_bytetrack),
        confianca=confianca,
        minuto=minuto,
        indice_do_frame=indice_do_frame,
        posicao_na_linha=posicao_na_linha,
    )


def registro(**alteracoes) -> RegistroDeEventos:
    """Registro completo de uma sessão curta, com os campos que D-1 exige."""
    campos = {
        "id_sessao": "000013-20260304T123000Z",
        "id_camera": "000013",
        "configuracao": ConfiguracaoDoProcessamento(),
        "versao_do_modelo": VERSAO_DO_MODELO,
        "minutos_processados": (1, 2),
        "minutos_nao_processados": (),
        "eventos": (evento(),),
    }
    campos.update(alteracoes)
    return RegistroDeEventos(**campos)


def test_AC_006_1_evento_gravado_carrega_timestamp_categoria_sentido_e_id_de_rastreio(
    tmp_path,
):
    """Os quatro campos que AC-006.1 exige chegam ao disco e voltam de lá.

    O id de rastreio é o composto de D-9 (`<minuto>:<id do ByteTrack>`), que é
    o que torna o id único na sessão sem inventar continuidade entre clipes
    (AC-007.3).
    """
    registro(eventos=(evento(segundos=30, sentido="CENTRO", minuto=3),)).gravar(
        tmp_path
    )

    gravado = json.loads((tmp_path / "eventos.json").read_text(encoding="utf-8"))
    [primeiro] = gravado["eventos"]

    assert primeiro["timestamp"] == (INICIO + timedelta(seconds=30)).isoformat()
    assert primeiro["categoria"] == Categoria.CARRO.value
    assert primeiro["sentido"] == "CENTRO"
    assert primeiro["id_de_rastreio"] == "3:17"


def test_eventos_json_registra_limiar_amostragem_e_versao_do_modelo_usados(tmp_path):
    """AC-008.1 exige a configuração **usada** registrada na sessão.

    Não os padrões de SUP-016 e SUP-017: os valores aplicados naquela execução.
    """
    configuracao = ConfiguracaoDoProcessamento(limiar_de_confianca=0.5, amostragem=2)
    registro(configuracao=configuracao).gravar(tmp_path)

    gravado = json.loads((tmp_path / "eventos.json").read_text(encoding="utf-8"))

    assert gravado["configuracao"]["limiar_de_confianca"] == 0.5
    assert gravado["configuracao"]["amostragem"] == 2
    assert gravado["configuracao"]["versao_do_modelo"] == VERSAO_DO_MODELO


def test_eventos_json_distingue_minuto_processado_de_minuto_sem_video(tmp_path):
    """AC-008.4 depende dessa distinção; D-4 dá o motivo de cada não processado.

    Minuto sem veículo é minuto processado com zero eventos; minuto sem vídeo é
    minuto que nem chegou a ser analisado, e o motivo fica gravado com ele.
    """
    lido = ler(
        registro(
            minutos_processados=(1, 3),
            minutos_nao_processados=(
                MinutoNaoProcessado(minuto=2, motivo="clipe ilegível"),
            ),
            eventos=(),
        )
        .gravar(tmp_path)
        .parent
    )

    assert lido.minutos_processados == (1, 3)
    assert lido.minutos_nao_processados == (
        MinutoNaoProcessado(minuto=2, motivo="clipe ilegível"),
    )
    assert lido.eventos == ()


def test_eventos_json_sobrevive_a_ida_e_volta_de_escrita_e_leitura(tmp_path):
    """T-12 relê o que já foi gravado: a volta precisa ser fiel ao que foi."""
    original = registro(
        eventos=(
            evento(segundos=10, categoria=Categoria.MOTO, sentido="CENTRO", minuto=1),
            evento(
                segundos=70,
                categoria=Categoria.CAMINHAO,
                sentido="BAIRRO",
                minuto=2,
                id_bytetrack=4,
                confianca=0.61,
                indice_do_frame=300,
                posicao_na_linha=0.9,
            ),
        )
    )

    lido = ler(original.gravar(tmp_path).parent)

    assert lido.id_sessao == original.id_sessao
    assert lido.id_camera == original.id_camera
    assert lido.configuracao == original.configuracao
    assert lido.versao_do_modelo == original.versao_do_modelo
    assert lido.minutos_processados == original.minutos_processados
    assert lido.eventos == original.eventos


def test_eventos_json_fica_ao_lado_do_manifest_no_diretorio_da_sessao(tmp_path):
    """D-1: o arquivo é `eventos.json`, no diretório da sessão."""
    caminho = registro().gravar(tmp_path)
    assert caminho == tmp_path / "eventos.json"


def test_eventos_json_grava_a_versao_do_formato(tmp_path):
    """Sem número de versão, formato novo é indistinguível de arquivo corrompido."""
    registro().gravar(tmp_path)
    gravado = json.loads((tmp_path / "eventos.json").read_text(encoding="utf-8"))
    assert gravado["versao"] >= 1


def test_eventos_sao_gravados_em_ordem_de_timestamp(tmp_path):
    """D-1 pede a lista em ordem de timestamp, venha ela ordenada ou não."""
    registro(
        eventos=(
            evento(segundos=90, minuto=2, id_bytetrack=4),
            evento(segundos=5, minuto=1, id_bytetrack=17),
        )
    ).gravar(tmp_path)

    gravado = json.loads((tmp_path / "eventos.json").read_text(encoding="utf-8"))
    carimbos = [item["timestamp"] for item in gravado["eventos"]]
    assert carimbos == sorted(carimbos)


def test_evento_recusa_timestamp_ingenuo():
    """SUP-030 exige fuso explícito; um datetime ingênuo não diz qual é o dele."""
    with pytest.raises(ValueError):
        evento(segundos=0).__class__(
            timestamp=INICIO.replace(tzinfo=None),
            categoria=Categoria.CARRO,
            sentido="CENTRO",
            id_de_rastreio="1:17",
            confianca=0.9,
            minuto=1,
            indice_do_frame=0,
            posicao_na_linha=0.5,
        )


def test_gravacao_e_atomica_e_nao_deixa_temporario_para_tras(tmp_path):
    """Mesmo padrão de `capture/manifest.py`: temporário no diretório e replace."""
    registro().gravar(tmp_path)
    registro().gravar(tmp_path)
    assert sorted(item.name for item in tmp_path.iterdir()) == ["eventos.json"]

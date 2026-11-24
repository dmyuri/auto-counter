"""Gravação dos eventos de cruzamento — T-05.

Comportamento em `.spec/features/persistencia-resultados/spec.md`: AC-008.2.

Os objetos gravados são os `Evento` de `counting.events` — os mesmos que
`counting.events.ler` devolve de um `eventos.json` real. Nenhum teste aqui
redefine o evento: a construção usa a classe de verdade, e a normalização de
fuso (UTC) e a validação de confiança/posição já são dela.

Nenhum teste grava banco dentro do repositório: tudo acontece em `tmp_path`.
"""

from datetime import datetime, timedelta, timezone

import pytest

from auto_counter.counting.config import Categoria
from auto_counter.counting.events import Evento
from auto_counter.storage.connection import conectar
from auto_counter.storage.events import contar_eventos, gravar_eventos, ler_eventos
from auto_counter.storage.model import EventoGravado
from auto_counter.storage.sessions import SessaoInexistenteError, abrir_sessao

ID_CAMERA = "000013"
CRIADA_EM = datetime(2026, 1, 1, 8, 0, 0, tzinfo=timezone.utc)


def _abrir(conexao, id_sessao: str) -> None:
    abrir_sessao(
        conexao,
        id_sessao=id_sessao,
        id_camera=ID_CAMERA,
        criada_em=CRIADA_EM,
        duracao_pedida=5,
        sentido_a="Icaraí",
        sentido_b="Centro",
    )


def _evento(
    *,
    id_de_rastreio: str = "1:1",
    sentido: str = "Icaraí",
    categoria: Categoria = Categoria.CARRO,
    confianca: float = 0.9,
    minuto: int = 1,
    timestamp: datetime = datetime(2026, 1, 1, 8, 0, 30, tzinfo=timezone.utc),
) -> Evento:
    return Evento(
        timestamp=timestamp,
        categoria=categoria,
        sentido=sentido,
        id_de_rastreio=id_de_rastreio,
        confianca=confianca,
        minuto=minuto,
        indice_do_frame=42,
        posicao_na_linha=0.5,
    )


def test_AC_008_2_cada_evento_fica_ligado_ao_id_da_sessao(tmp_path):
    with conectar(tmp_path) as conexao:
        _abrir(conexao, "s1")
        _abrir(conexao, "s2")

        gravar_eventos(
            conexao,
            "s1",
            [
                _evento(id_de_rastreio="1:1", sentido="Icaraí"),
                _evento(id_de_rastreio="1:2", sentido="Centro"),
            ],
        )
        conexao.commit()

        assert contar_eventos(conexao, "s1") == 2
        assert contar_eventos(conexao, "s2") == 0

        linhas = conexao.execute(
            "SELECT id_sessao FROM evento WHERE id_sessao = ?", ("s1",)
        ).fetchall()
    assert {linha["id_sessao"] for linha in linhas} == {"s1"}


def test_AC_008_2_o_evento_guarda_timestamp_categoria_sentido_rastreio_e_confianca(
    tmp_path,
):
    instante = datetime(2026, 1, 1, 8, 3, 15, tzinfo=timezone.utc)
    evento = _evento(
        id_de_rastreio="3:7",
        sentido="Centro",
        categoria=Categoria.CAMINHAO,
        confianca=0.81,
        minuto=3,
        timestamp=instante,
    )

    with conectar(tmp_path) as conexao:
        _abrir(conexao, "s1")
        gravar_eventos(conexao, "s1", [evento])
        conexao.commit()

        linha = conexao.execute(
            "SELECT * FROM evento WHERE id_sessao = ? AND id_de_rastreio = ?",
            ("s1", "3:7"),
        ).fetchone()

    assert linha["sentido"] == "Centro"
    assert linha["categoria"] == "CAMINHAO"
    assert linha["confianca"] == 0.81
    assert linha["minuto"] == 3
    assert datetime.fromisoformat(linha["timestamp"]) == instante


def test_AC_008_2_o_timestamp_do_evento_e_gravado_em_utc(tmp_path):
    """Um timestamp com fuso não-UTC chega já normalizado por `Evento`
    (SUP-030); a gravação preserva essa normalização."""
    fuso_menos_tres = timezone(timedelta(hours=-3))
    instante_local = datetime(2026, 1, 1, 5, 0, 30, tzinfo=fuso_menos_tres)
    evento = _evento(timestamp=instante_local)

    assert evento.timestamp == datetime(2026, 1, 1, 8, 0, 30, tzinfo=timezone.utc)

    with conectar(tmp_path) as conexao:
        _abrir(conexao, "s1")
        gravar_eventos(conexao, "s1", [evento])
        conexao.commit()

        (bruto,) = conexao.execute(
            "SELECT timestamp FROM evento WHERE id_sessao = ?", ("s1",)
        ).fetchone()

    gravado = datetime.fromisoformat(bruto)
    assert gravado.utcoffset() == timedelta(0)
    assert gravado == datetime(2026, 1, 1, 8, 0, 30, tzinfo=timezone.utc)


def test_evento_de_sessao_inexistente_e_recusado_com_mensagem_citando_o_id(tmp_path):
    with conectar(tmp_path) as conexao:
        with pytest.raises(SessaoInexistenteError, match="sessao-inexistente"):
            gravar_eventos(conexao, "sessao-inexistente", [_evento()])


def test_gravar_a_mesma_lista_de_eventos_duas_vezes_nao_duplica(tmp_path):
    """Base de AC-008.5 no nível do evento: `ON CONFLICT ... DO UPDATE`."""
    eventos = [
        _evento(id_de_rastreio="1:1", sentido="Icaraí"),
        _evento(id_de_rastreio="1:2", sentido="Centro"),
    ]

    with conectar(tmp_path) as conexao:
        _abrir(conexao, "s1")
        gravar_eventos(conexao, "s1", eventos)
        gravar_eventos(conexao, "s1", eventos)
        conexao.commit()

        assert contar_eventos(conexao, "s1") == 2


def test_gravar_lista_vazia_de_eventos_nao_falha(tmp_path):
    with conectar(tmp_path) as conexao:
        _abrir(conexao, "s1")
        gravar_eventos(conexao, "s1", [])
        conexao.commit()

        assert contar_eventos(conexao, "s1") == 0


def test_contar_eventos_de_sessao_sem_nenhum_evento_e_zero(tmp_path):
    with conectar(tmp_path) as conexao:
        _abrir(conexao, "s1")
        assert contar_eventos(conexao, "s1") == 0


def test_ler_eventos_devolve_o_que_foi_gravado_com_fuso_e_categoria_do_enum(tmp_path):
    instante = datetime(2026, 1, 1, 8, 0, 30, tzinfo=timezone.utc)
    with conectar(tmp_path) as conexao:
        _abrir(conexao, "s1")
        gravar_eventos(
            conexao,
            "s1",
            [
                _evento(
                    id_de_rastreio="1:7",
                    sentido="Centro",
                    categoria=Categoria.ONIBUS,
                    confianca=0.75,
                    minuto=3,
                    timestamp=instante,
                )
            ],
        )
        conexao.commit()

        lidos = ler_eventos(conexao, "s1")

    assert lidos == (
        EventoGravado(
            id_de_rastreio="1:7",
            sentido="Centro",
            timestamp=instante,
            categoria=Categoria.ONIBUS,
            confianca=0.75,
            minuto=3,
        ),
    )
    assert lidos[0].timestamp.utcoffset() == timedelta(0)
    assert isinstance(lidos[0].categoria, Categoria)


def test_ler_eventos_vem_em_ordem_de_timestamp_e_rastreio(tmp_path):
    base = datetime(2026, 1, 1, 8, 0, 0, tzinfo=timezone.utc)
    with conectar(tmp_path) as conexao:
        _abrir(conexao, "s1")
        gravar_eventos(
            conexao,
            "s1",
            [
                _evento(id_de_rastreio="1:9", timestamp=base + timedelta(seconds=30)),
                _evento(id_de_rastreio="1:3", sentido="Centro", timestamp=base + timedelta(seconds=10)),
                _evento(id_de_rastreio="1:2", sentido="Icaraí", timestamp=base + timedelta(seconds=10)),
                _evento(id_de_rastreio="1:2", sentido="Centro", timestamp=base + timedelta(seconds=10)),
            ],
        )
        conexao.commit()

        lidos = ler_eventos(conexao, "s1")

    assert [(e.id_de_rastreio, e.sentido) for e in lidos] == [
        ("1:2", "Centro"),
        ("1:2", "Icaraí"),
        ("1:3", "Centro"),
        ("1:9", "Icaraí"),
    ]


def test_ler_eventos_de_sessao_inexistente_erra_citando_o_id(tmp_path):
    with conectar(tmp_path) as conexao:
        with pytest.raises(SessaoInexistenteError) as erro:
            ler_eventos(conexao, "nao-existe")

    assert "nao-existe" in str(erro.value)


def test_ler_eventos_de_sessao_sem_evento_devolve_tupla_vazia(tmp_path):
    with conectar(tmp_path) as conexao:
        _abrir(conexao, "s1")

        assert ler_eventos(conexao, "s1") == ()


# --- processamento-upload: vídeo e deslocamento do evento (SUP-100) ---


def test_SUP_100_evento_de_upload_ida_e_volta_com_video_e_deslocamento(tmp_path):
    evento = Evento(
        timestamp=datetime(2026, 1, 1, 8, 2, 12, tzinfo=timezone.utc),
        categoria=Categoria.CARRO,
        sentido="Icaraí",
        id_de_rastreio="3:9",
        confianca=0.8,
        minuto=3,
        indice_do_frame=120,
        posicao_na_linha=0.5,
        video=2,
        deslocamento_segundos=12,
    )
    with conectar(tmp_path) as conexao:
        _abrir(conexao, "s1")
        gravar_eventos(conexao, "s1", [evento])

        [lido] = ler_eventos(conexao, "s1")

    assert (lido.video, lido.deslocamento) == (2, 12)


def test_evento_ao_vivo_continua_com_video_e_deslocamento_nulos(tmp_path):
    with conectar(tmp_path) as conexao:
        _abrir(conexao, "s1")
        gravar_eventos(conexao, "s1", [_evento()])

        [lido] = ler_eventos(conexao, "s1")

    assert lido.video is None
    assert lido.deslocamento is None

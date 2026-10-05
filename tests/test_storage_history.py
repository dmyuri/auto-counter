"""Consulta do histórico de sessões — T-09.

Comportamento em `.spec/features/persistencia-resultados/spec.md`: AC-009.1
e AC-009.2.

Nenhum teste aqui toca disco de vídeo ou rede: `listar_sessoes` lê só o
banco, e é isso que faz uma sessão cujos clipes já foram apagados continuar
listada.
"""

import shutil
from datetime import datetime, timedelta, timezone

from auto_counter.capture.status import StatusDaSessao
from auto_counter.counting.config import Categoria
from auto_counter.counting.events import Evento
from auto_counter.storage.connection import conectar
from auto_counter.storage.events import gravar_eventos
from auto_counter.storage.sessions import abrir_sessao, fechar_captura, listar_sessoes

ID_CAMERA = "000013"
SENTIDO_A = "Icaraí"
SENTIDO_B = "Centro"


def _abrir_e_fechar(
    conexao,
    id_sessao: str,
    *,
    criada_em: datetime,
    inicio: datetime | None = None,
    fim: datetime | None = None,
    duracao_real: int = 1,
    status: StatusDaSessao = StatusDaSessao.COMPLETA,
    minutos_perdidos: tuple[int, ...] = (),
) -> None:
    abrir_sessao(
        conexao,
        id_sessao=id_sessao,
        id_camera=ID_CAMERA,
        criada_em=criada_em,
        duracao_pedida=duracao_real,
        sentido_a=SENTIDO_A,
        sentido_b=SENTIDO_B,
    )
    fechar_captura(
        conexao,
        id_sessao,
        inicio=inicio,
        fim=fim,
        duracao_real=duracao_real,
        encerrada_pelo_usuario=False,
        status=status,
        minutos_perdidos=minutos_perdidos,
    )


def _evento(id_de_rastreio: str) -> Evento:
    return Evento(
        timestamp=datetime(2026, 1, 1, 8, 0, 30, tzinfo=timezone.utc),
        categoria=Categoria.CARRO,
        sentido=SENTIDO_A,
        id_de_rastreio=id_de_rastreio,
        confianca=0.9,
        minuto=1,
        indice_do_frame=0,
        posicao_na_linha=0.5,
    )


def test_AC_009_1_sessao_com_os_videos_apagados_continua_listada(tmp_path):
    dir_sessao = tmp_path / "sessions" / "000013-20260101T080000Z"
    dir_sessao.mkdir(parents=True)
    (dir_sessao / "minuto-01.mp4").write_bytes(b"video de mentira")

    with conectar(tmp_path) as conexao:
        _abrir_e_fechar(
            conexao,
            "000013-20260101T080000Z",
            criada_em=datetime(2026, 1, 1, 8, 0, 0, tzinfo=timezone.utc),
        )
        conexao.commit()

        # Apaga o diretório inteiro da sessão — a consulta não deveria nem
        # saber que ele existia.
        shutil.rmtree(dir_sessao)
        assert not dir_sessao.exists()

        historico = listar_sessoes(conexao)

    assert [item.id_sessao for item in historico] == ["000013-20260101T080000Z"]


def test_AC_009_1_a_sessao_listada_traz_camera_periodo_status_e_totais(tmp_path):
    inicio = datetime(2026, 1, 1, 8, 0, 3, tzinfo=timezone.utc)
    fim = datetime(2026, 1, 1, 8, 1, 58, tzinfo=timezone.utc)

    with conectar(tmp_path) as conexao:
        _abrir_e_fechar(
            conexao,
            "s1",
            criada_em=datetime(2026, 1, 1, 8, 0, 0, tzinfo=timezone.utc),
            inicio=inicio,
            fim=fim,
            duracao_real=2,
            status=StatusDaSessao.DEGRADADA,
        )
        gravar_eventos(conexao, "s1", [_evento("1:1"), _evento("1:2")])
        conexao.commit()

        (item,) = listar_sessoes(conexao)

    assert item.id_sessao == "s1"
    assert item.id_camera == ID_CAMERA
    assert item.inicio == inicio
    assert item.fim == fim
    assert item.status is StatusDaSessao.DEGRADADA
    assert item.total_de_eventos == 2


def test_AC_009_2_o_historico_vem_da_mais_recente_para_a_mais_antiga(tmp_path):
    base = datetime(2026, 1, 1, 8, 0, 0, tzinfo=timezone.utc)

    with conectar(tmp_path) as conexao:
        # Gravadas fora de ordem de propósito: a consulta ordena, não a
        # ordem de inserção.
        _abrir_e_fechar(conexao, "meio", criada_em=base + timedelta(minutes=5))
        _abrir_e_fechar(conexao, "mais_antiga", criada_em=base)
        _abrir_e_fechar(conexao, "mais_recente", criada_em=base + timedelta(minutes=10))
        conexao.commit()

        historico = listar_sessoes(conexao)

    assert [item.id_sessao for item in historico] == [
        "mais_recente",
        "meio",
        "mais_antiga",
    ]


def test_AC_009_2_sessao_sem_nenhum_evento_aparece_com_total_zero(tmp_path):
    with conectar(tmp_path) as conexao:
        _abrir_e_fechar(
            conexao, "s1", criada_em=datetime(2026, 1, 1, 8, 0, 0, tzinfo=timezone.utc)
        )
        conexao.commit()

        (item,) = listar_sessoes(conexao)

    assert item.id_sessao == "s1"
    assert item.total_de_eventos == 0


def test_sessao_ainda_em_captura_aparece_com_status_nulo(tmp_path):
    with conectar(tmp_path) as conexao:
        abrir_sessao(
            conexao,
            id_sessao="s1",
            id_camera=ID_CAMERA,
            criada_em=datetime(2026, 1, 1, 8, 0, 0, tzinfo=timezone.utc),
            duracao_pedida=5,
            sentido_a=SENTIDO_A,
            sentido_b=SENTIDO_B,
        )

        (item,) = listar_sessoes(conexao)

    assert item.status is None
    assert item.inicio is None
    assert item.fim is None


def test_listar_sessoes_respeita_o_limite(tmp_path):
    base = datetime(2026, 1, 1, 8, 0, 0, tzinfo=timezone.utc)

    with conectar(tmp_path) as conexao:
        for indice in range(3):
            _abrir_e_fechar(
                conexao, f"s{indice}", criada_em=base + timedelta(minutes=indice)
            )
        conexao.commit()

        historico = listar_sessoes(conexao, limite=2)

    assert len(historico) == 2
    assert [item.id_sessao for item in historico] == ["s2", "s1"]


def test_listar_sessoes_sem_nenhuma_sessao_devolve_tupla_vazia(tmp_path):
    with conectar(tmp_path) as conexao:
        assert listar_sessoes(conexao) == ()

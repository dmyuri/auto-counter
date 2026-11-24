"""Agregados por minuto: contagem, zero e sem dado — T-06.

Comportamento em `.spec/features/persistencia-resultados/spec.md`: AC-008.3 e
AC-008.4.

`agregar` é função pura — nenhum teste aqui toca banco. A gravação
(`gravar_agregados`/`ler_agregados`) é testada à parte, contra um banco em
`tmp_path`.
"""

from datetime import datetime, timezone

import pytest

from auto_counter.counting.config import Categoria
from auto_counter.counting.events import Evento, MinutoNaoProcessado
from auto_counter.storage.connection import conectar
from auto_counter.storage.minutes import (
    SentidoDesconhecidoError,
    agregar,
    gravar_agregados,
    ler_agregados,
)
from auto_counter.storage.model import EstadoDoMinuto
from auto_counter.storage.sessions import SessaoInexistenteError, abrir_sessao

SENTIDO_A = "Icaraí"
SENTIDO_B = "Centro"


def _evento(
    *,
    minuto: int,
    sentido: str = SENTIDO_A,
    categoria: Categoria = Categoria.CARRO,
    id_de_rastreio: str = "1:1",
) -> Evento:
    return Evento(
        timestamp=datetime(2026, 1, 1, 8, minuto, 0, tzinfo=timezone.utc),
        categoria=categoria,
        sentido=sentido,
        id_de_rastreio=id_de_rastreio,
        confianca=0.9,
        minuto=minuto,
        indice_do_frame=0,
        posicao_na_linha=0.5,
    )


def _agregar(eventos, **kwargs):
    base = dict(
        duracao_real=5,
        minutos_processados=(1, 2, 3, 4, 5),
        minutos_nao_processados=(),
        sentido_a=SENTIDO_A,
        sentido_b=SENTIDO_B,
    )
    base.update(kwargs)
    return agregar(eventos, **base)


def test_AC_008_3_existe_uma_linha_para_cada_minuto_da_sessao():
    agregados = _agregar([])
    assert tuple(item.minuto for item in agregados) == (1, 2, 3, 4, 5)


def test_AC_008_3_minuto_capturado_sem_nenhum_cruzamento_aparece_com_zero():
    (agregado,) = _agregar([], duracao_real=1, minutos_processados=(1,))

    assert agregado.estado is EstadoDoMinuto.CAPTURADO
    assert agregado.sentido_a_carro == 0
    assert agregado.sentido_a_moto == 0
    assert agregado.sentido_a_onibus == 0
    assert agregado.sentido_a_caminhao == 0
    assert agregado.sentido_b_carro == 0
    assert agregado.sentido_b_moto == 0
    assert agregado.sentido_b_onibus == 0
    assert agregado.sentido_b_caminhao == 0


def test_AC_008_3_a_contagem_do_minuto_e_quebrada_por_sentido_e_por_categoria():
    eventos = [
        _evento(minuto=1, sentido=SENTIDO_A, categoria=Categoria.CARRO, id_de_rastreio="1:1"),
        _evento(minuto=1, sentido=SENTIDO_A, categoria=Categoria.CARRO, id_de_rastreio="1:2"),
        _evento(minuto=1, sentido=SENTIDO_A, categoria=Categoria.MOTO, id_de_rastreio="1:3"),
        _evento(minuto=1, sentido=SENTIDO_B, categoria=Categoria.CAMINHAO, id_de_rastreio="1:4"),
    ]

    (agregado,) = _agregar(eventos, duracao_real=1, minutos_processados=(1,))

    assert agregado.sentido_a_carro == 2
    assert agregado.sentido_a_moto == 1
    assert agregado.sentido_a_onibus == 0
    assert agregado.sentido_a_caminhao == 0
    assert agregado.sentido_b_carro == 0
    assert agregado.sentido_b_moto == 0
    assert agregado.sentido_b_onibus == 0
    assert agregado.sentido_b_caminhao == 1


def test_AC_008_4_minuto_perdido_na_captura_fica_marcado_como_sem_dado():
    agregados = _agregar(
        [],
        duracao_real=3,
        minutos_processados=(1, 3),
        minutos_nao_processados=(
            MinutoNaoProcessado(minuto=2, motivo="minuto perdido na captura: etag parado"),
        ),
    )

    agregado_2 = agregados[1]
    assert agregado_2.minuto == 2
    assert agregado_2.estado is EstadoDoMinuto.SEM_DADO
    assert agregado_2.motivo == "minuto perdido na captura: etag parado"
    assert agregado_2.sentido_a_carro is None
    assert agregado_2.sentido_b_caminhao is None


def test_AC_008_4_minuto_sem_dado_e_distinguivel_de_minuto_com_contagem_zero():
    agregados = _agregar(
        [],
        duracao_real=2,
        minutos_processados=(1,),
        minutos_nao_processados=(
            MinutoNaoProcessado(minuto=2, motivo="clipe ilegível"),
        ),
    )

    capturado, sem_dado = agregados
    assert capturado.estado is EstadoDoMinuto.CAPTURADO
    assert capturado.sentido_a_carro == 0  # contagem zero, não ausência

    assert sem_dado.estado is EstadoDoMinuto.SEM_DADO
    assert sem_dado.sentido_a_carro is None  # nulo, não zero

    assert capturado.sentido_a_carro != sem_dado.sentido_a_carro


def test_AC_008_4_minuto_capturado_mas_nao_processado_tambem_e_sem_dado():
    """Minuto que virou clipe (capturado) mas falhou no processamento é
    `SEM_DADO`, com o motivo próprio do processamento — não é confundido com
    "minuto perdido na captura"."""
    agregados = _agregar(
        [],
        duracao_real=1,
        minutos_processados=(),
        minutos_nao_processados=(
            MinutoNaoProcessado(minuto=1, motivo="clipe ilegível: arquivo corrompido"),
        ),
    )

    (agregado,) = agregados
    assert agregado.estado is EstadoDoMinuto.SEM_DADO
    assert agregado.motivo == "clipe ilegível: arquivo corrompido"
    assert "perdido na captura" not in agregado.motivo


def test_minuto_sem_dado_sem_motivo_correspondente_recebe_texto_padrao():
    """Nenhum dos dois conjuntos cita o minuto: nunca motivo vazio."""
    agregados = _agregar(
        [], duracao_real=1, minutos_processados=(), minutos_nao_processados=()
    )

    (agregado,) = agregados
    assert agregado.estado is EstadoDoMinuto.SEM_DADO
    assert agregado.motivo  # não vazio e não nulo
    assert "não aparece" in agregado.motivo or "nao aparece" in agregado.motivo


def test_sentido_fora_dos_dois_rotulos_da_camera_e_erro_explicito():
    eventos = [_evento(minuto=1, sentido="Outro Bairro")]

    with pytest.raises(SentidoDesconhecidoError) as excinfo:
        _agregar(eventos, duracao_real=1, minutos_processados=(1,))

    mensagem = str(excinfo.value)
    assert "Outro Bairro" in mensagem
    assert SENTIDO_A in mensagem
    assert SENTIDO_B in mensagem


# --- gravação e leitura (T-06, parte de banco) -----------------------------


ID_CAMERA = "000013"
CRIADA_EM = datetime(2026, 1, 1, 8, 0, 0, tzinfo=timezone.utc)


def _abrir(conexao, id_sessao: str) -> None:
    abrir_sessao(
        conexao,
        id_sessao=id_sessao,
        id_camera=ID_CAMERA,
        criada_em=CRIADA_EM,
        duracao_pedida=2,
        sentido_a=SENTIDO_A,
        sentido_b=SENTIDO_B,
    )


def test_gravar_e_ler_agregados_devolve_o_mesmo_conteudo(tmp_path):
    agregados = _agregar(
        [_evento(minuto=1, sentido=SENTIDO_A, categoria=Categoria.CARRO)],
        duracao_real=2,
        minutos_processados=(1,),
        minutos_nao_processados=(MinutoNaoProcessado(minuto=2, motivo="clipe ausente"),),
    )

    with conectar(tmp_path) as conexao:
        _abrir(conexao, "s1")
        gravar_agregados(conexao, "s1", agregados)
        conexao.commit()

        relidos = ler_agregados(conexao, "s1")

    assert relidos == agregados


def test_gravar_agregados_duas_vezes_nao_duplica(tmp_path):
    agregados = _agregar([], duracao_real=1, minutos_processados=(1,))

    with conectar(tmp_path) as conexao:
        _abrir(conexao, "s1")
        gravar_agregados(conexao, "s1", agregados)
        gravar_agregados(conexao, "s1", agregados)
        conexao.commit()

        relidos = ler_agregados(conexao, "s1")

    assert len(relidos) == 1


def test_gravar_agregados_de_sessao_inexistente_e_recusado_citando_o_id(tmp_path):
    agregados = _agregar([], duracao_real=1, minutos_processados=(1,))

    with conectar(tmp_path) as conexao:
        with pytest.raises(SessaoInexistenteError, match="sessao-inexistente"):
            gravar_agregados(conexao, "sessao-inexistente", agregados)

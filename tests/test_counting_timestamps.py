"""Timestamp do evento a partir do Last-Modified e do índice do frame — T-06.

Critério coberto, de `.spec/features/contagem-veiculos/spec.md`:

- AC-006.5 — dado o Last-Modified do clipe e o índice do frame em que o
  cruzamento ocorreu, o timestamp do evento é o início do clipe somado ao
  deslocamento do frame, com resolução de 1 segundo.

O "início do clipe" é o Last-Modified daquele clipe, leitura literal de
AC-006.5. O truncamento — e não o arredondamento — é a regra fixada em T-06:
arredondar moveria um cruzamento do segundo 59 para o minuto seguinte, que é
exatamente onde a emenda de US-007 é decidida.

Tudo em UTC com fuso explícito (SUP-030). `datetime` ingênuo é recusado, como
`capture/manifest.py` já faz em `_em_utc`.
"""

from datetime import datetime, timedelta, timezone

import pytest

from auto_counter.counting.timestamps import instante_do_evento

INICIO = datetime(2026, 3, 4, 12, 30, 0, tzinfo=timezone.utc)
FPS = 30.0


def test_AC_006_5_timestamp_e_o_inicio_do_clipe_somado_ao_deslocamento_do_frame():
    """O frame 900 a 30 fps está 30 s depois do início do clipe."""
    assert instante_do_evento(INICIO, 900, FPS) == INICIO + timedelta(seconds=30)


def test_AC_006_5_timestamp_tem_resolucao_de_um_segundo():
    """Nenhum microssegundo sobrevive: AC-006.5 fixa resolução de 1 s."""
    instante = instante_do_evento(INICIO, 47, FPS)
    assert instante.microsecond == 0
    assert instante.tzinfo is not None


def test_AC_006_5_frame_zero_cai_no_proprio_inicio_do_clipe():
    """Deslocamento nulo é o próprio Last-Modified, sem desvio de um segundo."""
    assert instante_do_evento(INICIO, 0, FPS) == INICIO


def test_AC_006_5_deslocamento_e_truncado_e_nao_arredondado_para_o_segundo_seguinte():
    """O frame 1798 (59,933 s) fica no segundo 59, não vira o minuto seguinte.

    É o último frame do clipe medido da câmera 000013. Arredondar o levaria
    para 12:31:00, para dentro do clipe seguinte, e a janela de emenda de
    US-007 passaria a decidir sobre um cruzamento que não é de emenda.
    """
    instante = instante_do_evento(INICIO, 1798, FPS)
    assert instante == INICIO + timedelta(seconds=59)


def test_instante_do_evento_recusa_datetime_ingenuo():
    """Sem `tzinfo` não há como saber qual é o fuso — assumir seria inventar hora."""
    with pytest.raises(ValueError):
        instante_do_evento(INICIO.replace(tzinfo=None), 30, FPS)


def test_instante_do_evento_normaliza_para_utc():
    """Um Last-Modified em outro fuso vira UTC, como SUP-030 exige."""
    outro_fuso = INICIO.astimezone(timezone(timedelta(hours=-3)))
    instante = instante_do_evento(outro_fuso, 30, FPS)
    assert instante.utcoffset() == timedelta(0)
    assert instante == INICIO + timedelta(seconds=1)


@pytest.mark.parametrize("fps", [0.0, -30.0])
def test_instante_do_evento_recusa_fps_nao_positivo(fps: float):
    """`fps` <= 0 é erro de programação, não evento sem hora (T-06)."""
    with pytest.raises(ValueError):
        instante_do_evento(INICIO, 30, fps)


def test_instante_do_evento_recusa_indice_negativo():
    """Não existe frame antes do início do clipe."""
    with pytest.raises(ValueError):
        instante_do_evento(INICIO, -1, FPS)

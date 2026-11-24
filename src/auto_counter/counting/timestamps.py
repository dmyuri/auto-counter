"""Timestamp do evento a partir do Last-Modified e do índice do frame — T-06.

Comportamento definido em `.spec/features/contagem-veiculos/spec.md`: AC-006.5
— o timestamp do evento é o início do clipe somado ao deslocamento do frame,
com resolução de 1 segundo.

O "início do clipe" é o **Last-Modified** daquele clipe, que AC-006.5 dá como
entrada e que AC-003.4 já usa para montar o período da sessão.

O deslocamento é **truncado** para o segundo, não arredondado. A escolha é
deliberada: a 30 fps o último frame de um clipe está em 59,93 s, e arredondar o
empurraria para o minuto seguinte — para dentro do clipe posterior —, que é
exatamente onde a janela de emenda de US-007 decide se um cruzamento é
duplicado. Truncar mantém cada cruzamento no minuto em que ele foi visto.

Tudo em UTC com fuso explícito, coerente com SUP-030 de
`persistencia-resultados`, que vai ler estes instantes.
"""

from datetime import datetime, timedelta, timezone


def instante_do_evento(
    inicio_do_clipe: datetime, indice_do_frame: int, fps: float
) -> datetime:
    """Data e hora do cruzamento observado no frame `indice_do_frame`.

    `inicio_do_clipe` é o Last-Modified do clipe e precisa ser ciente de fuso:
    um `datetime` ingênuo não diz qual é o dele, e assumir um seria inventar
    hora. `fps` vem do próprio arquivo de vídeo; um valor não positivo é erro
    de programação — quem chama leu o clipe errado —, e não um evento sem hora.
    """
    if inicio_do_clipe.tzinfo is None:
        raise ValueError(
            f"início do clipe sem fuso horário ({inicio_do_clipe!r}); o evento é "
            f"datado em UTC com fuso explícito, e um datetime ingênuo não diz "
            f"qual é o dele"
        )
    if fps <= 0:
        raise ValueError(
            f"fps precisa ser positivo, e veio {fps!r}; sem taxa de quadros não "
            f"existe deslocamento do frame para somar ao início do clipe"
        )
    if indice_do_frame < 0:
        raise ValueError(
            f"índice do frame não pode ser negativo, e veio {indice_do_frame!r}; "
            f"não existe frame antes do início do clipe"
        )
    deslocamento = int(indice_do_frame / fps)
    return inicio_do_clipe.astimezone(timezone.utc) + timedelta(seconds=deslocamento)

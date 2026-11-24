"""Deduplicação na emenda entre clipes — T-10.

Critérios cobertos, de `.spec/features/contagem-veiculos/spec.md`:

- AC-007.1 — um cruzamento nos últimos 2 s de um clipe e um cruzamento de
  assinatura compatível nos primeiros 2 s do clipe imediatamente seguinte são o
  mesmo veículo: o segundo não gera evento novo;
- AC-007.2 — assinaturas diferentes na emenda são veículos distintos, e os dois
  eventos contam;
- AC-007.4 — clipes não adjacentes (minuto perdido no meio) não aplicam a
  janela: todos os cruzamentos contam.

A assinatura é a tripla de SUP-019 — categoria, sentido e posição do cruzamento
ao longo da linha, com tolerância de 10% do comprimento da linha. A
`posicao_na_linha` do `Evento` já é a fração de 0 a 1 ao longo da linha, então a
tolerância padrão de `ConfiguracaoDoProcessamento` (0,10) é comparada
diretamente com a diferença das frações.

A janela usa o **deslocamento dentro do clipe** — índice do frame ÷ fps —, e não
o timestamp truncado de AC-006.5, que perderia resolução justamente na borda que
decide a emenda.

Nenhum teste aqui abre vídeo, carrega o `.onnx` ou toca a rede: os eventos são
fabricados diretamente.
"""

from datetime import datetime, timedelta, timezone

from auto_counter.counting.config import Categoria, ConfiguracaoDoProcessamento
from auto_counter.counting.events import Evento
from auto_counter.counting.seam import FiltroDaEmenda, assinatura, deduplicar

FPS = 30.0
DURACAO_DO_CLIPE_ANTERIOR = 59.93
"""Duração de um clipe de 1798 frames a 30 fps, lida do arquivo (T-11)."""

INICIO_DO_CLIPE_ANTERIOR = datetime(2026, 5, 4, 12, 30, 0, tzinfo=timezone.utc)
INICIO_DO_CLIPE_ATUAL = datetime(2026, 5, 4, 12, 31, 0, tzinfo=timezone.utc)

CONFIG = ConfiguracaoDoProcessamento()


def evento(
    *,
    minuto: int,
    indice_do_frame: int,
    inicio_do_clipe: datetime,
    categoria: Categoria = Categoria.CARRO,
    sentido: str = "CENTRO",
    posicao_na_linha: float = 0.50,
    id_do_rastreador: int = 1,
) -> Evento:
    """Um evento de cruzamento fabricado, datado como T-06 o dataria."""
    return Evento(
        timestamp=inicio_do_clipe + timedelta(seconds=int(indice_do_frame / FPS)),
        categoria=categoria,
        sentido=sentido,
        id_de_rastreio=f"{minuto}:{id_do_rastreador}",
        confianca=0.80,
        minuto=minuto,
        indice_do_frame=indice_do_frame,
        posicao_na_linha=posicao_na_linha,
    )


def dedup(anteriores, atuais, *, adjacentes=True, config=CONFIG):
    """Chama `deduplicar` no cenário padrão de dois clipes de 30 fps."""
    return deduplicar(
        anteriores,
        atuais,
        adjacentes=adjacentes,
        fps_do_clipe_anterior=FPS,
        duracao_do_clipe_anterior=DURACAO_DO_CLIPE_ANTERIOR,
        fps_do_clipe_atual=FPS,
        config=config,
    )


def test_assinatura_e_a_tripla_de_sup_019():
    """A assinatura é categoria, sentido e posição — e nada mais (SUP-019).

    Em particular ela não carrega id de rastreio nem minuto: se carregasse,
    dois cruzamentos da emenda nunca seriam compatíveis, porque o rastreador
    reinicia a cada clipe (AC-007.3) e os ids jamais coincidem.
    """
    um = evento(
        minuto=3, indice_do_frame=1790, inicio_do_clipe=INICIO_DO_CLIPE_ANTERIOR
    )
    outro = evento(
        minuto=4,
        indice_do_frame=10,
        inicio_do_clipe=INICIO_DO_CLIPE_ATUAL,
        id_do_rastreador=99,
    )

    assert assinatura(um) == assinatura(outro)


def test_AC_007_1_cruzamento_compativel_nos_dois_segundos_da_emenda_nao_gera_evento_novo():
    """O mesmo veículo visto dos dois lados do corte conta uma vez só.

    O frame 1790 está a 59,67 s — dentro dos últimos 2 s de um clipe de 59,93 s
    — e o frame 15 do clipe seguinte está a 0,5 s do começo. Mesma categoria,
    mesmo sentido e posições a 0,02 de distância, bem dentro dos 10% de SUP-019.
    """
    anterior = evento(
        minuto=3,
        indice_do_frame=1790,
        inicio_do_clipe=INICIO_DO_CLIPE_ANTERIOR,
        posicao_na_linha=0.50,
    )
    atual = evento(
        minuto=4,
        indice_do_frame=15,
        inicio_do_clipe=INICIO_DO_CLIPE_ATUAL,
        posicao_na_linha=0.52,
    )

    assert dedup([anterior], [atual]) == ()


def test_AC_007_1_cruzamento_fora_da_janela_de_dois_segundos_continua_contando():
    """Fora dos 2 s de cada lado não há emenda, e o evento é preservado.

    Os dois lados da janela no mesmo teste, porque errar um só passaria
    despercebido se o outro fosse verificado sozinho: o cruzamento anterior a
    50 s do início do clipe (frame 1500, longe do corte) e o cruzamento atual a
    3 s do início do clipe seguinte (frame 90).
    """
    anterior_cedo = evento(
        minuto=3, indice_do_frame=1500, inicio_do_clipe=INICIO_DO_CLIPE_ANTERIOR
    )
    anterior_na_janela = evento(
        minuto=3, indice_do_frame=1790, inicio_do_clipe=INICIO_DO_CLIPE_ANTERIOR
    )
    atual_na_janela = evento(
        minuto=4, indice_do_frame=15, inicio_do_clipe=INICIO_DO_CLIPE_ATUAL
    )
    atual_tarde = evento(
        minuto=4, indice_do_frame=90, inicio_do_clipe=INICIO_DO_CLIPE_ATUAL
    )

    # O cruzamento anterior está longe do corte: não suprime nada.
    assert dedup([anterior_cedo], [atual_na_janela]) == (atual_na_janela,)

    # O cruzamento atual está depois dos 2 s: não é candidato à supressão.
    assert dedup([anterior_na_janela], [atual_tarde]) == (atual_tarde,)


def test_AC_007_2_assinaturas_diferentes_na_emenda_geram_dois_eventos():
    """Dois veículos distintos no corte contam os dois.

    Uma diferença por componente da tripla de SUP-019, para que o teste acuse se
    a comparação ignorar qualquer um deles: categoria diferente, sentido
    diferente e posição na linha além dos 10%.
    """
    anterior = evento(
        minuto=3,
        indice_do_frame=1790,
        inicio_do_clipe=INICIO_DO_CLIPE_ANTERIOR,
        categoria=Categoria.CARRO,
        sentido="CENTRO",
        posicao_na_linha=0.20,
    )

    outra_categoria = evento(
        minuto=4,
        indice_do_frame=15,
        inicio_do_clipe=INICIO_DO_CLIPE_ATUAL,
        categoria=Categoria.CAMINHAO,
        sentido="CENTRO",
        posicao_na_linha=0.20,
    )
    outro_sentido = evento(
        minuto=4,
        indice_do_frame=15,
        inicio_do_clipe=INICIO_DO_CLIPE_ATUAL,
        categoria=Categoria.CARRO,
        sentido="ICARAI",
        posicao_na_linha=0.20,
    )
    outra_posicao = evento(
        minuto=4,
        indice_do_frame=15,
        inicio_do_clipe=INICIO_DO_CLIPE_ATUAL,
        categoria=Categoria.CARRO,
        sentido="CENTRO",
        posicao_na_linha=0.35,
    )

    assert dedup([anterior], [outra_categoria]) == (outra_categoria,)
    assert dedup([anterior], [outro_sentido]) == (outro_sentido,)
    assert dedup([anterior], [outra_posicao]) == (outra_posicao,)


def test_AC_007_2_dois_veiculos_iguais_no_inicio_do_clipe_seguinte_nao_somem_juntos():
    """Pareamento 1 para 1: um cruzamento anterior suprime no máximo um.

    Dois carros na mesma faixa entrando no início do clipe seguinte com a mesma
    assinatura. Só um deles é a continuação do cruzamento visto no fim do clipe
    anterior; o outro é veículo novo, e AC-007.2 exige que ele conte.
    """
    anterior = evento(
        minuto=3,
        indice_do_frame=1790,
        inicio_do_clipe=INICIO_DO_CLIPE_ANTERIOR,
        posicao_na_linha=0.50,
    )
    primeiro = evento(
        minuto=4,
        indice_do_frame=10,
        inicio_do_clipe=INICIO_DO_CLIPE_ATUAL,
        posicao_na_linha=0.50,
        id_do_rastreador=1,
    )
    segundo = evento(
        minuto=4,
        indice_do_frame=40,
        inicio_do_clipe=INICIO_DO_CLIPE_ATUAL,
        posicao_na_linha=0.50,
        id_do_rastreador=2,
    )

    assert dedup([anterior], [primeiro, segundo]) == (segundo,)


def test_AC_007_4_clipes_nao_adjacentes_nao_aplicam_a_janela_de_deduplicacao():
    """Minuto perdido no meio desliga a deduplicação inteira.

    Os dois clipes não são vizinhos no tempo, então um cruzamento no fim de um e
    outro no início do outro não podem ser o mesmo veículo — mesmo com
    assinatura idêntica. Todos os cruzamentos contam.
    """
    anterior = evento(
        minuto=3,
        indice_do_frame=1790,
        inicio_do_clipe=INICIO_DO_CLIPE_ANTERIOR,
        posicao_na_linha=0.50,
    )
    atual = evento(
        minuto=5,
        indice_do_frame=15,
        inicio_do_clipe=INICIO_DO_CLIPE_ATUAL,
        posicao_na_linha=0.50,
    )

    assert dedup([anterior], [atual], adjacentes=False) == (atual,)


def filtro(anteriores, *, adjacentes=True, config=CONFIG):
    """O `FiltroDaEmenda` do cenário padrão de dois clipes de 30 fps."""
    return FiltroDaEmenda(
        eventos_do_clipe_anterior=anteriores,
        adjacentes=adjacentes,
        fps_do_clipe_anterior=FPS,
        duracao_do_clipe_anterior=DURACAO_DO_CLIPE_ANTERIOR,
        config=config,
    )


def test_AC_016_3_filtro_incremental_da_o_mesmo_resultado_que_deduplicar():
    """Alimentado evento a evento, o filtro decide como `deduplicar` (D-1).

    Cenários: dentro e fora da janela, assinatura igual, próxima da tolerância e
    diferente, dois veículos iguais no início do clipe seguinte e não adjacentes.
    """
    ant = INICIO_DO_CLIPE_ANTERIOR
    atu = INICIO_DO_CLIPE_ATUAL
    fim = evento(minuto=3, indice_do_frame=1790, inicio_do_clipe=ant)
    cedo = evento(minuto=3, indice_do_frame=1500, inicio_do_clipe=ant)

    cenarios = [
        ([fim], [evento(minuto=4, indice_do_frame=15, inicio_do_clipe=atu)], True),
        ([cedo], [evento(minuto=4, indice_do_frame=15, inicio_do_clipe=atu)], True),
        ([fim], [evento(minuto=4, indice_do_frame=90, inicio_do_clipe=atu)], True),
        (
            [fim],
            [
                evento(
                    minuto=4,
                    indice_do_frame=15,
                    inicio_do_clipe=atu,
                    posicao_na_linha=0.60,
                )
            ],
            True,
        ),
        (
            [fim],
            [
                evento(
                    minuto=4,
                    indice_do_frame=15,
                    inicio_do_clipe=atu,
                    posicao_na_linha=0.61,
                )
            ],
            True,
        ),
        (
            [fim],
            [
                evento(
                    minuto=4,
                    indice_do_frame=15,
                    inicio_do_clipe=atu,
                    categoria=Categoria.MOTO,
                ),
                evento(
                    minuto=4,
                    indice_do_frame=20,
                    inicio_do_clipe=atu,
                    sentido="ICARAI",
                ),
            ],
            True,
        ),
        (
            [fim],
            [
                evento(
                    minuto=4, indice_do_frame=10, inicio_do_clipe=atu, id_do_rastreador=1
                ),
                evento(
                    minuto=4, indice_do_frame=40, inicio_do_clipe=atu, id_do_rastreador=2
                ),
            ],
            True,
        ),
        ([fim], [evento(minuto=5, indice_do_frame=15, inicio_do_clipe=atu)], False),
        ([], [evento(minuto=4, indice_do_frame=15, inicio_do_clipe=atu)], True),
    ]

    for anteriores, atuais, adjacentes in cenarios:
        incremental = filtro(anteriores, adjacentes=adjacentes)
        aceitos = tuple(
            e for e in atuais if incremental.aceita(e, fps_do_clipe_atual=FPS)
        )
        assert aceitos == dedup(anteriores, atuais, adjacentes=adjacentes)


def test_AC_016_3_cruzamento_duplicado_na_emenda_e_recusado_no_momento_em_que_chega():
    """A duplicata recebe `False` na própria chamada, sem esperar o clipe acabar."""
    anterior = evento(
        minuto=3, indice_do_frame=1790, inicio_do_clipe=INICIO_DO_CLIPE_ANTERIOR
    )
    duplicata = evento(
        minuto=4,
        indice_do_frame=15,
        inicio_do_clipe=INICIO_DO_CLIPE_ATUAL,
        posicao_na_linha=0.52,
    )

    assert filtro([anterior]).aceita(duplicata, fps_do_clipe_atual=FPS) is False


def test_AC_016_3_filtro_sem_anterior_aceita_tudo():
    """Primeiro minuto, ou minuto depois de um D-4: nada para suprimir."""
    qualquer = evento(
        minuto=1, indice_do_frame=0, inicio_do_clipe=INICIO_DO_CLIPE_ATUAL
    )

    assert FiltroDaEmenda.sem_anterior().aceita(qualquer, fps_do_clipe_atual=FPS)


def test_AC_007_2_filtro_aceita_veiculo_de_assinatura_diferente_na_emenda():
    """Categoria, sentido ou posição diferentes: veículo novo, mesmo na janela."""
    anterior = evento(
        minuto=3,
        indice_do_frame=1790,
        inicio_do_clipe=INICIO_DO_CLIPE_ANTERIOR,
        posicao_na_linha=0.20,
    )
    outra_categoria = evento(
        minuto=4,
        indice_do_frame=15,
        inicio_do_clipe=INICIO_DO_CLIPE_ATUAL,
        categoria=Categoria.CAMINHAO,
        posicao_na_linha=0.20,
    )
    outro_sentido = evento(
        minuto=4,
        indice_do_frame=15,
        inicio_do_clipe=INICIO_DO_CLIPE_ATUAL,
        sentido="ICARAI",
        posicao_na_linha=0.20,
    )
    outra_posicao = evento(
        minuto=4,
        indice_do_frame=15,
        inicio_do_clipe=INICIO_DO_CLIPE_ATUAL,
        posicao_na_linha=0.35,
    )

    for novo in (outra_categoria, outro_sentido, outra_posicao):
        assert filtro([anterior]).aceita(novo, fps_do_clipe_atual=FPS) is True

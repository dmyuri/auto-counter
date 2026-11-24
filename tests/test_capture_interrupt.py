"""Encerramento explícito pelo usuário — T-08.

Critério coberto, de `.spec/features/captura-clipes/spec.md`:

- AC-003.6 — o usuário interrompe a captura no minuto k de N pedidos: a duração
  real da sessão passa a ser k, o status de AC-004.4 a AC-004.6 é calculado
  sobre k e não sobre N, o encerramento pelo usuário fica registrado na sessão,
  e os k minutos já capturados seguem para processamento.

SUP-013 é o que obriga a troca do denominador: a regra dos 20% usa o N
**pedido**, exceto quando o usuário interrompe de propósito — desistência nunca
cai nessa regra. Por isso o teste central aqui é o de `_tasks.md`: pedir 15 e
parar no 7 sem nenhuma perda produz sessão de duração real 7 com status
`COMPLETA`, e não `INVALIDA` por "8 minutos perdidos".

Q-003 decidiu que **não existe um quarto status**: o encerramento é um campo à
parte da sessão, e é ele que AC-008.1 e AC-010.4 vão consumir.

A parada é modelada como sinal explícito vindo de fora, e não como morte do
processo, porque fechar a interface não interrompe nada (AC-012.4 de
`interface-sessao`). O dublê `ParadaFalsa` é dirigido pelo relógio falso, do
mesmo jeito que o servidor dublê: ele passa a responder "parada pedida" a partir
de um instante marcado, que é como um Ctrl+C ou um clique no botão chegam —
num momento do tempo, não depois de um número de requisições.

O relógio, a espera e o cliente HTTP são injetados (D-7) e nenhum teste toca o
servidor da NitTrans. A infraestrutura de dublês é reusada de
`tests.test_capture_session` de propósito: o servidor falso e o relógio falso
já provam T-07 e reimplementá-los aqui faria os dois testes divergirem em
silêncio.
"""

from datetime import timedelta

import pytest

from auto_counter.capture.manifest import ler
from auto_counter.capture.session import JANELA_DO_MINUTO, capturar
from auto_counter.capture.status import StatusDaSessao
from tests.test_capture_session import (  # noqa: F401  (fixtures usadas por nome)
    LAST_MODIFIED_BASE,
    DormirFalso,
    RelogioFalso,
    ServidorFalso,
    base_url_no_ambiente,
    camera,
    clipes_legiveis,
)


class ParadaFalsa:
    """O sinal de AC-003.6, dirigido pelo relógio falso.

    `foi_pedida` passa a ser verdadeiro a partir de `segundo` no relógio falso.
    Registra quantas vezes foi consultada para provar que o laço olha o sinal
    entre checagens e entre minutos, e não só no fim da sessão.
    """

    def __init__(self, relogio: RelogioFalso, segundo: float):
        self.relogio = relogio
        self.segundo = segundo
        self.consultas = 0

    def foi_pedida(self) -> bool:
        self.consultas += 1
        return self.relogio.decorrido() >= self.segundo


def executa(camera, tmp_path, servidor, relogio, minutos: int, parada=None):
    """Roda o laço com relógio, espera, transporte HTTP e parada falsos."""
    return capturar(
        camera,
        minutos,
        data_dir=tmp_path / "data",
        cliente=servidor.cliente(),
        agora=relogio.agora,
        dormir=DormirFalso(relogio),
        parada=parada,
    )


def servidor_de_um_clipe_por_minuto(relogio, clipes_legiveis, minutos: int):
    """Servidor que publica um clipe novo a cada 60 s, sem falha nenhuma.

    É o cenário limpo: qualquer perda que aparecer num teste destes veio do
    encerramento sendo contado como perda, que é exatamente o defeito que
    AC-003.6 proíbe. Cada minuto publica conteúdo próprio, e não só ETag novo:
    republicar o mesmo vídeo é recusado desde AC-004.7 e viraria perda.
    """
    publicacoes = [(60.0 * indice, f"clipe-{indice:02d}") for indice in range(minutos)]
    return ServidorFalso(
        relogio, publicacoes, clipes_legiveis(*[etag for _, etag in publicacoes])
    )


def test_AC_003_6_interrupcao_no_minuto_k_faz_a_duracao_real_da_sessao_ser_k(
    camera, tmp_path, clipes_legiveis
):
    relogio = RelogioFalso()
    servidor = servidor_de_um_clipe_por_minuto(relogio, clipes_legiveis, minutos=15)
    # O minuto 7 é aceito em t=360; a parada chega no meio da janela do minuto
    # 8, que só teria clipe novo em t=420. Instante escolhido de propósito longe
    # de qualquer publicação: parada e clipe no mesmo segundo tornariam o
    # desfecho ambíguo e o teste deixaria de afirmar o que quer afirmar.
    parada = ParadaFalsa(relogio, segundo=380.0)

    resultado = executa(camera, tmp_path, servidor, relogio, 15, parada=parada)

    assert resultado.duracao_pedida == 15
    assert resultado.duracao_real == 7
    assert [item.minuto for item in resultado.minutos_capturados] == list(range(1, 8))
    # Os 8 minutos que não chegaram a acontecer **não** são minutos perdidos.
    assert resultado.minutos_perdidos == ()
    # E o sinal foi consultado durante a sessão, não só no fim dela.
    assert parada.consultas > 1


def test_AC_003_6_status_e_calculado_sobre_a_duracao_real_e_nao_sobre_a_pedida(
    camera, tmp_path, clipes_legiveis
):
    """O caso de `_tasks.md`: pedir 15, parar no 7, sem perda → `COMPLETA`.

    Com o denominador errado — o N pedido — seriam 8 minutos "perdidos" em 15, o
    que daria `INVALIDA`. SUP-013 diz que desistência nunca cai nessa regra.
    """
    relogio = RelogioFalso()
    servidor = servidor_de_um_clipe_por_minuto(relogio, clipes_legiveis, minutos=15)
    parada = ParadaFalsa(relogio, segundo=380.0)

    resultado = executa(camera, tmp_path, servidor, relogio, 15, parada=parada)

    assert resultado.duracao_real == 7
    assert resultado.status is StatusDaSessao.COMPLETA
    assert ler(resultado.dir_sessao).status is StatusDaSessao.COMPLETA


def test_AC_003_6_status_sobre_a_duracao_real_ainda_conta_os_minutos_perdidos(
    camera, tmp_path, clipes_legiveis
):
    """Trocar o denominador não é perdoar as perdas reais que houve.

    O servidor para de publicar depois do clipe de t=60, então a janela do
    minuto 3 se esgota em t=150 e o minuto 3 é uma perda de verdade (AC-004.2).
    A parada chega em seguida, com duração real 4. Uma perda em 4 é 25%: mais de
    20%, logo `INVALIDA` — o denominador muda, a regra dos 20% continua valendo.
    """
    relogio = RelogioFalso()
    servidor = ServidorFalso(
        relogio,
        [(0.0, "clipe-a"), (60.0, "clipe-b"), (200.0, "clipe-c"), (260.0, "clipe-d")],
        clipes_legiveis("clipe-a", "clipe-b", "clipe-c", "clipe-d"),
    )
    parada = ParadaFalsa(relogio, segundo=230.0)

    resultado = executa(camera, tmp_path, servidor, relogio, 15, parada=parada)

    assert [item.minuto for item in resultado.minutos_capturados] == [1, 2, 4]
    assert [item.minuto for item in resultado.minutos_perdidos] == [3]
    assert resultado.duracao_real == 4
    assert resultado.status is StatusDaSessao.INVALIDA


def test_AC_003_6_encerramento_pelo_usuario_fica_registrado_na_sessao(
    camera, tmp_path, clipes_legiveis
):
    """O campo de Q-003, que AC-008.1 e AC-010.4 vão consumir do manifest."""
    relogio = RelogioFalso()
    servidor = servidor_de_um_clipe_por_minuto(relogio, clipes_legiveis, minutos=15)
    parada = ParadaFalsa(relogio, segundo=200.0)

    resultado = executa(camera, tmp_path, servidor, relogio, 15, parada=parada)

    assert resultado.encerrada_pelo_usuario is True

    gravado = ler(resultado.dir_sessao)
    assert gravado.encerrada_pelo_usuario is True
    assert gravado.duracao_pedida == 15
    assert gravado.duracao_real == 4
    # O vocabulário continua sendo o de três status: o encerramento é campo à
    # parte, não um quarto nome (Q-003).
    assert gravado.status in tuple(StatusDaSessao)


def test_AC_003_6_sessao_sem_encerramento_do_usuario_nao_marca_o_campo(
    camera, tmp_path, clipes_legiveis
):
    """O campo só é verdadeiro quando houve ação explícita do usuário.

    Sem isso, "encerrada pelo usuário" não distinguiria nada e o denominador de
    SUP-013 trocaria em toda sessão.
    """
    relogio = RelogioFalso()
    servidor = servidor_de_um_clipe_por_minuto(relogio, clipes_legiveis, minutos=3)
    # A parada existe, mas nunca é pedida dentro do horizonte desta sessão.
    parada = ParadaFalsa(relogio, segundo=10_000.0)

    resultado = executa(camera, tmp_path, servidor, relogio, 3, parada=parada)

    assert resultado.encerrada_pelo_usuario is False
    assert resultado.duracao_real == 3
    assert resultado.duracao_pedida == 3
    assert ler(resultado.dir_sessao).encerrada_pelo_usuario is False


def test_AC_003_6_minutos_ja_capturados_seguem_para_processamento(
    camera, tmp_path, clipes_legiveis
):
    """O retorno é sessão normal, não erro: os k minutos continuam utilizáveis.

    "Seguem para processamento" se prova em disco e no manifest: os `.mp4` dos
    minutos aceitos continuam no diretório da sessão, com ETag e Last-Modified
    associados, e o período de AC-003.4 é o dos clipes efetivamente capturados.
    """
    relogio = RelogioFalso()
    servidor = servidor_de_um_clipe_por_minuto(relogio, clipes_legiveis, minutos=15)
    parada = ParadaFalsa(relogio, segundo=200.0)

    resultado = executa(camera, tmp_path, servidor, relogio, 15, parada=parada)

    assert sorted(p.name for p in resultado.dir_sessao.glob("*.mp4")) == [
        "minuto-01.mp4",
        "minuto-02.mp4",
        "minuto-03.mp4",
        "minuto-04.mp4",
    ]

    gravado = ler(resultado.dir_sessao)
    assert [item.minuto for item in gravado.minutos_capturados] == [1, 2, 3, 4]
    assert len({item.etag for item in gravado.minutos_capturados}) == 4
    assert gravado.inicio == LAST_MODIFIED_BASE
    assert gravado.fim == LAST_MODIFIED_BASE + timedelta(seconds=180)
    assert resultado.inicio == gravado.inicio
    assert resultado.fim == gravado.fim


def test_AC_003_6_parada_no_meio_da_janela_nao_conta_o_minuto_como_perdido(
    camera, tmp_path, clipes_legiveis
):
    """A diferença entre uma sessão `DEGRADADA` falsa e uma `COMPLETA` correta.

    O minuto 5 está no meio da sua janela — o servidor só publicaria o próximo
    clipe em t=240 — quando a parada chega em t=200. Esse minuto não existe:
    não é perda, e a duração real é 4, não 5.
    """
    relogio = RelogioFalso()
    servidor = servidor_de_um_clipe_por_minuto(relogio, clipes_legiveis, minutos=15)
    parada = ParadaFalsa(relogio, segundo=200.0)

    resultado = executa(camera, tmp_path, servidor, relogio, 15, parada=parada)

    assert [item.minuto for item in resultado.minutos_capturados] == [1, 2, 3, 4]
    assert resultado.minutos_perdidos == ()
    assert resultado.duracao_real == 4
    assert resultado.status is StatusDaSessao.COMPLETA
    # A janela do minuto 5 foi abandonada antes dos 90 s de SUP-008: a parada
    # não espera a janela vencer.
    assert relogio.decorrido() < 180.0 + JANELA_DO_MINUTO


def test_AC_003_6_parada_antes_do_primeiro_clipe_produz_sessao_invalida(
    camera, tmp_path, clipes_legiveis
):
    """Duração real 0: nenhuma comparação é possível, então `INVALIDA`.

    Decisão do autor do projeto: a sessão de duração real 0 recebe `INVALIDA`
    sem passar por `capture.status.classificar`, que rejeita `base < 1` como
    erro de programação. Continua sendo sessão, não exceção (AC-003.6), e não
    cria um quarto status (Q-003).
    """
    relogio = RelogioFalso()
    # O servidor nunca publica nada de novo, e a parada chega no instante do
    # comando — antes de qualquer clipe ser aceito.
    servidor = ServidorFalso(relogio, [(0.0, "clipe-a")], clipes_legiveis("clipe-a"))
    parada = ParadaFalsa(relogio, segundo=0.0)

    resultado = executa(camera, tmp_path, servidor, relogio, 15, parada=parada)

    assert resultado.duracao_real == 0
    assert resultado.encerrada_pelo_usuario is True
    assert resultado.minutos_capturados == ()
    assert resultado.minutos_perdidos == ()
    assert resultado.status is StatusDaSessao.INVALIDA
    # Sem nenhum clipe capturado não há período (AC-003.4).
    assert resultado.inicio is None
    assert resultado.fim is None

    gravado = ler(resultado.dir_sessao)
    assert gravado.status is StatusDaSessao.INVALIDA
    assert gravado.duracao_real == 0
    assert gravado.encerrada_pelo_usuario is True


def test_AC_003_6_parada_sem_sinal_nenhum_deixa_a_sessao_ir_ate_o_n_pedido(
    camera, tmp_path, clipes_legiveis
):
    """`parada=None` é o caso do laço sem interface: nada muda em T-07."""
    relogio = RelogioFalso()
    servidor = servidor_de_um_clipe_por_minuto(relogio, clipes_legiveis, minutos=3)

    resultado = executa(camera, tmp_path, servidor, relogio, 3, parada=None)

    assert resultado.duracao_real == 3
    assert resultado.encerrada_pelo_usuario is False
    assert resultado.status is StatusDaSessao.COMPLETA


@pytest.mark.parametrize("segundo_da_parada", [0.0, 50.0, 200.0, 380.0])
def test_AC_003_6_nenhuma_parada_deixa_excecao_escapar_para_o_usuario(
    camera, tmp_path, clipes_legiveis, segundo_da_parada
):
    """A parada em qualquer ponto produz sessão fechada, nunca exceção.

    `CLAUDE.md` proíbe que falha de captura vire exceção não tratada, e a parada
    em t=0 é justamente a que passa perto do `ValueError` de `classificar`.
    """
    relogio = RelogioFalso()
    servidor = servidor_de_um_clipe_por_minuto(relogio, clipes_legiveis, minutos=15)
    parada = ParadaFalsa(relogio, segundo=segundo_da_parada)

    resultado = executa(camera, tmp_path, servidor, relogio, 15, parada=parada)

    assert resultado.encerrada_pelo_usuario is True
    assert resultado.status in tuple(StatusDaSessao)
    assert resultado.duracao_real == len(resultado.minutos_capturados) + len(
        resultado.minutos_perdidos
    )


def test_AC_012_1_o_minuto_abandonado_por_parada_nao_chega_ao_gancho(
    camera, tmp_path, clipes_legiveis
):
    relogio = RelogioFalso()
    servidor = servidor_de_um_clipe_por_minuto(relogio, clipes_legiveis, minutos=15)
    # O minuto 3 é aceito em t=120; a parada chega no meio da janela do minuto 4.
    parada = ParadaFalsa(relogio, segundo=140.0)
    chamadas: list[tuple[int, bool]] = []

    resultado = capturar(
        camera,
        15,
        data_dir=tmp_path / "data",
        cliente=servidor.cliente(),
        agora=relogio.agora,
        dormir=DormirFalso(relogio),
        parada=parada,
        ao_resolver_minuto=lambda minuto, capturado: chamadas.append(
            (minuto, capturado)
        ),
    )

    assert resultado.duracao_real == 3
    assert chamadas == [(1, True), (2, True), (3, True)]


def test_AC_012_7_parada_durante_a_espera_entre_checagens_tem_efeito_em_menos_de_um_segundo(
    camera, tmp_path, clipes_legiveis
):
    """A espera de 10 s entre checagens (SUP-008) não segura o pedido de parada.

    O minuto 7 é aceito em t=360 e a próxima checagem seria em t=370. A parada
    chega em t=365, no meio dessa espera: a captura tem de parar ali, e não só
    na checagem seguinte.
    """
    relogio = RelogioFalso()
    servidor = servidor_de_um_clipe_por_minuto(relogio, clipes_legiveis, minutos=15)
    parada = ParadaFalsa(relogio, segundo=365.0)

    resultado = executa(camera, tmp_path, servidor, relogio, 15, parada=parada)

    assert resultado.duracao_real == 7
    assert relogio.decorrido() < 366.0


def test_AC_012_7_sem_parada_a_espera_entre_checagens_continua_de_dez_segundos(
    camera, tmp_path, clipes_legiveis
):
    # Sem quem possa pedir a parada, a espera não é fatiada: SUP-008 intacta.
    relogio = RelogioFalso()
    servidor = servidor_de_um_clipe_por_minuto(relogio, clipes_legiveis, minutos=2)
    dormir = DormirFalso(relogio)

    capturar(
        camera,
        2,
        data_dir=tmp_path / "data",
        cliente=servidor.cliente(),
        agora=relogio.agora,
        dormir=dormir,
    )

    assert 10.0 in dormir.esperas
    assert all(espera >= 10.0 for espera in dormir.esperas[:-1])


class ParadaNoSegundoDownload:
    """Pedida assim que o servidor recebe o GET do clipe do minuto 2."""

    def __init__(self, servidor: ServidorFalso):
        self.servidor = servidor

    def foi_pedida(self) -> bool:
        return self.servidor.metodos().count("GET") >= 2


def test_AC_012_7_parada_durante_o_download_abandona_o_minuto_sem_contar_perda(
    camera, tmp_path, clipes_legiveis
):
    relogio = RelogioFalso()
    servidor = servidor_de_um_clipe_por_minuto(relogio, clipes_legiveis, minutos=15)
    parada = ParadaNoSegundoDownload(servidor)

    resultado = executa(camera, tmp_path, servidor, relogio, 15, parada=parada)

    assert [item.minuto for item in resultado.minutos_capturados] == [1]
    assert resultado.minutos_perdidos == ()
    assert resultado.duracao_real == 1
    # O arquivo do minuto interrompido não fica no diretório da sessão.
    assert sorted(p.name for p in resultado.dir_sessao.glob("*.mp4")) == [
        resultado.minutos_capturados[0].arquivo
    ]

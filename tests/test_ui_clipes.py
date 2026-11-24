"""Interface: lista de clipes, downloads e `.zip` no painel "Sessão finalizada" —
download-clipes.

Critérios cobertos, de `.spec/features/download-clipes/spec.md`: AC-024.3 (a
mensagem), AC-025.1 a AC-025.6 (SUP-073, SUP-077, D-6, D-7, D-10).

Como em `test_ui_resultado.py`, o `AppTest` não clica em `download_button`: um
espião em `streamlit.download_button` registra o que a interface entrega, e a
marca de "baixado" é gravada em `at.session_state` como o `on_click` faria.

O estado é montado à mão em `tmp_path`, com os `.mp4` (bytes quaisquer) no
diretório da sessão. Nada aqui toca a rede, abre navegador ou lê o `.env`.
"""

import io
import os
import zipfile
from datetime import datetime, timedelta, timezone

import pytest

from auto_counter.capture.status import StatusDaSessao
from auto_counter.pipeline.state import AnotadorDoEstado, ClipeMantido, Fase
from auto_counter.storage.connection import conectar
from tests.export_helpers import ID_SESSAO, gravar_sessao
from tests.test_ui_acompanhamento import (  # noqa: F401  (fixtures usadas por nome)
    INICIO,
    data_dir,
    downloads,
    textos,
)
from tests.test_ui_formulario import (  # noqa: F401  (fixtures usadas por nome)
    abre_a_interface,
    ambiente,
    registro_com,
)
from tests.test_ui_resultado import (  # noqa: F401  (fixtures usadas por nome)
    chave_do_resultado,
    entregas,
)

ROTULO_DO_ZIP = "Baixar todos (.zip)"
ROTULO_DO_CLIPE = "Baixar"
MENSAGEM_NAO_MANTIDOS = "Clipes não foram mantidos nesta sessão."
# Três clipes em minutos de relógio distintos (11:00, 11:01 e 11:02 UTC).
TAMANHOS = {1: 1_000_000, 2: 2_000_000, 3: 1_500_000}
DURACOES = {1: 59, 2: 59, 3: None}


def nome_do_clipe(minuto: int) -> str:
    return f"000013_20260907_08{minuto - 1:02d}.mp4"


def clipe(data_dir, minuto: int, *, last_modified=None, tamanho=None):
    """Escreve o `.mp4` no diretório da sessão e devolve o item do estado."""
    pasta = data_dir / "sessions" / ID_SESSAO
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / f"minuto-{minuto:02d}.mp4"
    tamanho = TAMANHOS.get(minuto, 1000) if tamanho is None else tamanho
    caminho.write_bytes(bytes([minuto]) * tamanho)
    return ClipeMantido(
        minuto=minuto,
        caminho=caminho,
        last_modified=last_modified or INICIO + timedelta(minutes=minuto - 1),
        duracao_segundos=DURACOES.get(minuto, 59),
    )


def sessao(
    data_dir,
    fase=Fase.CONCLUIDA,
    *,
    manter_videos=True,
    clipes=None,
    pid=None,
):
    """Sessão terminada em `fase`, com `manter_videos` e `clipes` no estado."""
    data_dir.mkdir(parents=True, exist_ok=True)
    campos = {}
    if fase is Fase.CONCLUIDA:
        with conectar(data_dir) as conexao:
            gravar_sessao(conexao, status=StatusDaSessao.COMPLETA)
        planilha = data_dir / "000013_20260907_0800_2min.xlsx"
        planilha.write_bytes(b"conteudo do xlsx")
        campos = {"status": "COMPLETA", "planilha": str(planilha)}
    elif fase is not Fase.FALHOU:
        campos = {"status": "INVALIDA", "mensagem": "desfecho de teste"}
    a = AnotadorDoEstado(
        data_dir,
        pid=os.getpid() if pid is None else pid,
        id_camera="000013",
        nome_camera="Praça Exemplo",
        duracao_pedida=3,
        iniciada_em=INICIO,
        agora=lambda: INICIO + timedelta(minutes=5),
        manter_videos=manter_videos,
    )
    a.iniciar()
    if pid is None:
        a.terminar(
            fase,
            id_sessao=ID_SESSAO,
            clipes=None if clipes is None else tuple(clipes),
            **campos,
        )


def tres_clipes(data_dir):
    return [clipe(data_dir, m) for m in (1, 2, 3)]


def entregas_de_clipe(entregas):
    return [e for e in entregas if e.get("file_name", "").endswith(".mp4")]


def entrega_do_zip(entregas):
    (zip_,) = [e for e in entregas if e.get("file_name", "").endswith(".zip")]
    return zip_


def rotulos(at) -> list[str]:
    return [d.proto.label for d in downloads(at)]


def test_AC_025_1_lista_k_clipes_em_ordem_com_nome_duracao_tamanho_e_titulo(
    data_dir, entregas
):
    sessao(data_dir, clipes=tres_clipes(data_dir))

    at = abre_a_interface()

    assert not at.exception
    texto = textos(at)
    assert "Clipes · 3 arquivos · 4,5 MB" in texto
    nomes = [nome_do_clipe(m) for m in (1, 2, 3)]
    posicoes = [texto.index(n) for n in nomes]
    assert posicoes == sorted(posicoes)
    assert "00:59" in texto
    for tamanho in ("1,0 MB", "2,0 MB", "1,5 MB"):
        assert tamanho in texto
    assert "—" in texto  # a duração do minuto 3 não foi medida
    assert [e["file_name"] for e in entregas_de_clipe(entregas)] == nomes
    assert rotulos(at).count(ROTULO_DO_CLIPE) == 3


def test_AC_025_2_minuto_perdido_nao_aparece_na_lista(data_dir, entregas):
    sessao(data_dir, clipes=[clipe(data_dir, 1), clipe(data_dir, 2), clipe(data_dir, 4)])

    at = abre_a_interface()

    texto = textos(at)
    assert "Clipes · 3 arquivos" in texto
    assert nome_do_clipe(3) not in texto
    assert [e["file_name"] for e in entregas_de_clipe(entregas)] == [
        nome_do_clipe(1),
        nome_do_clipe(2),
        nome_do_clipe(4),
    ]


def test_AC_025_3_baixar_clipe_entrega_os_bytes_do_disco_com_o_nome_de_sup_077(
    data_dir, entregas
):
    itens = tres_clipes(data_dir)
    sessao(data_dir, clipes=itens)

    abre_a_interface()

    entregues = entregas_de_clipe(entregas)
    assert len(entregues) == 3
    for entrega, item in zip(entregues, itens):
        assert entrega["file_name"] == nome_do_clipe(item.minuto)
        assert entrega["mime"] == "video/mp4"
        assert entrega["data"]() == item.caminho.read_bytes()
        assert callable(entrega["on_click"])


def test_AC_025_3_clipe_baixado_mostra_check(data_dir):
    sessao(data_dir, clipes=tres_clipes(data_dir))
    at = abre_a_interface()
    assert rotulos(at).count(ROTULO_DO_CLIPE) == 3

    # É o que o `on_click` grava na aba depois do acionamento.
    at.session_state["clipes_baixados"] = {f"{chave_do_resultado(data_dir)}:2"}
    at = at.run()

    clipes = [r for r in rotulos(at) if r in (ROTULO_DO_CLIPE, "✓")]
    assert clipes == [ROTULO_DO_CLIPE, "✓", ROTULO_DO_CLIPE]
    assert ROTULO_DO_ZIP in rotulos(at)


def test_AC_025_4_zip_contem_exatamente_os_clipes_listados(data_dir, entregas):
    itens = tres_clipes(data_dir)
    sessao(data_dir, clipes=itens)

    abre_a_interface()

    entrega = entrega_do_zip(entregas)
    assert entrega["file_name"] == "000013_clipes.zip"
    assert entrega["mime"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(entrega["data"]())) as arquivo:
        assert arquivo.namelist() == [nome_do_clipe(m) for m in (1, 2, 3)]
        for item in itens:
            assert arquivo.read(nome_do_clipe(item.minuto)) == item.caminho.read_bytes()


def test_AC_025_4_zip_baixado_marca_o_zip_e_todos_os_clipes(data_dir):
    sessao(data_dir, clipes=tres_clipes(data_dir))
    at = abre_a_interface()

    at.session_state["zip_baixado"] = chave_do_resultado(data_dir)
    at = at.run()

    assert "✓ Baixado" in rotulos(at)
    assert ROTULO_DO_ZIP not in rotulos(at)
    assert rotulos(at).count("✓") == 3
    assert ROTULO_DO_CLIPE not in rotulos(at)


def test_AC_025_4_marcas_nao_passam_para_a_sessao_seguinte(data_dir):
    sessao(data_dir, clipes=tres_clipes(data_dir))
    at = abre_a_interface()
    at.session_state["zip_baixado"] = chave_do_resultado(data_dir)
    at.session_state["clipes_baixados"] = {f"{chave_do_resultado(data_dir)}:1"}
    at = at.run()
    assert rotulos(at).count("✓") == 3

    nova = INICIO + timedelta(hours=1)
    a = AnotadorDoEstado(
        data_dir,
        pid=os.getpid(),
        id_camera="000013",
        nome_camera="Praça Exemplo",
        duracao_pedida=3,
        iniciada_em=nova,
        agora=lambda: nova + timedelta(minutes=5),
        manter_videos=True,
    )
    a.iniciar()
    planilha = data_dir / "000013_20260907_0800_2min.xlsx"
    a.terminar(
        Fase.CONCLUIDA,
        id_sessao=ID_SESSAO,
        status="COMPLETA",
        planilha=str(planilha),
        clipes=tuple(clipe(data_dir, m) for m in (1, 2, 3)),
    )
    at = at.run()

    assert rotulos(at).count(ROTULO_DO_CLIPE) == 3
    assert ROTULO_DO_ZIP in rotulos(at)
    assert "✓" not in rotulos(at)
    assert "✓ Baixado" not in rotulos(at)


def test_AC_025_5_clipe_ausente_nao_e_listado_e_a_tela_avisa(data_dir, entregas):
    itens = tres_clipes(data_dir)
    itens[1].caminho.unlink()
    sessao(data_dir, clipes=itens)

    at = abre_a_interface()

    assert "Clipes · 2 arquivos · 2,5 MB" in textos(at)
    assert [w.value for w in at.warning if "em disco" in w.value] == [
        "1 clipes não estão mais em disco."
    ]
    assert [e["file_name"] for e in entregas_de_clipe(entregas)] == [
        nome_do_clipe(1),
        nome_do_clipe(3),
    ]
    with zipfile.ZipFile(io.BytesIO(entrega_do_zip(entregas)["data"]())) as arquivo:
        assert arquivo.namelist() == [nome_do_clipe(1), nome_do_clipe(3)]


def test_AC_025_5_todos_ausentes_mostra_so_o_aviso(data_dir, entregas):
    itens = tres_clipes(data_dir)
    for item in itens:
        item.caminho.unlink()
    sessao(data_dir, clipes=itens)

    at = abre_a_interface()

    assert "3 clipes não estão mais em disco." in [w.value for w in at.warning]
    assert "Clipes ·" not in textos(at)
    assert entregas_de_clipe(entregas) == []
    assert not [e for e in entregas if e.get("file_name", "").endswith(".zip")]
    assert rotulos(at) == ["Baixar .xlsx"]


def test_AC_024_3_sem_a_opcao_mostra_clipes_nao_mantidos(data_dir, entregas):
    sessao(data_dir, manter_videos=False)

    at = abre_a_interface()

    assert MENSAGEM_NAO_MANTIDOS in [i.value for i in at.info]
    assert entregas_de_clipe(entregas) == []
    assert rotulos(at) == ["Baixar .xlsx"]
    assert "Clipes ·" not in textos(at)


@pytest.mark.parametrize(
    "fase", [Fase.PROCESSAMENTO_CANCELADO, Fase.SEM_PLANILHA, Fase.FALHOU, None]
)
def test_AC_025_6_cancelada_sem_planilha_e_falhou_nao_mostram_lista(
    data_dir, entregas, fase
):
    itens = tres_clipes(data_dir)
    if fase is None:  # processo morto, sem desfecho gravado
        sessao(data_dir, fase=Fase.FALHOU, clipes=itens, pid=2**22 + 777)
    else:
        sessao(data_dir, fase=fase, clipes=itens)

    at = abre_a_interface()

    assert not at.exception
    assert entregas_de_clipe(entregas) == []
    assert not [e for e in entregas if e.get("file_name", "").endswith(".zip")]
    assert "Clipes ·" not in textos(at)
    assert MENSAGEM_NAO_MANTIDOS not in [i.value for i in at.info]
    assert not [w for w in at.warning if "em disco" in w.value]


def test_downloads_usam_dado_adiado(data_dir, entregas):
    sessao(data_dir, clipes=tres_clipes(data_dir))

    abre_a_interface()

    mp4 = entregas_de_clipe(entregas)
    assert len(mp4) == 3
    assert all(callable(e["data"]) for e in mp4)
    assert callable(entrega_do_zip(entregas)["data"])


def test_AC_025_6_sessao_cancelada_na_captura_nao_mostra_lista(data_dir, entregas):
    """Mesmo com "Manter clipes" ligado: os clipes foram apagados (AC-012.7)."""
    itens = tres_clipes(data_dir)
    sessao(data_dir, fase=Fase.SESSAO_CANCELADA, clipes=itens)

    at = abre_a_interface()

    assert not at.exception
    assert entregas_de_clipe(entregas) == []
    assert not [e for e in entregas if e.get("file_name", "").endswith(".zip")]
    assert "Clipes ·" not in textos(at)
    assert MENSAGEM_NAO_MANTIDOS not in [i.value for i in at.info]

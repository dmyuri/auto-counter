"""Manifest da sessão em disco — T-06.

Critérios cobertos, de `.spec/features/captura-clipes/spec.md`:

- AC-003.1 — há exatamente N clipes distintos gravados em disco, cada um
  associado ao seu número de minuto, ao seu ETag e ao seu Last-Modified.
- AC-003.4 — início e fim do período da sessão vêm do Last-Modified do
  primeiro e do último clipe **efetivamente capturados**, e não do relógio
  local no início do comando.

Implementa também SUP-009 (o relógio local é gravado à parte, apenas como
diagnóstico) e SUP-012 (os clipes ficam em `<data_dir>/sessions/<id_sessao>/`).

Nenhum teste aqui toca a rede nem grava dentro do repositório: tudo acontece em
`tmp_path`, e o manifest é sempre relido do disco para que a afirmação seja
sobre o arquivo, não sobre o objeto em memória.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from auto_counter.capture.manifest import (
    NOME_DO_MANIFEST,
    ManifestDaSessao,
    diretorio_da_sessao,
    id_da_sessao,
    ler,
    nome_do_arquivo_do_minuto,
)
from auto_counter.capture.status import StatusDaSessao, classificar

ID_CAMERA = "000013"

RELOGIO_DO_COMANDO = datetime(2026, 9, 7, 15, 0, 0, tzinfo=timezone.utc)
"""Relógio local no instante do comando. Só nomeia o diretório (D-5)."""


def last_modified(minuto: int) -> datetime:
    """Last-Modified do clipe do minuto `minuto`, na referência do servidor.

    Deslocado de propósito em relação a `RELOGIO_DO_COMANDO`: AC-003.4 exige
    que o período saia daqui, e um teste em que os dois coincidissem não
    conseguiria distinguir um do outro.
    """
    return datetime(2026, 9, 7, 14, 30, 0, tzinfo=timezone.utc) + timedelta(
        minutes=minuto
    )


def manifest_novo(tmp_path, *, duracao_pedida: int = 5) -> ManifestDaSessao:
    """Uma sessão recém-criada no layout de SUP-012, dentro de `tmp_path`."""
    id_sessao = id_da_sessao(ID_CAMERA, RELOGIO_DO_COMANDO)
    return ManifestDaSessao.criar(
        diretorio_da_sessao(tmp_path, id_sessao),
        id_sessao=id_sessao,
        id_camera=ID_CAMERA,
        duracao_pedida=duracao_pedida,
    )


def capturar(manifest: ManifestDaSessao, minuto: int) -> None:
    """Registra o minuto `minuto` como capturado, com ETag próprio."""
    manifest.registrar_minuto(
        minuto,
        etag=f"etag-do-minuto-{minuto}",
        last_modified=last_modified(minuto),
        relogio_local=RELOGIO_DO_COMANDO + timedelta(minutes=minuto),
    )


def json_do_disco(manifest: ManifestDaSessao) -> dict:
    """Lê o `manifest.json` cru, para afirmar sobre o arquivo gravado."""
    return json.loads(manifest.caminho.read_text(encoding="utf-8"))


def test_AC_003_1_manifest_associa_cada_clipe_ao_minuto_ao_etag_e_ao_last_modified(
    tmp_path,
):
    """AC-003.1: cada clipe fica associado a minuto, ETag e Last-Modified.

    A associação é lida do arquivo em disco porque é ela a prova durável de
    AC-003.1 (D-3): sem manifest, os clipes preservados chegariam ao ground
    truth sem ETag nem referência de tempo.
    """
    manifest = manifest_novo(tmp_path, duracao_pedida=3)

    capturar(manifest, 2)

    dados = json_do_disco(manifest)
    (entrada,) = dados["minutos"]
    assert entrada["minuto"] == 2
    assert entrada["arquivo"] == "minuto-02.mp4"
    assert entrada["etag"] == "etag-do-minuto-2"
    assert entrada["last_modified"] == "2026-09-07T14:32:00+00:00"

    # SUP-009: o relógio local viaja à parte e marcado como diagnóstico.
    assert "relogio_local_diagnostico" in entrada
    assert entrada["relogio_local_diagnostico"] != entrada["last_modified"]

    # A leitura de volta é parte da entrega (persistencia-resultados e T-09
    # dependem dela) e tem de devolver os mesmos valores, com fuso.
    relido = ler(manifest.dir_sessao)
    (minuto,) = relido.minutos_capturados
    assert minuto.minuto == 2
    assert minuto.etag == "etag-do-minuto-2"
    assert minuto.last_modified == last_modified(2)


def test_AC_003_1_sessao_de_n_minutos_sem_falha_registra_n_entradas_distintas(
    tmp_path,
):
    """AC-003.1: N minutos sem falha → N entradas distintas no manifest.

    Distintas nos três eixos que a spec cita: número do minuto, ETag e nome de
    arquivo. Um ETag repetido virando duas entradas quebraria a exigência de
    clipes distintos, e dois minutos apontando para o mesmo arquivo fariam o
    mesmo vídeo contar duas vezes.
    """
    n = 5
    manifest = manifest_novo(tmp_path, duracao_pedida=n)

    for minuto in range(1, n + 1):
        capturar(manifest, minuto)
    manifest.fechar(classificar(n, []), duracao_real=n)

    dados = json_do_disco(manifest)
    assert len(dados["minutos"]) == n
    assert [entrada["minuto"] for entrada in dados["minutos"]] == [1, 2, 3, 4, 5]
    assert len({entrada["etag"] for entrada in dados["minutos"]}) == n
    assert [entrada["arquivo"] for entrada in dados["minutos"]] == [
        "minuto-01.mp4",
        "minuto-02.mp4",
        "minuto-03.mp4",
        "minuto-04.mp4",
        "minuto-05.mp4",
    ]

    assert dados["status"] == StatusDaSessao.COMPLETA.value
    assert dados["minutos_perdidos"] == []
    assert dados["duracao_pedida"] == n
    assert dados["duracao_real"] == n
    assert dados["encerrada_pelo_usuario"] is False


def test_AC_003_1_manifest_e_regravado_a_cada_minuto_resolvido(tmp_path):
    """AC-003.1: a escrita é incremental — não espera o fim da sessão.

    A URL não tem histórico: uma queda no minuto 12 não pode levar junto os 11
    minutos anteriores. Por isso cada minuto resolvido — capturado ou perdido —
    já aparece no arquivo antes do minuto seguinte começar.
    """
    manifest = manifest_novo(tmp_path, duracao_pedida=4)
    assert manifest.caminho.exists(), "o cabeçalho da sessão é gravado na criação"

    capturar(manifest, 1)
    assert len(json_do_disco(manifest)["minutos"]) == 1

    manifest.registrar_perda(2, motivo="o ETag não mudou dentro da janela")
    dados = json_do_disco(manifest)
    assert len(dados["minutos"]) == 1
    assert dados["minutos_perdidos"] == [
        {"minuto": 2, "motivo": "o ETag não mudou dentro da janela"}
    ]

    capturar(manifest, 3)
    assert len(json_do_disco(manifest)["minutos"]) == 2

    # E nenhum temporário da escrita atômica fica para trás no diretório.
    assert sorted(p.name for p in manifest.dir_sessao.iterdir()) == [NOME_DO_MANIFEST]


def test_AC_003_4_inicio_e_fim_vem_do_last_modified_do_primeiro_e_do_ultimo_clipe_capturado(
    tmp_path,
):
    """AC-003.4: o período da sessão é o Last-Modified do 1º e do último clipe."""
    manifest = manifest_novo(tmp_path, duracao_pedida=4)

    for minuto in range(1, 5):
        capturar(manifest, minuto)
    manifest.fechar(classificar(4, []), duracao_real=4)

    dados = json_do_disco(manifest)
    assert dados["inicio"] == "2026-09-07T14:31:00+00:00"
    assert dados["fim"] == "2026-09-07T14:34:00+00:00"

    relido = ler(manifest.dir_sessao)
    assert relido.inicio == last_modified(1)
    assert relido.fim == last_modified(4)


def test_AC_003_4_relogio_local_do_inicio_do_comando_nao_define_o_periodo_da_sessao(
    tmp_path,
):
    """AC-003.4: o relógio local do comando não entra no período (SUP-009).

    D-2 assume a consequência: o minuto 1 baixa o clipe que já está no
    servidor, então o início registrado pode cair até ~1 minuto **antes** do
    comando. Este teste fixa exatamente essa situação — se o código usasse o
    relógio local, o início nunca poderia ser anterior a ele.
    """
    manifest = manifest_novo(tmp_path, duracao_pedida=2)

    capturar(manifest, 1)
    capturar(manifest, 2)
    manifest.fechar(classificar(2, []), duracao_real=2)

    relido = ler(manifest.dir_sessao)
    assert relido.inicio < RELOGIO_DO_COMANDO
    assert relido.inicio == last_modified(1)
    assert relido.fim == last_modified(2)

    dados = json_do_disco(manifest)
    assert dados["inicio"] != RELOGIO_DO_COMANDO.isoformat()
    assert dados["fim"] != RELOGIO_DO_COMANDO.isoformat()


def test_AC_003_4_minuto_perdido_na_borda_nao_entra_no_periodo_da_sessao(tmp_path):
    """AC-003.4: perder a primeira ou a última borda encolhe o período.

    "Efetivamente capturados" é literal: com os minutos 1 e 5 perdidos, o
    período vai do Last-Modified do minuto 2 ao do minuto 4. Um período que
    ainda cobrisse 1..5 afirmaria vídeo que não existe em disco.
    """
    manifest = manifest_novo(tmp_path, duracao_pedida=5)

    manifest.registrar_perda(1, motivo="o ETag não mudou dentro da janela")
    for minuto in (2, 3, 4):
        capturar(manifest, minuto)
    manifest.registrar_perda(5, motivo="o clipe baixado não abriu como vídeo")
    manifest.fechar(classificar(5, [1, 5]), duracao_real=5)

    relido = ler(manifest.dir_sessao)
    assert relido.inicio == last_modified(2)
    assert relido.fim == last_modified(4)
    assert relido.status is StatusDaSessao.INVALIDA
    assert [perda.minuto for perda in relido.minutos_perdidos] == [1, 5]
    assert [perda.motivo for perda in relido.minutos_perdidos] == [
        "o ETag não mudou dentro da janela",
        "o clipe baixado não abriu como vídeo",
    ]


def test_AC_003_4_sessao_sem_nenhum_minuto_capturado_fica_com_periodo_nulo(tmp_path):
    """AC-003.4: sem clipe capturado não há de onde tirar início e fim.

    Nulo, e não o relógio local do comando: inventar um período a partir dele
    seria exatamente o que AC-003.4 proíbe.
    """
    manifest = manifest_novo(tmp_path, duracao_pedida=3)

    for minuto in (1, 2, 3):
        manifest.registrar_perda(minuto, motivo="o ETag não mudou dentro da janela")
    manifest.fechar(classificar(3, [1, 2, 3]), duracao_real=3)

    dados = json_do_disco(manifest)
    assert dados["inicio"] is None
    assert dados["fim"] is None

    relido = ler(manifest.dir_sessao)
    assert relido.inicio is None
    assert relido.fim is None


def test_AC_003_1_o_diretorio_da_sessao_segue_o_layout_e_o_id_de_d5(tmp_path):
    """AC-003.1 e SUP-012: `<data_dir>/sessions/<id_sessao>/`, id de D-5.

    O id é nome de diretório e nada mais (D-5): ele sai do relógio local, que
    AC-003.4 proíbe de virar referência de tempo da sessão.
    """
    id_sessao = id_da_sessao(ID_CAMERA, RELOGIO_DO_COMANDO)
    assert id_sessao == "000013-20260907T150000Z"

    dir_sessao = diretorio_da_sessao(tmp_path, id_sessao)
    assert dir_sessao == tmp_path / "sessions" / id_sessao

    manifest = manifest_novo(tmp_path)
    assert manifest.caminho == dir_sessao / NOME_DO_MANIFEST
    assert nome_do_arquivo_do_minuto(3) == "minuto-03.mp4"
    assert nome_do_arquivo_do_minuto(15) == "minuto-15.mp4"


def test_AC_003_1_minuto_repetido_no_manifest_e_erro_de_programacao(tmp_path):
    """AC-003.1: um número de minuto nunca recebe dois clipes.

    Sobrescrever silenciosamente faria a sessão declarar N entradas com menos
    de N clipes distintos em disco.
    """
    manifest = manifest_novo(tmp_path, duracao_pedida=3)
    capturar(manifest, 1)

    with pytest.raises(ValueError):
        capturar(manifest, 1)

    with pytest.raises(ValueError):
        manifest.registrar_perda(1, motivo="o ETag não mudou dentro da janela")

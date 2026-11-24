"""Descarte dos vídeos ao fim da sessão — T-09.

Critério coberto, de `.spec/features/captura-clipes/spec.md`:

- AC-003.5 — sessão cujo processamento terminou e que foi executada **sem** a
  opção de manter os vídeos não deixa nenhum arquivo de vídeo em disco; com a
  opção ativa, todos os clipes permanecem no diretório da sessão.

Implementa também SUP-012: a opção de preservar é explícita na linha de comando
e **desligada por padrão**, e a decisão fica gravada no manifest, para que quem
encerra a sessão depois do processamento não dependa do comando original.

O manifest **não é arquivo de vídeo**: ele sobrevive ao descarte, porque é nele
que vivem o status e a lista de minutos perdidos de que AC-007.4 e AC-008.4
dependem.

Nada aqui toca a rede e nada é gravado dentro do repositório: tudo acontece em
`tmp_path`.
"""

from datetime import datetime, timedelta, timezone

from auto_counter.capture.cleanup import (
    descartar_videos,
    encerrar_videos_da_sessao,
)
from auto_counter.capture.manifest import (
    NOME_DO_MANIFEST,
    ManifestDaSessao,
    diretorio_da_sessao,
    id_da_sessao,
    ler,
    nome_do_arquivo_do_minuto,
)
from auto_counter.capture.status import classificar

ID_CAMERA = "000013"

RELOGIO_DO_COMANDO = datetime(2026, 9, 7, 15, 0, 0, tzinfo=timezone.utc)
"""Relógio local no instante do comando. Só nomeia o diretório (D-5)."""


def last_modified(minuto: int) -> datetime:
    """Last-Modified do clipe daquele minuto, na referência do servidor."""
    return datetime(2026, 9, 7, 14, 30, 0, tzinfo=timezone.utc) + timedelta(
        minutes=minuto
    )


def sessao_capturada(tmp_path, *, minutos: int = 3, manter_videos: bool = False):
    """Uma sessão já capturada e fechada, com os `.mp4` de verdade em disco.

    Os arquivos têm bytes quaisquer: o descarte é sobre o arquivo, não sobre o
    conteúdo — quem julga se o vídeo é legível é T-05, na captura.
    """
    id_sessao = id_da_sessao(ID_CAMERA, RELOGIO_DO_COMANDO)
    manifest = ManifestDaSessao.criar(
        diretorio_da_sessao(tmp_path, id_sessao),
        id_sessao=id_sessao,
        id_camera=ID_CAMERA,
        duracao_pedida=minutos,
        manter_videos=manter_videos,
    )
    for minuto in range(1, minutos + 1):
        arquivo = manifest.dir_sessao / nome_do_arquivo_do_minuto(minuto)
        arquivo.write_bytes(b"bytes do clipe do minuto %d" % minuto)
        manifest.registrar_minuto(
            minuto,
            etag=f'"etag-{minuto}"',
            last_modified=last_modified(minuto),
            relogio_local=RELOGIO_DO_COMANDO + timedelta(minutes=minuto),
        )
    manifest.fechar(
        classificar(minutos, [minuto.minuto for minuto in manifest.minutos_perdidos]),
        duracao_real=minutos,
    )
    return manifest


def videos_em(dir_sessao):
    """Os arquivos de vídeo que sobraram no diretório da sessão."""
    return sorted(caminho.name for caminho in dir_sessao.glob("*.mp4"))


def test_AC_003_5_sem_a_opcao_de_manter_os_videos_nenhum_arquivo_de_video_permanece(
    tmp_path,
):
    """Padrão desligado (SUP-012): o encerramento apaga todos os `.mp4`."""
    manifest = sessao_capturada(tmp_path, minutos=3, manter_videos=False)

    apagados = encerrar_videos_da_sessao(manifest.dir_sessao)

    assert apagados == 3
    assert videos_em(manifest.dir_sessao) == []


def test_AC_003_5_com_a_opcao_ativa_todos_os_clipes_permanecem_no_diretorio_da_sessao(
    tmp_path,
):
    """Com a preservação gravada no manifest, nada é apagado.

    A decisão é lida do manifest, e não do comando original: quem encerra a
    sessão depois do processamento não tem mais os argumentos da linha de
    comando à mão.
    """
    manifest = sessao_capturada(tmp_path, minutos=3, manter_videos=True)

    apagados = encerrar_videos_da_sessao(manifest.dir_sessao)

    assert apagados == 0
    assert videos_em(manifest.dir_sessao) == [
        nome_do_arquivo_do_minuto(1),
        nome_do_arquivo_do_minuto(2),
        nome_do_arquivo_do_minuto(3),
    ]
    assert ler(manifest.dir_sessao).manter_videos is True


def test_AC_003_5_o_manifest_da_sessao_sobrevive_ao_descarte_dos_videos(tmp_path):
    """O manifest não é vídeo: status e minutos perdidos continuam legíveis.

    AC-007.4 e AC-008.4 dependem dessa informação **depois** do descarte, então
    apagar o manifest junto com os `.mp4` inviabilizaria as duas.
    """
    manifest = sessao_capturada(tmp_path, minutos=2, manter_videos=False)

    descartar_videos(manifest.dir_sessao)

    assert (manifest.dir_sessao / NOME_DO_MANIFEST).exists()
    relido = ler(manifest.dir_sessao)
    assert relido.status is manifest.status
    assert relido.duracao_real == 2
    assert [item.minuto for item in relido.minutos_capturados] == [1, 2]

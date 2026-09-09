"""Identidade de conteúdo de um clipe — T-12.

Critério coberto, de `.spec/features/captura-clipes/spec.md`:

- AC-004.7 — clipe cujo conteúdo é byte a byte igual ao do anterior não abre um
  minuto novo. Esta tarefa entrega só a **identidade de conteúdo** de que aquele
  critério depende; quem a usa para recusar o clipe é T-13.

Implementa SUP-051: a identidade de conteúdo é o sha256 dos bytes baixados,
porque o ETag identifica o recurso no servidor e não o arquivo — na sessão
`000013-20260908T050407Z` o mesmo vídeo chegou com dois ETags diferentes.

Nenhum teste aqui toca a rede: os arquivos são escritos em `tmp_path`.
"""

import hashlib

from auto_counter.capture.content import PEDACO_DE_LEITURA, sha256_do_arquivo


def test_AC_004_7_dois_arquivos_de_conteudo_igual_tem_o_mesmo_sha256(tmp_path):
    """AC-004.7: o que decide a igualdade é o conteúdo, não o nome nem a data.

    É o caso da sessão real: dois arquivos gravados em momentos diferentes, com
    nomes de minuto diferentes, e os mesmos bytes dentro.
    """
    conteudo = b"os mesmos bytes servidos duas vezes"
    primeiro = tmp_path / "minuto-01.mp4"
    segundo = tmp_path / "minuto-02.mp4"
    primeiro.write_bytes(conteudo)
    segundo.write_bytes(conteudo)

    assert sha256_do_arquivo(primeiro) == sha256_do_arquivo(segundo)

    # E conteúdo diferente precisa dar hash diferente, senão a comparação de
    # T-13 recusaria clipe legítimo.
    terceiro = tmp_path / "minuto-03.mp4"
    terceiro.write_bytes(conteudo + b" com um veiculo a mais")
    assert sha256_do_arquivo(terceiro) != sha256_do_arquivo(primeiro)


def test_AC_004_7_sha256_de_arquivo_maior_que_o_pedaco_de_leitura_e_correto(tmp_path):
    """AC-004.7: o clipe tem ~32 MB e é lido em pedaços, não de uma vez.

    O arquivo do teste passa do tamanho do pedaço de leitura de propósito: uma
    implementação que só hasheasse o primeiro pedaço passaria em tudo o mais e
    falharia aqui.
    """
    conteudo = bytes(range(256)) * ((PEDACO_DE_LEITURA // 256) + 3)
    assert len(conteudo) > PEDACO_DE_LEITURA

    clipe = tmp_path / "minuto-01.mp4"
    clipe.write_bytes(conteudo)

    assert sha256_do_arquivo(clipe) == hashlib.sha256(conteudo).hexdigest()

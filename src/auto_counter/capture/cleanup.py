"""Descarte dos vídeos de uma sessão — T-09.

Comportamento em `.spec/features/captura-clipes/spec.md`:

- AC-003.5 — sessão cujo processamento terminou e que foi executada **sem** a
  opção de manter os vídeos não deixa nenhum arquivo de vídeo em disco; com a
  opção ativa, todos os clipes permanecem no diretório da sessão.

Implementa SUP-012: a opção de preservar é explícita na linha de comando e vem
**desligada por padrão**; a decisão fica gravada no manifest, para que quem
encerra a sessão depois do processamento saiba o que fazer sem depender dos
argumentos do comando original.

**Quem chama isto não é o comando de captura.** AC-003.5 fala em sessão "cujo
processamento terminou", e AC-007.4 de `contagem-veiculos` registra que a
contagem tem de terminar antes do descarte. Enquanto `contagem-veiculos` não
existir, apagar no fim da captura destruiria o material antes de qualquer
processamento — então o comando de captura apenas grava a flag no manifest, e é
o encerramento da sessão que chama `encerrar_videos_da_sessao`. **É aqui que
`contagem-veiculos` deve ligar o descarte**, depois de contar.

O `manifest.json` **não é arquivo de vídeo** e nunca é apagado por estas
funções: é nele que vivem o status e a lista de minutos perdidos de que AC-007.4
e AC-008.4 dependem depois que os `.mp4` já sumiram. O diretório da sessão
também permanece.
"""

from pathlib import Path

from auto_counter.capture import manifest as manifest_da_sessao

EXTENSOES_DE_VIDEO = (".mp4",)
"""O que conta como "arquivo de vídeo" para AC-003.5.

Os clipes são gravados como `.mp4` (T-06, `nome_do_arquivo_do_minuto`), e a
captura não transcodifica nem recomprime nada (§Fora de escopo da spec), então
não há outro formato para aparecer no diretório da sessão.
"""


def descartar_videos(dir_sessao: str | Path) -> int:
    """Apaga os arquivos de vídeo do diretório da sessão e diz quantos apagou.

    Descarte incondicional: quem decide **se** deve apagar é
    `encerrar_videos_da_sessao`, que lê a decisão gravada no manifest.

    Só os vídeos vão embora — o `manifest.json`, qualquer outro arquivo e o
    próprio diretório continuam onde estão. Diretório inexistente, ou arquivo
    que sumiu entre a listagem e o `unlink`, não é erro: o resultado desejado
    (o vídeo não está mais lá) já vale, e uma exceção aqui derrubaria o
    encerramento da sessão por causa de algo que já estava certo.
    """
    diretorio = Path(dir_sessao)
    if not diretorio.is_dir():
        return 0

    apagados = 0
    for caminho in sorted(diretorio.iterdir()):
        if not caminho.is_file() or caminho.suffix.lower() not in EXTENSOES_DE_VIDEO:
            continue
        try:
            caminho.unlink()
        except FileNotFoundError:
            continue
        apagados += 1
    return apagados


def encerrar_videos_da_sessao(dir_sessao: str | Path) -> int:
    """Aplica a decisão de preservação gravada no manifest (AC-003.5).

    Lê `manter_videos` do manifest da sessão: ativa, nenhum clipe é apagado e o
    retorno é zero; desligada — o padrão de SUP-012 —, todos os vídeos são
    descartados. A decisão vem do arquivo, e não de um parâmetro, justamente
    porque o encerramento acontece depois do processamento, quando a linha de
    comando que iniciou a sessão não existe mais.
    """
    manifest = manifest_da_sessao.ler(dir_sessao)
    if manifest.manter_videos:
        return 0
    return descartar_videos(manifest.dir_sessao)

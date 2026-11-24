# Feature: download-clipes

## Contexto

Hoje os vídeos de uma sessão só ficam em disco quando ela é disparada pela linha
de comando com `--keep-clips` (SUP-012 de `captura-clipes`). A interface nunca
passa essa opção, pela D-13 do `_tasks.md` de `interface-sessao`: "o usuário faz
três coisas, e manter vídeo não é uma delas". Ao fim de toda sessão iniciada
pela interface, os vídeos são apagados (AC-003.5).

O protótipo `Contagem de Veiculos.html` muda isso em dois pontos:

- no painel de Configuração, a seção "02 · Saída" tem a opção "Manter clipes de
  vídeo", com o texto "Salva os trechos processados para download ao final. A
  planilha .xlsx é sempre gerada.";
- no painel de resultados, quando a opção estava ligada, aparece a lista dos
  clipes da sessão, cada um com o seu botão de download, e um botão para baixar
  todos num `.zip`.

O que muda é o acesso a uma opção que o sistema já tinha. Manter vídeos tem um
custo que a decisão precisa levar em conta: uma sessão de 15 min ocupa ~480 MB,
e os clipes mostram placas e pessoas. É justamente por isso que
`persistencia-resultados` não guarda imagem nenhuma, e é por isso que a opção
vem desligada (Q-017).

Esta feature cobre só as sessões da câmera ao vivo. No upload, a opção não
aparece, porque o usuário já tem os arquivos originais (Q-022 de
`processamento-upload`).

## Histórias

US-024 — Escolher manter os clipes ao iniciar a sessão
Como integrante do projeto de extensão, quero decidir, antes de iniciar, se os
vídeos da sessão ficam guardados, para poder revê-los ou reprocessá-los sem
precisar do terminal.

Critérios de aceite:
  AC-024.1 — Dado uma aba recém-aberta com a fonte "Câmera ao vivo", quando a
  interface é exibida, então a opção "Manter clipes de vídeo" aparece desligada,
  com o texto "Salva os trechos processados para download ao final. A
  planilha .xlsx é sempre gerada."

  AC-024.2 — Dado a opção ligada ao iniciar, quando a sessão iniciada pela
  interface termina com o processamento concluído, então todos os clipes
  capturados permanecem no diretório da sessão, como em AC-003.5 com a opção
  ativa, mesmo que a aba tenha sido fechada durante a sessão.

  AC-024.3 — Dado a opção desligada ao iniciar, quando a sessão iniciada pela
  interface termina com o processamento concluído, então nenhum arquivo de vídeo
  dela permanece em disco, como em AC-003.5 sem a opção, e o resultado informa
  "Clipes não foram mantidos nesta sessão."

  AC-024.4 — Dado uma sessão em andamento ou um resultado exibido, quando a
  interface é consultada, então a opção não pode ser alterada.

  AC-024.5 — Dado a fonte "Fazer upload de vídeos" marcada, quando a interface é
  exibida, então a opção "Manter clipes de vídeo" não aparece.

US-025 — Baixar os clipes no resultado
Como integrante do projeto de extensão, quero baixar os clipes da sessão pela
interface, um a um ou todos juntos, para guardá-los fora do diretório de dados
ou mostrá-los a alguém.

Critérios de aceite:
  AC-025.1 — Dado uma sessão concluída com a opção ligada e k clipes capturados,
  quando o resultado é exibido, então o painel de resultados lista exatamente k
  clipes, um por minuto capturado e em ordem de minuto. Cada linha tem o nome, a
  duração em MM:SS e o tamanho em MB. O título da lista é
  "Clipes · k arquivos · X MB", com X igual à soma dos tamanhos.

  AC-025.2 — Dado uma sessão com minutos perdidos na captura (AC-004.5,
  AC-004.6), quando a lista é exibida, então nenhum minuto perdido aparece nela.

  AC-025.3 — Dado um clipe listado, quando o usuário aciona o download dele,
  então o arquivo entregue é byte a byte igual ao clipe em disco, tem o nome de
  SUP-077 e o botão daquele clipe passa a mostrar "✓", pela regra de SUP-073 de
  `layout-interface`.

  AC-025.4 — Dado a lista com k clipes, quando o usuário aciona
  "Baixar todos (.zip)", então o arquivo `.zip` entregue contém exatamente os k
  clipes, com os mesmos nomes de AC-025.3 e conteúdo byte a byte igual ao de cada
  um. O botão passa a mostrar "✓ Baixado" e todos os botões individuais passam a
  mostrar "✓", pela regra de SUP-073 de `layout-interface`.

  AC-025.5 — Dado uma sessão concluída com a opção ligada em que j dos k clipes
  já não estão em disco, quando o resultado é exibido, então só os k − j
  presentes são listados e incluídos no `.zip`, e a interface informa que j
  clipes não estão mais em disco.

  AC-025.6 — Dado uma sessão cancelada pelo usuário na captura (AC-012.7), com
  processamento cancelado (AC-012.5), sem planilha (AC-012.6) ou que falhou,
  quando o resultado é exibido, então nenhuma lista de clipes nem botão de
  `.zip` é exibido.
  > **Alterado em 2026-11-14:** "Dado uma sessão com processamento cancelado
  > (AC-012.5), sem planilha (AC-012.6) ou que falhou, quando o resultado é
  > exibido, então nenhuma lista de clipes nem botão de `.zip` é exibido."
  > Motivo: na sessão cancelada na captura (AC-012.7 de `interface-sessao`), os
  > clipes são apagados mesmo com a opção ligada, então não há o que listar.

## Fora de escopo

- Manter ou baixar os vídeos de uma sessão de upload.
- Assistir aos clipes dentro da interface.
- Clipes com as caixas de detecção ou a linha de contagem desenhadas.
- Escolher quais minutos manter: a opção vale para a sessão inteira.
- Baixar os clipes de uma sessão anterior à última, ou de uma sessão iniciada
  pelo terminal.
- Apagar pela interface os clipes mantidos.
- Descarte automático dos clipes mantidos por prazo.
- Gravar na planilha se os clipes foram mantidos.

## Suposições

- [x] SUP-076 — A opção é repassada ao processo da sessão como a mesma flag
  `--keep-clips` de `session run` (D-2 de `interface-sessao`). A interface não
  tem regra própria de descarte (SUP-038), e é por isso que fechar a aba não
  muda o resultado. Revoga a D-13 daquele `_tasks.md`. Afeta AC-024.2 e
  AC-024.3.
- [x] SUP-077 — Cada clipe é baixado com o nome `<id_camera>_<AAAAMMDD>_<HHMM>.mp4`,
  como no protótipo. A data e a hora vêm do Last-Modified do clipe, convertidas
  para o horário de Brasília, como em SUP-033. Se dois clipes da mesma sessão
  caírem no mesmo minuto de relógio, o segundo recebe o sufixo `_2`, o terceiro
  `_3` e assim por diante, para que nenhum nome se repita dentro do `.zip`.
  Confirmado pelo autor. Afeta AC-025.3 e AC-025.4.
- [x] SUP-078 — Removida na revisão de 2026-11-07: a formatação do tamanho e da
  duração dos clipes não mudava o resultado.
- [x] SUP-079 — A lista só aparece na sessão concluída, inclusive quando a
  captura foi encerrada pelo usuário (AC-003.6). Na sessão cancelada no
  processamento, os vídeos ficam em disco seja qual for a opção, mas ficam para
  `session process` (AC-012.5), não para download. Na sessão sem planilha e na
  que falhou não há resultado ao qual os clipes se refiram. Confirmado pelo
  autor. Afeta AC-025.6. A captura encerrada pelo usuário que chega a ter lista
  é só a interrompida por Ctrl+C no terminal (AC-003.6). Pelo botão da
  interface, a sessão é cancelada e os clipes são apagados mesmo com a opção
  ligada (AC-012.7), então não há lista.
- [x] SUP-080 — A escolha feita ao iniciar é gravada no estado da sessão
  (`sessao_atual.json`). A interface lê esse campo para saber se mostra a lista
  ou o aviso de AC-024.3, e não abre o manifest da captura, por causa da D-9 de
  `interface-sessao`. Afeta AC-024.3 e AC-025.1.
- [x] SUP-081 — Removida na revisão de 2026-11-07: repetia SUP-073 de
  `layout-interface`, que AC-025.3 e AC-025.4 passaram a citar direto.

## Perguntas em aberto

Nenhuma pendente. Os IDs permanecem como histórico das decisões.

- [x] Q-017 — A opção "Manter clipes de vídeo" vem ligada ou desligada?
  **Respondida: desligada.** É o mesmo padrão da linha de comando (SUP-012):
  nenhum vídeo com placa ou pessoa fica em disco sem que alguém peça, e o disco
  não enche com sessões que ninguém vai rever. A alternativa, ligada como no
  protótipo, guardaria ~480 MB por sessão por padrão. Virou AC-024.1.

## Specs afetadas

Revisado história por história.

- `interface-sessao`
  - Contexto, "o usuário faz três coisas": passa a haver uma quarta, decidir se
    os vídeos ficam guardados. A D-13 do `_tasks.md` daquela feature é revogada
    por SUP-076.
  - AC-012.3: o resultado da sessão concluída ganha a lista de clipes
    (AC-025.1).
  - AC-012.5: não muda. O cancelamento no processamento mantém os vídeos seja
    qual for a opção, e a lista não aparece nesse caso (AC-025.6).
  - AC-012.7: o cancelamento na captura apaga os clipes mesmo com a opção
    ligada, e a lista não aparece (AC-025.6). AC-024.2 não é contrariado,
    porque vale só para sessão com o processamento concluído.
- `captura-clipes`
  - SUP-012: a opção de manter vídeos deixa de existir só na linha de comando.
    Na interface ela também vem desligada (AC-024.1), então o padrão é o
    mesmo nos dois caminhos.
  - AC-003.5: não muda, e é o que AC-024.2 e AC-024.3 aplicam.
  - AC-003.6: a sessão encerrada pelo usuário na captura tem lista de clipes
    (SUP-079). Isso só ocorre pelo Ctrl+C no terminal, porque pela interface a
    sessão é cancelada (AC-012.7).
- `persistencia-resultados`
  - Contexto, "Os vídeos são apagados ao fim da sessão" e o motivo de
    privacidade para não guardar imagem: a exceção já existia pela flag, mas
    passa a estar a um clique, para qualquer usuário da interface. Com a opção
    desligada por padrão, guardar vídeo continua exigindo um pedido explícito.
  - Fora de escopo, "Descarte automático de sessões antigas por prazo": os
    clipes mantidos também não têm descarte automático.
- `contagem-veiculos`
  - D-5 do `_tasks.md` daquela feature: só uma sessão com vídeos mantidos pode
    ser reprocessada. A interface passa a poder produzir sessões
    reprocessáveis.
- `layout-interface`
  - AC-023.2: a lista de clipes fica no mesmo painel "Sessão finalizada",
    abaixo do cartão da planilha.
  - AC-023.3 e SUP-073: AC-025.3 e AC-025.4 usam a mesma regra para a marca
    "✓".
  - AC-023.5 e AC-023.6: a opção fica indisponível com o resultado na tela e
    volta com o valor anterior depois de "Nova sessão".
- `upload-videos`
  - AC-026.2: a opção não aparece com a fonte de upload (AC-024.5).
- `processamento-upload`
  - AC-030.6: a sessão de upload sempre apaga a cópia dos vídeos ao fim da
    sessão concluída, e não tem lista de clipes.
- `validacao-acuracia`
  - SUP-050: os clipes de referência passam a poder ser obtidos também pela
    interface, mas o fluxo continua o mesmo. Nenhum critério muda.
- `exportacao-xlsx` — nenhum critério muda. Revisado: a planilha não registra a
  opção (Fora de escopo), e AC-010.7 continua valendo sem os vídeos.
- `configuracao-camera` e `acompanhamento-ao-vivo` — nenhum critério muda.
  Revisado: esta feature não usa linha, rótulos, quantidades nem tempo.

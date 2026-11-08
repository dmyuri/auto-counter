# Feature: layout-interface

## Contexto

O protótipo `Contagem de Veiculos.html`, na raiz do repositório, define a nova
aparência da interface. Ele é uma simulação em React com números sorteados, e
serve de referência visual e de comportamento, não de código: a interface
continua em Streamlit, que é a stack do README, e continua sendo só a casca
sobre a camada de aplicação (SUP-038 de `interface-sessao`).

A tela passa a ter três painéis:

- **Configuração** — fonte, câmera, duração, saída e o botão principal.
- **Ao vivo** — total, quantidades por categoria com participação, taxa, tempo
  decorrido, tempo estimado e progresso.
- **Resultados** — aparece quando a sessão termina, com a planilha para
  baixar.

Um cabeçalho mostra o estado do sistema e alterna entre os temas claro e escuro.

Esta feature muda como a sessão é mostrada e operada. As fases, a trava de
sessão única, o encerramento e os números contados continuam os mesmos. O modo
de upload e a opção de manter clipes, que ficam no mesmo painel de
Configuração, são das features `upload-videos` e `download-clipes`.

Itens do protótipo que esta feature não segue, de propósito:

- **Contagem subindo durante a captura.** Captura e processamento continuam
  separados (`captura-clipes`), e a captura continua sem quantidades (AC-016.5).
- **Três categorias.** O sistema conta quatro (`contagem-veiculos`), com moto.
- **Nome da planilha `sessao_<câmera>_<carimbo>.xlsx`.** Vale o SUP-032 de
  `exportacao-xlsx`.
- **Tempo em HH:MM:SS.** Vale o MM:SS de SUP-057.
- **"Restante" calculado pelo tempo simulado.** Aqui é "Tempo estimado",
  previsto pelo orçamento de processamento (SUP-070).
- **Câmera online ou offline.** Retirado da lista por decisão do autor.
- **Prévia capturada da câmera.** A prévia é uma imagem fixa indicada para cada
  câmera (SUP-066).
- **Botão "Usar vídeos de exemplo".** Só existe na simulação.

## Histórias

US-019 — Ver o estado do sistema no cabeçalho e escolher o tema
Como integrante do projeto de extensão, quero ver no topo da tela se o sistema
está parado, capturando, processando ou terminado, e escolher entre tema claro e
escuro, para entender a situação de relance e usar a tela em qualquer ambiente.

Critérios de aceite:
  AC-019.1 — Dado nenhuma sessão em andamento e nenhum resultado exibido,
  quando a interface é consultada, então o cabeçalho mostra o indicador
  "Aguardando".

  AC-019.2 — Dado uma sessão em andamento iniciada pela interface, quando a
  interface é consultada, então o cabeçalho mostra "Capturando" na fase de
  captura e "Processando" na fase de processamento.

  AC-019.3 — Dado uma sessão em andamento iniciada pelo terminal, quando a
  interface é consultada, então o cabeçalho mostra "Em andamento".

  AC-019.4 — Dado o resultado de uma sessão exibido no painel de resultados,
  quando a interface é consultada, então o cabeçalho mostra "Finalizado".

  AC-019.5 — Dado uma aba recém-aberta, quando a interface é exibida, então ela
  aplica o tema escuro e o botão de tema oferece "Tema claro".

  AC-019.6 — Dado o tema escuro, quando o usuário aciona o botão de tema, então
  a interface passa a aplicar o tema claro e o botão passa a oferecer "Tema
  escuro"; acionar de novo volta ao tema escuro. A troca não altera a câmera
  selecionada, a duração nem a sessão em andamento.

US-020 — Escolher a câmera por cartões com prévia
Como integrante do projeto de extensão, quero escolher a câmera vendo o id, o
nome do local e uma imagem dela, para ter certeza de que estou analisando a via
certa.

Critérios de aceite:
  AC-020.1 — Dado um registro com N câmeras válidas, quando a interface é
  aberta, então ela apresenta exatamente N cartões, um por câmera, cada um com o
  id e o nome do local, e nenhum campo para digitar id, URL ou endereço de
  câmera.

  AC-020.2 — Dado uma câmera cuja configuração indica uma imagem de prévia, e
  essa imagem abre, quando o cartão é exibido, então ele mostra essa imagem.
  Quando a configuração não indica imagem, ou quando o arquivo indicado não
  existe ou não abre, o cartão mostra "sem prévia" no lugar da imagem e a câmera
  continua selecionável. Em nenhum dos casos a interface acessa a câmera para
  obter a prévia.

  AC-020.3 — Dado os cartões exibidos sem sessão em andamento, quando o usuário
  aciona um cartão, então aquela câmera passa a ser a única marcada como
  "SELECIONADA", e é ela que a sessão usa ao ser iniciada.

  AC-020.4 — Dado uma aba recém-aberta, quando os cartões são exibidos, então a
  primeira câmera do registro aparece selecionada.
  > **Alterado por:** feature `nova-camera`, em 2026-11-08.
  > O critério continua valendo sem mudança de texto, mas a câmera selecionada
  > numa aba recém-aberta passa a ser a 000012, que tem o menor id do registro,
  > e não mais a 000013 (AC-032.3 e Q-025).
  > Ver `.spec/features/nova-camera/spec.md`.

  AC-020.5 — Dado uma sessão em andamento ou um resultado exibido, quando a
  interface é consultada, então nenhum cartão pode ser acionado e a câmera
  selecionada não muda.

  AC-020.6 — Dado um registro sem nenhuma câmera válida, quando a interface é
  aberta, então nenhum cartão é exibido, a interface informa que não há câmera
  disponível e o botão de iniciar fica indisponível.

US-021 — Definir a duração com atalhos
Como integrante do projeto de extensão, quero escolher as durações mais comuns
com um clique, para iniciar a sessão sem digitar.

Critérios de aceite:
  AC-021.1 — Dado a interface sem sessão em andamento, quando o usuário aciona um
  dos atalhos "5 min", "10 min" ou "15 min", então a duração passa a esse valor
  e só esse atalho aparece destacado.

  AC-021.2 — Dado uma duração digitada entre 1 e 15 que não é 5, 10 nem 15,
  quando a interface é exibida, então nenhum atalho aparece destacado e a sessão
  é iniciada com o valor digitado.

  AC-021.3 — Dado uma sessão em andamento ou um resultado exibido, quando a
  interface é consultada, então o campo de duração e os atalhos ficam
  indisponíveis.

US-022 — Acompanhar a sessão no painel ao vivo
Como integrante do projeto de extensão, quero ver a participação de cada
categoria, o ritmo do fluxo, quanto já foi feito e quando a sessão deve
terminar, para avaliar o resultado e me planejar enquanto a sessão roda.

Critérios de aceite:
  AC-022.1 — Dado uma sessão em andamento iniciada pela interface, quando a
  interface é consultada, então o painel ao vivo tem o título
  "Contagem ao vivo · <nome do local da câmera>".

  AC-022.2 — Dado uma sessão em processamento com quantidades exibidas
  (AC-016.2) e total T, quando a interface é consultada, então cada uma das
  quatro categorias mostra a participação q/T × 100, arredondada ao inteiro mais
  próximo com meio para cima, com o sinal "%", e uma barra proporcional a essa
  participação; com T = 0, todas mostram "0%".

  AC-022.3 — Dado uma sessão em processamento com k ≥ 1 minutos já concluídos com
  dado e V veículos aceitos nesses k minutos, quando a interface é consultada,
  então ela exibe V/k com uma casa decimal seguido de "veíc/min"; com k = 0, ou na
  fase de captura, exibe "— veíc/min".

  AC-022.4 — Dado uma sessão em andamento com R de M minutos resolvidos na fase
  atual, quando a interface é consultada, então ela exibe "P% concluído", com
  P = ⌊R/M × 100⌋, e a barra de progresso na mesma proporção. Na captura,
  R é a soma de capturados e perdidos e M é a duração pedida. No processamento,
  R é o número de minutos analisados e M é o número de minutos a processar.

  AC-022.5 — Dado uma sessão em captura com duração pedida de N minutos,
  iniciada em T0, com L minutos perdidos até ali e consultada no instante T,
  quando a interface é consultada, então ela exibe "Tempo estimado" igual a
  max(0, N × 60 s − (T − T0)) + (N − L) × 80 s, truncado ao segundo, no formato
  MM:SS.

  AC-022.6 — Dado uma sessão em processamento com P de M minutos analisados, em
  que o minuto em análise começou a ser processado no instante Tm, consultada
  no instante T, quando a interface é consultada, então ela exibe "Tempo
  estimado" igual a max((M − P − 1) × 80 s, (M − P) × 80 s − (T − Tm)), truncado
  ao segundo, no formato MM:SS; com P = M, exibe "00:00".

  AC-022.7 — Dado uma sessão em captura, quando a interface é consultada, então o
  painel ao vivo não mostra nenhuma participação nem barra de categoria, e mostra
  o aviso de AC-016.5.

US-023 — Encerrar e conferir o resultado no painel de resultados
Como integrante do projeto de extensão, quero parar a sessão pelo mesmo painel em
que a iniciei, ver o resultado separado da configuração e começar outra quando
quiser, para não confundir a sessão que terminou com a próxima.

Critérios de aceite:
  AC-023.1 — Dado uma sessão em andamento iniciada pela interface, quando a
  interface é consultada, então o botão de iniciar não aparece e, no lugar dele,
  aparece "Parar antecipadamente". Acioná-lo pede confirmação com o aviso da fase
  atual. Só a confirmação encerra a sessão, e encerra pelas regras de AC-003.6 na
  captura e de AC-012.5 no processamento.

  AC-023.2 — Dado uma sessão concluída com planilha, quando o resultado é
  exibido, então o painel "Sessão finalizada" mostra:
  - "Concluída · MM:SS", com o tempo total de AC-018.1, ou
    "Interrompida pelo usuário · MM:SS" quando a sessão registra encerramento
    pelo usuário (AC-003.6);
  - o cartão da planilha, com o nome do arquivo de AC-010.1, o texto
    "N registros · contagem por categoria e por minuto", em que N é o número de
    eventos gravados da sessão, e o botão "Baixar .xlsx".

  AC-023.3 — Dado o cartão da planilha exibido, quando o usuário aciona
  "Baixar .xlsx", então o arquivo entregue é o mesmo de AC-012.3 e o botão passa
  a mostrar "✓ Baixado" enquanto aquele resultado estiver na tela.

  AC-023.4 — Dado o resultado de uma sessão com processamento cancelado
  (AC-012.5), sem planilha (AC-012.6) ou que falhou (AC-018.3, AC-018.4), quando
  o resultado é exibido, então o painel de resultados mostra a mensagem daquele
  desfecho e nenhum cartão de planilha.

  AC-023.5 — Dado um resultado exibido, enquanto "Nova sessão" não for acionado,
  quando a interface é consultada, então o botão de iniciar não aparece, os
  controles de configuração ficam indisponíveis e aparece o botão
  "Nova sessão".

  AC-023.6 — Dado um resultado exibido, quando o usuário aciona "Nova sessão",
  então o painel de resultados some, o cabeçalho volta a "Aguardando", os
  controles de configuração voltam a ficar disponíveis com a câmera e a duração
  da sessão anterior, e o botão de iniciar volta. O registro da sessão no banco e
  a planilha em disco não mudam.

  AC-023.7 — Dado que "Nova sessão" foi acionado numa aba, quando a interface é
  aberta numa aba nova, sem que outra sessão tenha começado, então o resultado
  da última sessão volta a ser exibido.

## Fora de escopo

- Contar veículos durante a captura, como o protótipo simula.
- Indicar se a câmera está online ou offline, e bloquear câmera por isso.
- Capturar, atualizar ou gerar a prévia pela interface, e mostrar o vídeo da
  câmera ao vivo.
- Guardar a escolha de tema entre uma abertura da interface e outra.
- Verificar, por teste, cores, fontes, espaçamentos ou disposição dos painéis:
  os critérios verificam textos, estados e valores, e o protótipo é a
  referência visual.
- Quantidades por sentido, por minuto ou em gráfico na tela, como já excluído
  em `acompanhamento-ao-vivo`. As barras de participação mostram a proporção do
  total, não uma série.
- Formato de tempo com horas (HH:MM:SS).
- Corrigir o tempo estimado pela velocidade medida da máquina: a previsão usa
  sempre o orçamento (SUP-070).

## Suposições

- [x] SUP-062 — A interface continua em Streamlit, e o visual do protótipo é
  aplicado com CSS injetado pela própria aplicação sobre os componentes
  nativos. As cores dos dois temas são as variáveis `--bg`, `--panel`,
  `--accent` e as demais definidas no protótipo. Os testes verificam o tema pelo
  conjunto de variáveis injetado, e não pela cor renderizada. Afeta AC-019.5 e
  AC-019.6.
- [x] SUP-063 — O protótipo tem três estados no cabeçalho (Aguardando,
  Processando, Finalizado) porque não tem fase de captura. Aqui são cinco:
  "Aguardando", "Capturando", "Processando", "Em andamento" (sessão do terminal,
  sobre a qual a interface não tem progresso) e "Finalizado". Confirmado pelo
  autor. Afeta AC-019.1 a AC-019.4.
- [x] SUP-064 — O tema padrão é o escuro, como no protótipo. A escolha vale para
  a aba aberta e não é gravada em disco: a interface só lê do disco (SUP-058), e
  guardar preferência visual não justifica gravar. Confirmado pelo autor. Afeta
  AC-019.5 e AC-019.6.
- [x] SUP-065 — Os cartões seguem a ordem do registro de câmeras, que é a ordem
  crescente de id, e a primeira dessa ordem vem selecionada. Confirmado pelo
  autor. Afeta AC-020.1 e AC-020.4.
- [x] SUP-066 — Conforme Q-016, a prévia é uma imagem fixa, que o mantenedor
  indica para cada câmera no campo opcional `preview` do YAML da câmera, com o
  caminho relativo ao diretório de configuração. A interface só exibe a imagem
  indicada: não captura frame, não desenha linha e não gera arquivo. O que a
  imagem mostra é escolha do mantenedor. A falta do campo, ou um caminho que
  não abre, não invalida a câmera (AC-001.2): o efeito é só "sem prévia". Afeta
  AC-020.2.
- [x] SUP-067 — O id aparece no cartão como texto, ao lado do nome do local,
  como no protótipo. Continua sem nenhum campo para digitar id, que é o que
  AC-011.1 proíbe. Confirmado pelo autor na revisão da lista de features. Afeta
  AC-020.1.
- [x] SUP-068 — Removida na revisão de 2026-11-07: não mudava o resultado. A
  regra de arredondamento está no próprio AC-022.2.
- [x] SUP-069 — A taxa é por minuto de vídeo, não por minuto de relógio. O
  protótipo divide o total pelo tempo decorrido, mas aqui o tempo decorrido
  inclui a captura e a velocidade da máquina, e o resultado não seria fluxo da
  via. O denominador são os minutos já concluídos com dado: o minuto em análise
  fica de fora para não inflar a taxa, e o minuto SEM_DADO também, porque não
  teve veículo medido. O processo da sessão grava no estado, a cada minuto
  concluído, os veículos acumulados até ali, e a interface só divide.
  Confirmado pelo autor. Afeta AC-022.3.
- [x] SUP-070 — Conforme a decisão do autor, o protótipo mostra "Restante" e a
  interface mostra "Tempo estimado": a previsão de quanto falta até o fim da
  sessão, calculada pelo orçamento de processamento, e não pela velocidade
  medida.
  - O orçamento por minuto de vídeo é de 80 s: 59,93 s × 10 frames analisados
    por segundo ≈ 600 frames × 133 ms (AC-005.4) = 79,8 s, arredondado para
    cima.
  - Na captura, o tempo estimado soma o que falta da duração pedida, contado de
    T0 (SUP-056), e 80 s por minuto que ainda vai ser processado. Minuto já
    perdido não entra, porque não vai ser processado.
  - No processamento, o tempo estimado é 80 s por minuto que falta, e o minuto
    em análise é descontado conforme o tempo passa. Se a análise passar dos
    80 s, o valor fica parado no estimado dos minutos seguintes, em vez de
    ficar negativo.
  - O processo da sessão grava no estado o instante Tm em que cada minuto
    começa a ser processado.

  O formato é o MM:SS de SUP-057. Afeta AC-022.4, AC-022.5 e AC-022.6.
- [x] SUP-071 — "Parar antecipadamente" é o novo rótulo de "Encerrar sessão", e
  a confirmação continua. O protótipo para com um clique, mas AC-012.4 exige
  ação explícita, e encerrar a captura custa minutos que não voltam. Confirmado
  pelo autor. Afeta AC-023.1.
- [x] SUP-072 — Removida na revisão de 2026-11-07: não mudava o resultado. A
  definição de "N registros" está no próprio AC-023.2.
- [x] SUP-073 — "✓ Baixado" registra que o botão foi acionado naquela aba. Não
  confirma que o navegador gravou o arquivo, porque o Streamlit não tem como
  saber. Afeta AC-023.3.
- [x] SUP-074 — "Nova sessão" dispensa o resultado só na aba em que foi
  acionado. Gravar a dispensa exigiria que a interface escrevesse estado em
  disco, o que ela não faz (SUP-058). Por isso, uma aba nova volta a mostrar o
  último resultado, até que outra sessão comece. Confirmado pelo autor. Afeta
  AC-023.6 e AC-023.7.
- [x] SUP-075 — Na sessão encerrada pelo usuário na captura, o texto é
  "Interrompida pelo usuário · MM:SS", com o tempo total da sessão. O protótipo
  mostra o instante da parada, mas aqui o processamento continua depois da
  parada, e o tempo que interessa é o da sessão inteira (AC-018.1). Confirmado
  pelo autor. Afeta AC-023.2.

## Perguntas em aberto

Nenhuma pendente. Os IDs permanecem como histórico das decisões.

- [x] Q-016 — De onde vem a imagem de prévia de cada câmera? **Respondida: de
  uma imagem fixa, cujo caminho o mantenedor indica para cada câmera.** Nada é
  capturado no momento. As alternativas descartadas foram baixar um clipe de
  cada câmera ao abrir a interface, reaproveitar o último frame baixado e gerar
  a prévia pelo comando de calibração. Virou SUP-066 e AC-020.2.

## Specs afetadas

Revisado história por história.

- `interface-sessao`
  - AC-011.1: a câmera deixa de ser identificada só pelo nome do local e passa a
    aparecer em cartão com id, nome e prévia (AC-020.1, AC-020.2). A proibição
    de campo para digitar id, URL ou endereço continua.
  - AC-011.2: a regra de 1 a 15 minutos continua. Os atalhos de AC-021.1 só
    escolhem valores dentro dela.
  - AC-011.3: reescrito para os cartões em AC-020.6, com o mesmo efeito.
  - AC-012.2: o progresso por fase continua e ganha percentual, tempo estimado,
    participação e taxa (AC-022.2 a AC-022.6).
  - AC-012.3: o resultado passa para o painel "Sessão finalizada", com
    "N registros" e a marca "✓ Baixado" (AC-023.2, AC-023.3). O download é o
    mesmo.
  - AC-012.4: o encerramento continua exigindo confirmação, agora pelo botão
    "Parar antecipadamente" (AC-023.1). Reabrir a interface continua
    reencontrando a sessão, e passa a reencontrar o último resultado mesmo
    depois de "Nova sessão" (AC-023.7).
  - AC-012.5 e AC-012.6: as mensagens vão para o painel de resultados, sem
    cartão de planilha (AC-023.4).
  - Comportamento sem critério próprio que muda: hoje o formulário de iniciar
    fica disponível logo depois do fim da sessão. Com AC-023.5, ele só volta
    depois de "Nova sessão".
  - Fora de escopo daquela spec, "Monitoramento contínuo, painel ao vivo das
    câmeras": continua valendo. A prévia é uma imagem fixa, e a interface não
    acessa a câmera para obtê-la (AC-020.2).
  - A cadência de 2 s (D-17 do `_tasks.md` daquela feature) continua, e é
    nela que o tempo estimado e a taxa se atualizam.
- `acompanhamento-ao-vivo`
  - Fora de escopo, "Estimativa de tempo restante ou previsão de término":
    **contradito** por AC-022.5 e AC-022.6, por decisão do autor.
  - AC-016.5: continua valendo, e AC-022.7 o reforça.
  - AC-017.1: o tempo decorrido e o formato MM:SS continuam.
  - SUP-058: o estado em disco ganha o instante Tm de cada minuto e os veículos
    acumulados por minuto concluído (SUP-069, SUP-070). A interface continua só
    lendo e formatando.
- `contagem-veiculos`
  - AC-005.4: o limite de 133 ms passa a ser também a base do tempo estimado
    (SUP-070). Se o orçamento for renegociado de novo, como prevê SUP-017, os
    80 s por minuto mudam junto. A gravação nova no estado é uma por minuto, e
    não por evento, então não pesa no laço por frame.
  - SUP-017: os 10 frames analisados por segundo entram na conta dos 80 s.
  - Nenhuma regra de detecção, rastreamento ou categoria muda.
- `configuracao-camera`
  - AC-001.1 e AC-001.2: o YAML da câmera ganha o campo opcional `preview`
    (SUP-066). Ele não é obrigatório: a falta do campo ou um caminho inválido
    não rejeita a câmera.
  - AC-002.1: não muda. O PNG de calibração continua sendo só instrumento do
    mantenedor, e a prévia é outra imagem, indicada à parte.
  - A tela clicável de calibração, fora de escopo lá, continua fora.
- `captura-clipes`
  - AC-003.6: é a origem do texto "Interrompida pelo usuário" de AC-023.2.
  - Nenhum outro critério muda: a prévia não faz download (AC-020.2).
- `persistencia-resultados`
  - Contexto e Fora de escopo, "Nenhuma imagem é persistida" e "Guardar
    imagens": a imagem de prévia não fica em tabela nem é gerada pelo sistema,
    mas é uma imagem da via que fica no diretório de configuração. Se esse
    diretório for versionado, a imagem vai para o repositório. Cabe ao
    mantenedor escolher uma imagem sem placa nem pessoa identificável.
  - AC-008.2: é a origem do "N registros" de AC-023.2.
- `exportacao-xlsx`
  - AC-010.1 e SUP-032: o nome exibido no cartão é o do arquivo gerado ali, e
    não o nome do protótipo. Nenhum critério muda.
- `validacao-acuracia` — nenhum critério muda. Revisado: a validação roda fora
  da interface.

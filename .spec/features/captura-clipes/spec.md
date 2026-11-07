# Feature: captura-clipes

## Contexto

A URL pública da NitTrans serve `last_video.mp4`: um único arquivo com o último
minuto de vídeo, substituído a cada minuto. Medições feitas na câmera 000013:
1280×720, 30 fps, H.264, 59,93 s de duração, ~32 MB por clipe. O servidor envia
`ETag` e `Last-Modified` a cada resposta, o que permite identificar clipe novo e
ordenar os clipes sem OCR do timestamp gravado na imagem.

Consequência que define esta feature: não existe histórico. Um clipe que não for
baixado dentro da sua janela de um minuto está perdido para sempre. Por isso a
sessão é dividida em duas fases e esta é a primeira: durante os N minutos
escolhidos o sistema só baixa: é a operação barata, e nada pode competir com ela
por CPU. O processamento (`contagem-veiculos`) só começa depois, lendo do disco.

Uma sessão de 15 minutos ocupa ~480 MB em disco enquanto dura.

Toda sessão termina com exatamente um de três status — COMPLETA, DEGRADADA ou
INVÁLIDA — e esse vocabulário é o mesmo no banco, na interface e no XLSX. O
status responde a uma pergunta estatística, não de esforço: se o resultado pode
ou não ser comparado ao de outra sessão.

## Histórias

US-003 — Capturar os clipes do período escolhido
Como integrante do projeto de extensão, quero que o sistema baixe os clipes de
um minuto da câmera escolhida durante a duração que eu definir, para ter o
material bruto daquele período.

Critérios de aceite:
  AC-003.1 — Dado uma câmera do registro e uma duração de N minutos com
  1 ≤ N ≤ 15, quando a captura termina sem falhas, então há exatamente N clipes
  distintos gravados em disco, cada um associado ao seu número de minuto, ao seu
  ETag e ao seu Last-Modified.
  > **Alterado por:** feature `processamento-upload`, em 2026-11-07.
  > Na sessão de upload não há clipe por minuto, ETag nem Last-Modified, e cada
  > vídeo enviado fica associado à sessão pela posição na lista, pelo sha256 e
  > pelos minutos que ocupa (AC-030.1).
  > Ver `.spec/features/processamento-upload/spec.md`.

  AC-003.2 — Dado que o servidor responde com o mesmo ETag da checagem anterior,
  quando o sistema verifica se há clipe novo, então não baixa o conteúdo
  novamente e aguarda a próxima checagem.

  AC-003.3 — Dado uma duração fora do intervalo de 1 a 15 minutos, quando a
  captura é solicitada, então é rejeitada com erro que cita o limite, antes de
  qualquer requisição ao servidor.
  > **Alterado por:** feature `upload-videos`, em 2026-11-07.
  > O limite de 1 a 15 minutos não se aplica à sessão de upload, que tem o
  > limite equivalente de 15 min de duração somada dos vídeos (AC-027.11).
  > Ver `.spec/features/upload-videos/spec.md`.

  AC-003.4 — Dado uma captura concluída, quando o período da sessão é registrado,
  então início e fim vêm do Last-Modified do primeiro e do último clipe
  efetivamente capturados, e não do relógio local no início do comando.
  > **Alterado por:** feature `processamento-upload`, em 2026-11-07.
  > Na sessão de upload, o período passa a ser o início e o término do
  > processamento no relógio local, marcado como "horário do processamento"
  > (AC-030.3 e SUP-100).
  > Ver `.spec/features/processamento-upload/spec.md`.

  AC-003.5 — Dado uma sessão cujo processamento terminou e que foi executada sem
  a opção de manter os vídeos, quando a sessão é encerrada, então nenhum arquivo
  de vídeo dela permanece em disco; com a opção ativa, todos os clipes
  permanecem no diretório da sessão.
  > **Alterado por:** feature `processamento-upload`, em 2026-11-07.
  > Na sessão de upload concluída, os vídeos enviados são sempre apagados,
  > porque o upload não tem a opção de mantê-los (AC-030.6 e SUP-097).
  > Ver `.spec/features/processamento-upload/spec.md`.

  AC-003.6 — Dado que o usuário interrompe explicitamente a captura no minuto k
  de N minutos pedidos, quando a sessão é encerrada, então a duração real da
  sessão passa a ser k, o status de AC-004.4 a AC-004.6 é calculado sobre k e não
  sobre N, o encerramento pelo usuário fica registrado na sessão e os k minutos
  já capturados seguem para processamento.

US-004 — Tolerar falha de captura sem invalidar a sessão inteira
Como integrante do projeto de extensão, quero que uma falha momentânea não jogue
fora os minutos já capturados e que o resultado diga exatamente o que faltou,
para eu saber se posso confiar naquele número.

Critérios de aceite:
  AC-004.1 — Dado que a requisição de um clipe falha por erro de rede, timeout ou
  resposta HTTP de erro, quando o sistema tenta obtê-lo, então repete até 3
  tentativas com espera crescente dentro da janela daquele minuto, e só depois
  marca o minuto como não capturado.

  AC-004.2 — Dado que o ETag não muda dentro da janela daquele minuto (o arquivo
  parou de ser atualizado no servidor), quando a janela se esgota, então o minuto
  é marcado como não capturado e a captura segue para o minuto seguinte, sem
  interromper a sessão.

  AC-004.3 — Dado um clipe baixado cujo conteúdo não abre como vídeo legível,
  quando o sistema o valida, então descarta o arquivo, marca o minuto como não
  capturado e a execução continua, sem exceção não tratada escapando para o
  usuário.

  AC-004.4 — Dado uma sessão de N minutos em que nenhum minuto foi perdido,
  quando a captura termina, então a sessão recebe status COMPLETA.
  > **Alterado por:** feature `processamento-upload`, em 2026-11-07.
  > Na sessão de upload, o minuto perdido passa a ser o minuto sem dado por
  > falha de leitura, com o mesmo limite (AC-030.4 e SUP-095).
  > Ver `.spec/features/processamento-upload/spec.md`.

  AC-004.5 — Dado uma sessão de N minutos com pelo menos um minuto perdido e no
  máximo 20% de N perdidos, quando a captura termina, então a sessão recebe
  status DEGRADADA e a lista dos números dos minutos perdidos fica registrada.
  > **Alterado por:** feature `processamento-upload`, em 2026-11-07.
  > Na sessão de upload, o minuto perdido passa a ser o minuto sem dado por
  > falha de leitura, com o mesmo limite (AC-030.4 e SUP-095).
  > Ver `.spec/features/processamento-upload/spec.md`.

  AC-004.6 — Dado uma sessão de N minutos com mais de 20% de N perdidos, quando a
  captura termina, então a sessão recebe status INVÁLIDA e a lista dos números
  dos minutos perdidos fica registrada.
  > **Alterado por:** feature `processamento-upload`, em 2026-11-07.
  > Na sessão de upload, o minuto perdido passa a ser o minuto sem dado por
  > falha de leitura, com o mesmo limite (AC-030.4 e SUP-095).
  > Ver `.spec/features/processamento-upload/spec.md`.

  AC-004.7 — Dado um clipe baixado cujo conteúdo é byte a byte igual ao do clipe
  imediatamente anterior aceito na sessão, ainda que o ETag e o Last-Modified
  sejam diferentes, quando o sistema o valida, então descarta o arquivo, não o
  associa a nenhum minuto e continua checando dentro da janela daquele minuto;
  esgotada a janela sem conteúdo inédito, o minuto é marcado como não capturado,
  pela mesma regra de AC-004.2.

## Fora de escopo

- Buscar trechos passados: a URL só expõe o último minuto, então não existe
  seleção de data e hora, apenas duração a partir de agora.
- Capturar de mais de uma câmera ao mesmo tempo.
- Retomar uma sessão interrompida a partir do ponto em que parou: os minutos
  decorridos não voltam.
- Processar vídeo durante a fase de captura.
- Transcodificar, recomprimir ou reduzir a resolução dos clipes na captura.

## Suposições

- [x] SUP-008 — O sistema consulta o servidor a cada 10 s por requisição HEAD e
  considera clipe novo quando o ETag muda; a janela de espera de um clipe novo é
  de 90 s antes de declarar o minuto perdido, e as 3 tentativas de AC-004.1
  precisam caber nessa janela. Afeta AC-003.2, AC-004.1 e AC-004.2.
- [x] SUP-009 — A identidade de um clipe é o ETag e sua referência de tempo é o
  Last-Modified do servidor; o relógio local é gravado à parte apenas como
  informação de diagnóstico. A sessão real mostrou que o ETag identifica o
  **recurso**, não o **conteúdo**: ele pode mudar sem que o vídeo mude, e por
  isso SUP-051 acrescenta a comparação por conteúdo. A referência de tempo
  continua sendo o Last-Modified. Afeta AC-003.1 e AC-003.4.
- [x] SUP-011 — "Vídeo legível" significa que o arquivo abre no OpenCV e que o
  primeiro e o último frame são decodificáveis. Afeta AC-004.3.
- [x] SUP-012 — Os clipes ficam em `<data_dir>/sessions/<id_sessao>/` e a opção de
  preservá-los é uma flag explícita na linha de comando, desligada por padrão.
  Afeta AC-003.5.
- [x] SUP-013 — O limite de 20% é percentual puro sobre a duração da sessão, sem
  tolerância absoluta: em sessão curta uma única perda pode bastar para INVÁLIDA,
  e isso está correto, porque perder um terço do período realmente impede
  comparar aquele número com o de outra sessão. O denominador é N pedido, exceto
  quando o usuário interrompe de propósito, caso em que AC-003.6 substitui N pela
  duração real — desistência nunca cai nesta regra. Afeta AC-004.5 e AC-004.6.
- [x] SUP-051 — A identidade de **conteúdo** de um clipe é o sha256 dos bytes
  baixados, comparado apenas com o do clipe imediatamente anterior aceito na
  sessão. O ETag continua identificando o recurso no servidor (SUP-009), mas
  deixa de valer como prova de conteúdo inédito: a sessão
  `000013-20260908T050407Z` recebeu o mesmo vídeo nos minutos 1 e 2 com ETags
  diferentes (`6a9f969c-69cdbe` e `6a9f96d4-69cdbe`, mesma metade de tamanho),
  porque o servidor trocou o Last-Modified sem trocar o arquivo. O sha256 de
  cada clipe aceito passa a ser gravado no registro da sessão, ao lado do ETag e
  do Last-Modified de AC-003.1 — é campo novo em schema já commitado, então
  exige **versão nova do manifest**, conforme `CLAUDE.md`. Comparar só com o
  anterior é decisão do autor do projeto: repetição alternada (o clipe do minuto
  1 voltando no minuto 3) não é detectada, e isso é consequência aceita. Afeta
  AC-003.1 e AC-004.7.

## Perguntas em aberto

Nenhuma pendente. Os IDs permanecem como histórico das decisões.

- [x] Q-003 — O que acontece com os minutos já baixados quando o usuário
  interrompe a captura? **Respondida: viram uma sessão da duração real.** Pedir
  15 min e parar no 7 produz uma sessão de 7 minutos, com o status calculado
  sobre 7 e o encerramento pelo usuário registrado. Não foi criado um quarto
  status: o vocabulário de três continua valendo e a sessão ganha apenas um campo
  de encerramento em AC-008.1. Está em AC-003.6.

## Specs afetadas

Revisado história por história.

- `configuracao-camera` — nenhuma contradição: esta feature consome AC-001.1 e
  AC-001.4 sem alterá-los.
- `contagem-veiculos` — AC-007.4 depende diretamente do registro de minutos
  perdidos criado em AC-004.5 e AC-004.6: sem essa informação a deduplicação de
  emenda seria aplicada entre clipes que não são adjacentes. E AC-003.5 obriga
  a contagem a terminar antes do descarte dos vídeos. AC-004.7 é o que passa a
  sustentar o "clipes distintos" de AC-003.1: clipe repetido aceito faria a
  contagem registrar os mesmos veículos duas vezes, que é exatamente o que
  US-007 existe para evitar — e a janela de emenda não o impediria, porque a
  repetição cobre o clipe inteiro, não só os 2 s do corte.
- `persistencia-resultados` — AC-008.1 grava o status e os minutos perdidos
  definidos em AC-004.4 a AC-004.6 e, por causa de AC-003.6, passa a gravar
  também a duração real da sessão e a marca de encerramento pelo usuário;
  AC-008.4 depende da lista de minutos perdidos para distinguir minuto sem vídeo
  de minuto sem veículo.
- `exportacao-xlsx` — AC-010.5 exibe o status definido aqui, e AC-010.4 passa a
  imprimir a duração real e o encerramento pelo usuário vindos de AC-003.6.
- `interface-sessao` — AC-012.4 depende de AC-003.6 para o encerramento
  antecipado: fechar o navegador não interrompe nada, só ação explícita do
  usuário aciona esta regra.
- `validacao-acuracia` — AC-014.5 roda sem rede, sobre clipes preservados pela
  opção descrita em SUP-012, que é como os 3 clipes de referência são obtidos.

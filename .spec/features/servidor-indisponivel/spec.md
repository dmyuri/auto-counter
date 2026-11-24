# Feature: servidor-indisponivel

## Contexto

A captura consulta o servidor de vídeo da NitTrans por HEAD a cada 10 s, com
janela de 90 s por minuto (SUP-008 de `captura-clipes`). Às vezes o servidor
fica fora do ar, no início da sessão ou entre um minuto e outro.

Hoje o sistema não distingue "servidor fora do ar" de "servidor no ar, mas sem
clipe novo". Toda checagem que falha por rede, timeout ou HTTP de erro é tratada
como checagem sem clipe identificável (D-4 do `_tasks.md` de `captura-clipes`) e
o sistema espera a próxima. Esgotada a janela, o minuto é perdido com o mesmo
motivo de ETag parado (AC-004.2). A captura segue até o minuto N mesmo com o
servidor fora o tempo todo: numa sessão de 15 min, são ~22 min de espera. No fim
aparece um aviso genérico de sessão sem planilha, que não diz a causa. O motivo
gravado no manifest não fala de servidor, e nada disso chega à tela nem ao
terminal.

Esta feature faz três coisas:

1. distingue a falha do servidor das outras perdas;
2. encerra a captura quando o servidor fica fora por 2 minutos seguidos;
3. diz no resultado da sessão que a captura foi encerrada por servidor
   indisponível, e desde quando.

Os minutos já capturados seguem para a contagem. O status continua calculado
sobre a duração pedida, e o encerramento fica registrado na sessão. Durante a
captura não há aviso: "servidor indisponível" só aparece no resultado.

Vale para a sessão da câmera ao vivo, pela interface e pelo terminal. A sessão
de upload não consulta servidor e não é afetada.

## Histórias

US-033 — Encerrar a captura quando o servidor fica indisponível
Como integrante do projeto de extensão, quero que a captura pare quando o
servidor de vídeo fica fora do ar por 2 minutos seguidos, e que os minutos já
capturados sejam contados, para não esperar até o fim da duração por clipes que
não vão chegar e não perder o que já foi capturado.

Critérios de aceite:
  AC-033.1 — Dado uma checagem HEAD da captura, quando ela termina em erro de
  conexão (conexão recusada, falha de DNS ou de rede), em timeout ou em resposta
  HTTP de 500 a 599, então ela conta como falha de servidor; quando o servidor
  responde com qualquer outro código, inclusive 404, 403 ou 200, ela não conta
  como falha de servidor.

  AC-033.2 — Dado a janela de 90 s de um minuto em que todas as checagens são
  falha de servidor (AC-033.1), quando a janela se esgota, então o minuto é
  registrado no manifest como não capturado, com um motivo que contém
  "servidor indisponível" e é diferente do motivo de AC-004.2, e esse minuto
  conta como minuto com servidor indisponível.

  AC-033.3 — Dado a janela de um minuto em que pelo menos uma checagem não foi
  falha de servidor, quando o minuto é resolvido como capturado ou como perdido
  por qualquer regra de `captura-clipes`, então ele não conta como minuto com
  servidor indisponível e zera a sequência de minutos com servidor indisponível.

  AC-033.4 — Dado uma sessão de N minutos pedidos em que os minutos k−1 e k, com
  2 ≤ k < N, são minutos com servidor indisponível seguidos (AC-033.2), quando a
  janela do minuto k se esgota, então a captura encerra, nenhuma requisição é
  feita ao servidor depois disso, e cada minuto de k+1 a N é registrado no
  manifest como não capturado, com um motivo que contém "não tentado" e
  "servidor indisponível".

  AC-033.5 — Dado a captura encerrada por AC-033.4, AC-033.7 ou AC-033.10,
  quando o status da sessão é calculado, então a lista de minutos perdidos tem
  todos os minutos não capturados de 1 a N, inclusive os não tentados. O status
  de AC-004.4 a AC-004.6 é calculado sobre N pedido, a duração real registrada é
  N, o encerramento pelo usuário fica registrado como "não" e a sessão fica
  marcada como encerrada por servidor indisponível. Exemplo: N = 15, minutos 1 a
  3 capturados e 4 e 5 com servidor indisponível → perdidos 4 a 15 (12 de 15),
  status INVÁLIDA.

  AC-033.6 — Dado a captura encerrada por AC-033.4 ou AC-033.7 com pelo menos um
  minuto capturado, quando a sessão roda por `session run` ou pela interface,
  então os minutos capturados são contados e a sessão termina com planilha. Por
  `session capture`, os clipes capturados ficam no diretório da sessão e são
  aceitos por `session process`. A opção de manter os vídeos continua valendo
  como hoje (AC-003.5).

  AC-033.7 — Dado uma sessão de N ≥ 2 minutos pedidos em que os minutos N−1 e N
  são minutos com servidor indisponível seguidos, quando a janela do minuto N se
  esgota, então a captura termina e a sessão fica marcada como encerrada por
  servidor indisponível, como em AC-033.5, mesmo sem nenhum minuto não tentado.

  AC-033.8 — Dado o servidor indisponível desde o início de uma sessão de N ≥ 2
  minutos, com os minutos 1 e 2 sendo minutos com servidor indisponível, quando
  a captura encerra por AC-033.4 ou AC-033.7, então nenhum minuto é capturado, a
  sessão termina sem planilha (AC-012.6), com status INVÁLIDA e marcada como
  encerrada por servidor indisponível.

  AC-033.9 — Dado um minuto com servidor indisponível seguido de um minuto
  capturado ou perdido por outra regra (AC-033.3), e sem outros 2 minutos
  seguidos com servidor indisponível depois disso, quando a captura continua,
  então ela segue até o minuto N e a sessão não fica marcada como encerrada por
  servidor indisponível.

  AC-033.10 — Dado uma sessão de N = 1 minuto em que o único minuto é minuto com
  servidor indisponível, quando a janela dele se esgota, então o minuto é perdido
  com o motivo de AC-033.2, a sessão termina sem planilha (AC-012.6), com status
  INVÁLIDA e marcada como encerrada por servidor indisponível.

  AC-033.11 — Dado o minuto k−1 com servidor indisponível, quando o usuário
  encerra a captura durante a janela do minuto k, pelo botão "Parar
  antecipadamente" ou por Ctrl+C, então vale a regra de parada já existente
  (AC-012.7 ou AC-003.6) e a sessão não fica marcada como encerrada por servidor
  indisponível.

US-035 — Saber no fim que a captura foi encerrada por servidor indisponível
Como integrante do projeto de extensão, quero que o resultado da sessão diga que
a captura foi encerrada porque o servidor ficou indisponível, e desde quando,
para saber por que faltam minutos.

Critérios de aceite:
  AC-035.1 — Dado uma sessão iniciada no instante T0 (AC-017.1), com planilha e
  marcada como encerrada por servidor indisponível (AC-033.5), quando o
  resultado é exibido, então o painel "Sessão finalizada" mostra "Encerrada por
  servidor indisponível · MM:SS", com o tempo total de AC-018.1, no lugar de
  "Concluída · MM:SS". Abaixo vem o aviso "Servidor indisponível desde MM:SS da
  sessão; minutos perdidos: <lista>", e o cartão da planilha (AC-023.2)
  continua. Nesse aviso, MM:SS é o instante da primeira falha da sequência
  ininterrupta de falhas de servidor que levou ao encerramento, menos T0,
  truncado ao segundo, no formato de AC-017.1, e a lista é a de AC-033.5.

  AC-035.2 — Dado uma sessão sem planilha marcada como encerrada por servidor
  indisponível (AC-033.8 ou AC-033.10), quando o resultado é exibido, então o
  painel mostra o status, a informação de que não há planilha (AC-012.6) e o
  mesmo aviso de AC-035.1, sem botão de download.

  AC-035.3 — Dado uma sessão que não foi marcada como encerrada por servidor
  indisponível, mesmo com minutos perdidos por AC-033.2, quando o resultado é
  exibido, então o painel não mostra o texto nem o aviso de AC-035.1 e segue
  AC-023.2 e AC-023.4.

  AC-035.4 — Dado uma sessão por `session run` ou `session capture` marcada como
  encerrada por servidor indisponível, quando o comando termina, então o terminal
  imprime "servidor indisponível", o MM:SS de AC-035.1 e a lista dos minutos
  perdidos. O código de saída é o mesmo que o comando já usa para aquele
  desfecho, com ou sem planilha.

  AC-035.5 — Dado uma sessão em captura com minutos com servidor indisponível,
  antes de ela terminar, quando a interface é consultada ou a saída do terminal
  é lida, então nenhuma delas mostra "servidor indisponível".

US-036 — Registrar o encerramento por servidor indisponível
Como docente responsável pelo projeto, quero que a sessão encerrada por servidor
indisponível fique marcada no banco, na planilha e no histórico, para saber
depois por que aquela sessão é INVÁLIDA ao compará-la com outras.

Critérios de aceite:
  AC-036.1 — Dado uma sessão persistida, quando o registro dela é lido do banco,
  então ele tem a indicação de encerramento por servidor indisponível: "sim" para
  a sessão marcada por AC-033.5 e "não" para as outras. As sessões gravadas antes
  desta feature são lidas como "não".

  AC-036.2 — Dado uma sessão capturada por `session capture` e marcada como
  encerrada por servidor indisponível, quando ela é processada depois por
  `session process`, então a indicação de AC-036.1 continua "sim" no banco.

  AC-036.3 — Dado a aba Sessao da planilha (AC-010.4), quando a planilha é gerada,
  então ela traz a linha "encerrada por servidor indisponível" com "SIM" ou
  "NÃO", conforme AC-036.1, na mesma grafia da linha "encerrada pelo usuário".
  > **Alterado em 2026-11-15:** "Dado a aba Sessao da planilha (AC-010.4),
  > quando a planilha é gerada, então ela traz a linha "Encerrada por servidor
  > indisponível" com "sim" ou "não", conforme AC-036.1." Motivo: a aba usa
  > rótulo minúsculo e valor em maiúsculas ("encerrada pelo usuário" → "SIM" ou
  > "NÃO"), e a linha nova segue o mesmo padrão. Decidido pelo autor.

  AC-036.4 — Dado várias sessões gravadas, quando o histórico é listado
  (AC-009.2), então a linha da sessão marcada como encerrada por servidor
  indisponível contém "servidor indisponível", e a das outras sessões não.

## Fora de escopo

- Aviso de servidor indisponível durante a captura, na interface ou no terminal:
  "servidor indisponível" só aparece no resultado da sessão (Q-027).
- Checar o servidor antes de criar a sessão e recusar o início: o servidor fora
  no momento do clique segue a mesma regra (SUP-117).
- Mudar o botão "Parar antecipadamente" (AC-012.7 e AC-023.1) ou o Ctrl+C
  (AC-003.6): durante a falha do servidor, os dois continuam como hoje (SUP-127).
- Tratar 404, 403 ou outro 4xx como servidor indisponível, ou dar mensagem
  própria para câmera não encontrada ou acesso negado: esses casos seguem a regra
  atual (AC-004.2).
- Contar a falha do download (GET) depois de um HEAD com resposta como falha de
  servidor: ela segue AC-004.1, e o minuto dela não conta para a regra dos 2
  minutos.
- Mostrar na tela final o motivo dos minutos perdidos das sessões que não foram
  encerradas por servidor indisponível.
- Mudar a janela de 90 s, o intervalo de 10 s entre checagens ou as 3 tentativas
  de download (SUP-008 e AC-004.1).
- Retomar a captura quando o servidor volta depois do encerramento.
- Alerta fora da interface e do terminal (e-mail, notificação).
- Sessão de upload, que não consulta o servidor.
- Prévia e frame da câmera nos cartões (`configuracao-camera`, `nova-camera`).

## Suposições

- [x] SUP-112 — A captura encerra depois de 2 minutos seguidos com servidor
  indisponível, e não segue até o minuto N. Confirmado pelo autor. Afeta
  AC-033.4 e AC-033.7.
- [x] SUP-113 — Falha de servidor é erro de conexão, DNS, rede, timeout ou HTTP
  de 500 a 599. Um 404, 403 ou outro 4xx é resposta do servidor e segue a regra
  atual. Confirmado pelo autor. Afeta AC-033.1.
- [x] SUP-114 — Minuto com servidor indisponível é aquele em que todas as
  checagens da janela de 90 s foram falha de servidor. Uma única resposta, mesmo
  sem clipe novo, tira o minuto da conta e zera a sequência. Assim, uma câmera
  travada, com o servidor no ar e o ETag parado, não vira erro de servidor.
  Confirmado pelo autor. Afeta AC-033.2, AC-033.3 e AC-033.9.
- [x] SUP-115 — Os minutos já capturados seguem para a contagem e geram
  planilha, como no Ctrl+C (AC-003.6), e não são descartados. Confirmado pelo
  autor. Afeta AC-033.6.
- [x] SUP-116 — O status é calculado sobre a duração pedida, e os minutos não
  tentados entram na lista de perdidos, com motivo próprio. A duração real
  registrada é N. Calcular sobre os minutos que aconteceram faria uma sessão
  curta parecer DEGRADADA. Deixar os não tentados fora da lista faria 12 minutos
  sem vídeo valerem como 2 perdidos. Confirmado pelo autor. Afeta AC-033.4 e
  AC-033.5.
- [x] SUP-117 — O servidor fora do ar no momento do início segue a mesma regra
  dos 2 minutos, sem checagem prévia que recuse iniciar. Confirmado pelo autor.
  Afeta AC-033.8.
- [x] SUP-118 — Os 2 minutos seguidos com servidor indisponível também marcam a
  sessão quando são os dois últimos (N−1 e N), mesmo sem minuto cortado.
  Confirmado pelo autor. Afeta AC-033.7.
- [x] SUP-119 — Na sessão de 1 minuto, o único minuto com servidor indisponível
  basta para marcar a sessão como encerrada por servidor indisponível, embora
  não existam 2 minutos seguidos. É exceção à regra de SUP-112. Confirmado pelo
  autor. Afeta AC-033.10 e AC-035.2.
- [x] SUP-121 — O resultado informa o tempo decorrido da sessão (T − T0, mesmo
  relógio de AC-017.1) da primeira falha de servidor, e não o horário local nem
  o número do minuto. Confirmado pelo autor. Afeta AC-035.1.
- [x] SUP-122 — A sessão encerrada por servidor indisponível tem texto de
  desfecho próprio, "Encerrada por servidor indisponível · MM:SS", seguido do
  aviso "Servidor indisponível desde MM:SS da sessão; minutos perdidos:
  <lista>". Confirmado pelo autor. Afeta AC-035.1 e AC-035.2.
- [x] SUP-123 — A tela final só mostra o motivo das perdas na sessão encerrada
  por servidor indisponível. As outras sessões ficam como hoje. Confirmado pelo
  autor. Afeta AC-035.3.
- [x] SUP-124 — A regra vale também para `session run` e `session capture`. O
  terminal só informa o servidor indisponível no encerramento, sem código de
  saída novo, porque interface e terminal usam a mesma camada (SUP-038).
  Confirmado pelo autor. Afeta AC-035.4 e AC-035.5.
- [x] SUP-125 — O encerramento por servidor indisponível fica registrado no banco,
  na aba Sessao do XLSX, com a linha "Encerrada por servidor indisponível" e
  "sim" ou "não", e no histórico, e não só no manifest e na tela. Confirmado pelo
  autor. Afeta AC-036.1, AC-036.3 e AC-036.4.
  > **Corrigido em 2026-11-15:** na aba Sessao, a linha segue a grafia das
  > vizinhas: "encerrada por servidor indisponível", com "SIM" ou "NÃO"
  > (AC-036.3).
- [x] SUP-127 — A parada pelo usuário prevalece. Um minuto abandonado por parada
  não existe (AC-003.6), então não fecha a sequência de 2 minutos, e a sessão
  segue a regra da parada, sem a marca de servidor indisponível. Confirmado pelo
  autor. Afeta AC-033.11.
- [x] SUP-129 — O MM:SS do resultado é o da primeira falha da sequência
  ininterrupta de falhas de servidor que levou ao encerramento. Essa sequência
  pode ter começado antes da janela do primeiro minuto inteiro fora, e o MM:SS
  marca quando o servidor de fato parou de responder. Confirmado pelo autor.
  Afeta AC-035.1.

## Perguntas em aberto

Nenhuma pendente. Os IDs permanecem como histórico das decisões.

- [x] Q-027 — Com um aviso de servidor indisponível na tela durante a captura,
  apertar "Parar antecipadamente" apagaria os minutos já capturados (AC-012.7),
  enquanto esperar o encerramento automático os contaria. O botão deveria mudar?
  **Respondida: a pergunta deixou de existir.** O autor decidiu que não há aviso
  durante a captura: "servidor indisponível" só aparece no resultado da sessão
  encerrada por servidor indisponível. Sem o aviso na tela, não há o reflexo de
  apertar o botão por causa dele, e AC-012.7 continua como está. Decidido junto:
  - saiu a história do aviso ao vivo (US-034, com AC-034.1 a AC-034.6), e o ID
    não é reaproveitado;
  - saíram a suposição do aviso ao vivo (SUP-120) e os palpites que dependiam
    dele (SUP-128, SUP-130 e SUP-131);
  - AC-035.5 garante que nada mostra "servidor indisponível" antes do fim da
    sessão.

## Specs afetadas

Revisado história por história.

- `captura-clipes`
  - AC-004.2: deixa de valer sempre que a captura "segue para o minuto seguinte,
    sem interromper a sessão". Dois minutos seguidos com servidor indisponível
    encerram a captura (AC-033.4), e na sessão de 1 minuto o único minuto basta
    para marcar a sessão (AC-033.10). O minuto com servidor indisponível ganha
    motivo próprio, distinto do ETag parado (AC-033.2).
  - AC-004.4 a AC-004.6 e SUP-013: o denominador continua N pedido, mas a lista
    de perdidos passa a ter também minutos não tentados (AC-033.5). Isso não é
    desistência: SUP-013 não troca o denominador.
  - AC-003.6: a sessão passa a ter um segundo tipo de encerramento antes de N,
    distinto do encerramento pelo usuário. Esse fica "não" e a duração real fica
    N (AC-033.5). AC-033.11 mantém a precedência da parada pelo usuário.
  - D-4 do `_tasks.md`: o erro de rede, timeout e HTTP 5xx na checagem deixa de
    ir pelo mesmo caminho da checagem sem ETag ou Last-Modified (AC-033.1).
- `interface-sessao`
  - AC-012.1: no encerramento por servidor indisponível, os minutos não
    tentados entram de uma vez na contagem de perdidos, sem janela própria
    (AC-033.4).
  - AC-012.3 e AC-012.6: o resultado da sessão encerrada por servidor
    indisponível ganha texto e aviso próprios, com e sem planilha (AC-035.1,
    AC-035.2).
- `layout-interface`
  - AC-023.2: além de "Concluída · MM:SS" e "Interrompida pelo usuário · MM:SS",
    passa a existir "Encerrada por servidor indisponível · MM:SS", com aviso
    abaixo (AC-035.1).
  - AC-023.4: o resultado sem planilha da sessão encerrada por servidor
    indisponível mostra também o aviso (AC-035.2).
  - AC-022.4: no encerramento por servidor indisponível, os minutos não tentados
    entram em R como perdidos, e o progresso da captura vai a 100% antes de a
    fase mudar.
- `acompanhamento-ao-vivo`
  - AC-017.2: a passagem da captura para o processamento passa a acontecer
    também pelo encerramento por servidor indisponível, e o tempo continua
    medido a partir de T0.
  - AC-018.3: vale também para a sessão sem planilha encerrada por servidor
    indisponível, que mostra o tempo total, sem quantidades, além do aviso de
    AC-035.2.
- `persistencia-resultados`
  - AC-008.1: o registro da sessão ganha a indicação de encerramento por servidor
    indisponível (AC-036.1). Campo novo exige migration numerada.
  - AC-009.2: o histórico passa a mostrar essa marca (AC-036.4).
  - AC-008.4: os minutos não tentados aparecem como sem dado nos agregados, como
    qualquer minuto não capturado.
- `exportacao-xlsx`
  - AC-010.4: a aba Sessao ganha a linha "Encerrada por servidor indisponível"
    (AC-036.3).
  - AC-010.5: o percentual de minutos perdidos passa a incluir os minutos não
    tentados.
- `contagem-veiculos`
  - AC-007.4: comportamento mantido, com um caso novo. Os minutos não tentados
    entram na lista de perdidos, e a deduplicação de emenda não é aplicada entre
    clipes separados por eles.
- `download-clipes`
  - AC-025.1: comportamento mantido. A sessão com planilha encerrada por servidor
    indisponível é concluída e, com a opção ligada, lista os k clipes
    capturados.
  - AC-025.6: a sessão sem planilha encerrada por servidor indisponível cai
    neste critério, sem lista de clipes.
- `configuracao-camera`: sem efeito. A URL continua montada por AC-001.4 e
  AC-001.5, e o 404 de câmera removida não muda de tratamento (SUP-113).
- `nova-camera`: sem efeito. A câmera 000012 é capturada pelo mesmo laço e
  recebe a mesma regra, sem critério próprio alterado.
- `upload-videos` e `processamento-upload`: sem efeito. A sessão de upload não
  consulta o servidor, e AC-030.4 já define o minuto perdido do upload por
  falha de leitura.
- `validacao-acuracia`: sem efeito. AC-014.5 roda sem rede, sobre clipes
  preservados.

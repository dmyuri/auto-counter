# Feature: acompanhamento-ao-vivo

## Contexto

Hoje, enquanto a sessão processa, a interface mostra só a fase e quantos minutos
já foram analisados (AC-012.2 de `interface-sessao`). Numa sessão de 15 minutos,
o processamento leva até 20 min na máquina de referência (AC-005.4 de
`contagem-veiculos`). Durante esse tempo o usuário não vê nenhum número de
veículos: o primeiro só aparece quando ele abre a planilha.

Esta feature mostra, ao vivo e enquanto a sessão roda, duas informações:

- as quantidades de veículos já contados por categoria (carro, ônibus,
  caminhão, moto) e o total;
- o tempo decorrido da sessão, somando a captura dos vídeos e a contagem dos
  veículos.

Duas restrições de specs existentes definem o que "ao vivo" consegue entregar:

- **A contagem só existe no processamento.** A captura só baixa vídeo, e
  processar durante a captura está fora de escopo de `captura-clipes`. Então as
  quantidades só começam quando o processamento começa. O tempo começa a contar
  antes, porque inclui a captura.
- **A tela sobe a cada veículo, e só mostra o que vai ser gravado.** Os
  veículos aparecem à medida que cruzam a linha, e não em degraus a cada minuto
  processado, que seriam ~70 s com 1 frame analisado a cada 3 e 117,7 ms por
  frame (Q-012). Dois mecanismos de `contagem-veiculos` descartam um cruzamento
  depois que ele aconteceu, e cada um é tratado de um jeito:
  - A deduplicação da emenda (AC-007.1) descarta, no início de um clipe, o
    cruzamento que repete um do fim do clipe anterior. Quando o clipe seguinte
    começa, os eventos do fim do anterior já são conhecidos, então o filtro é
    aplicado antes de o cruzamento chegar à tela, e a duplicata nunca aparece
    (SUP-053).
  - Um clipe que falha no meio da leitura perde todos os eventos do minuto (D-4
    de `contagem-veiculos`). Os veículos desse minuto já apareceram na tela, e
    a tela os desconta (Q-014). É o único caso em que as quantidades diminuem.

Esta feature só mostra informação. Ela não muda o que é contado, o que é gravado
no banco nem o que vai para a planilha.

## Histórias

US-016 — Acompanhar as quantidades de veículos durante o processamento
Como integrante do projeto de extensão, quero ver quantos carros, ônibus,
caminhões e motos já foram contados, e o total, enquanto o processamento roda,
para acompanhar o resultado sem esperar a planilha.

Critérios de aceite:
  AC-016.1 — Dado uma sessão que acabou de passar da captura para o
  processamento, quando a interface é consultada antes de qualquer cruzamento
  ser aceito, então ela mostra as quantidades de carro, ônibus, caminhão, moto e
  total, todas iguais a zero.

  AC-016.2 — Dado uma sessão em processamento, quando um veículo cruza a linha e
  o evento é aceito, sem ser descartado pela deduplicação de emenda (AC-007.1)
  nem pelo limite de um evento por rastreio e sentido (AC-006.6), então, na
  consulta seguinte, a interface mostra a quantidade da categoria daquele evento
  e o total aumentados em 1, sem esperar o minuto terminar; e o total exibido é
  sempre a soma das quatro categorias.

  AC-016.3 — Dado um cruzamento no início de um clipe que a deduplicação de
  emenda descarta (AC-007.1), quando a interface é consultada antes, durante ou
  depois do processamento desse clipe, então esse cruzamento não aparece em
  nenhuma das quantidades; e, ao longo de toda a fase de processamento, as
  quantidades exibidas só diminuem de uma consulta para a seguinte no caso de
  AC-016.8.

  AC-016.4 — Dado uma sessão cujo processamento terminou e foi gravado, quando as
  quantidades da última atualização do processamento são comparadas com os
  eventos gravados no banco para aquela sessão, então a quantidade de cada
  categoria e o total são iguais.

  AC-016.5 — Dado uma sessão em captura, quando a interface é consultada, então
  nenhuma quantidade de veículos é exibida, nem mesmo zero, e a interface informa
  que a contagem começa quando a captura terminar.

  AC-016.6 — Dado um minuto marcado como não capturado, ou um clipe que não
  rende nenhum frame legível, quando esse minuto é resolvido no processamento,
  então as quantidades exibidas não mudam.

  AC-016.7 — Dado uma sessão em processamento, quando a interface é fechada e
  aberta de novo sem que nenhum evento seja aceito ou descontado nesse
  meio-tempo, então as quantidades exibidas são as mesmas de antes do
  fechamento.

  AC-016.8 — Dado um clipe que falha no meio da leitura depois de ter gerado
  eventos já exibidos, quando o sistema descarta os eventos desse minuto (D-4 de
  `contagem-veiculos`), então as quantidades de cada categoria e o total voltam
  ao valor que tinham antes de esse minuto começar a ser processado.
  > **Alterado por:** feature `processamento-upload`, em 2026-11-07.
  > Na sessão de upload, o desconto passa a ser só dos eventos do minuto em que
  > o vídeo falhou, mantidos os minutos já concluídos daquele vídeo (AC-028.9).
  > Ver `.spec/features/processamento-upload/spec.md`.

US-017 — Acompanhar o tempo decorrido da sessão
Como integrante do projeto de extensão, quero ver há quanto tempo a sessão está
rodando, somando captura e contagem, para saber quanto o sistema leva para
entregar o resultado.

Critérios de aceite:
  AC-017.1 — Dado uma sessão iniciada no instante T0 e em andamento, em captura
  ou em processamento, quando a interface é consultada no instante T, então ela
  exibe o tempo decorrido T − T0, truncado ao segundo, no formato MM:SS.

  AC-017.2 — Dado uma sessão que passa da captura para o processamento, pelo fim
  da duração pedida ou por encerramento antecipado (AC-003.6), quando a interface
  é consultada já no processamento, então o tempo exibido continua medido a
  partir de T0, sem voltar a zero.

  AC-017.3 — Dado uma sessão em andamento, quando a interface é consultada em dois
  instantes T1 e T2, então a diferença entre os dois tempos exibidos é T2 − T1,
  com tolerância de 1 s.

  AC-017.4 — Dado uma sessão em andamento, quando a interface é fechada e aberta
  de novo no instante T, então o tempo exibido é T − T0, e não o tempo desde a
  reabertura.

US-018 — Conferir as quantidades e o tempo finais no resultado
Como integrante do projeto de extensão, quero que, ao fim da sessão, as
quantidades finais e o tempo total continuem na tela junto ao resultado, para
não precisar abrir a planilha para saber o total nem perder quanto tempo a
sessão levou.

Critérios de aceite:
  AC-018.1 — Dado uma sessão concluída com planilha (AC-012.3), quando o usuário
  acessa o resultado, então a interface exibe as quantidades finais de carro,
  ônibus, caminhão, moto e total, iguais às dos eventos gravados no banco para
  aquela sessão, e o tempo total da sessão, igual ao instante de término menos
  T0, no formato de AC-017.1.

  AC-018.2 — Dado o resultado de uma sessão que exibe tempo total (AC-018.1 ou
  AC-018.3), quando a interface é consultada em dois instantes diferentes,
  inclusive depois de fechada e reaberta, então o tempo total exibido é o mesmo
  nas duas consultas.

  AC-018.3 — Dado uma sessão com processamento cancelado (AC-012.5), sem planilha
  (AC-012.6) ou terminada em falha registrada pelo próprio processo da sessão,
  quando o usuário acessa o resultado, então a interface exibe o tempo total da
  sessão, igual ao instante de término menos T0, e nenhuma quantidade de
  veículos.

  AC-018.4 — Dado uma sessão cujo processo terminou sem concluir, sem registrar
  desfecho, quando o usuário acessa o resultado, então a interface não exibe
  nenhuma quantidade de veículos nem tempo total.

## Fora de escopo

- Contar veículos durante a captura: a captura continua só baixando vídeo,
  conforme `captura-clipes`.
- Quantidades por sentido, por minuto ou em gráfico na tela.
- Estimativa de tempo restante ou previsão de término.
- Gravar o tempo da sessão no banco ou imprimi-lo na planilha. Isso mudaria
  AC-008.1 e AC-010.4 e exigiria migration nova.
- Mostrar quantidades e tempo na saída do terminal (`session run`,
  `session process`).
- Quantidades e tempo para uma sessão iniciada pelo terminal: a interface
  continua mostrando só que há uma sessão em andamento, sem progresso.
- Mudar o que é contado: as quantidades exibidas são as mesmas que vão para o
  banco, sem regra de contagem própria da tela.

## Suposições

- [x] SUP-053 — As quantidades mudam a cada evento aceito, conforme Q-012. A
  deduplicação de emenda e o limite de um evento por rastreio e sentido são
  avaliados quando o evento é gerado, e não depois do clipe inteiro: quando o
  clipe seguinte começa, os eventos do fim do anterior já são conhecidos. A
  categoria é decidida no cruzamento (SUP-023), então um veículo não muda de
  categoria depois de aparecer na tela. O resultado gravado é o mesmo da
  deduplicação feita depois do clipe inteiro. Afeta AC-016.2 e AC-016.3.
- [x] SUP-054 — O total é a soma das quatro categorias, e nenhuma quantidade é
  separada por sentido na tela: o briefing pede as categorias e o total, sem
  sentido. Afeta AC-016.2, AC-016.4 e AC-018.1.
- [x] SUP-055 — Durante a captura, o bloco de quantidades não aparece, nem com
  zeros, e no lugar dele aparece um aviso de que a contagem começa quando a captura
  terminar. Mostrar zero durante a captura seria lido como "nenhum veículo
  passou". Afeta AC-016.5.
- [x] SUP-056 — O tempo é um único cronômetro, sem parcial por fase. T0 é o
  instante em que o processo da sessão começa, logo depois do clique em
  **Iniciar sessão**. O término é o instante em que a sessão chega ao desfecho,
  já com gravação no banco e exportação incluídas. Os dois são medidos no relógio
  local da máquina. Esse relógio serve só para mostrar duração: o período real
  da sessão continua vindo do Last-Modified, conforme AC-003.4. Afeta AC-017.1,
  AC-017.2, AC-017.4 e AC-018.1.
- [x] SUP-057 — O formato é MM:SS, truncado ao segundo, e os minutos passam de 59
  sem virar hora (por exemplo, 75:03). Uma sessão de 15 min leva até ~35 min no
  orçamento atual, então não há hora a mostrar no uso normal. Afeta AC-017.1 e
  AC-018.1.
- [x] SUP-058 — Quantidades e tempo chegam à interface pelo mesmo estado em disco
  que o processo da sessão já grava para o progresso (`sessao_atual.json`), com
  T0, o término e as quantidades acumuladas. A interface só lê e formata, sem
  calcular contagem (SUP-038). O estado é regravado a cada evento aceito e a
  cada desconto de AC-016.8. A cadência de atualização da tela é a já
  existente, de 2 s, então um veículo aparece em até 2 s depois que seu evento é
  aceito. Afeta AC-016.2, AC-016.7, AC-016.8, AC-017.3, AC-017.4 e AC-018.2.
- [x] SUP-059 — Minuto perdido na captura e clipe que não rende nenhum frame
  legível não acrescentam veículo a nenhuma categoria. Afeta AC-016.6.
- [x] SUP-060 — Conforme Q-013 e Q-015:
  - Na sessão concluída, o resultado mostra as quantidades finais e o tempo
    total.
  - Na cancelada, na sem planilha e na terminada em falha registrada pelo
    próprio processo, mostra só o tempo total. Na cancelada nada foi gravado
    (AC-012.5), e na sem planilha os zeros seriam lidos como "nenhum veículo
    passou" (AC-012.6).
  - Quando o processo morre sem registrar desfecho, não mostra nem quantidades
    nem tempo, porque não há instante de término.

  Afeta AC-018.1, AC-018.2, AC-018.3 e AC-018.4.
- [x] SUP-061 — No desconto de AC-016.8, as quantidades voltam exatamente ao
  valor de antes do minuto que falhou, porque esse minuto passa a valer como
  "sem dado" e nenhum evento dele é gravado. Afeta AC-016.4 e AC-016.8.

## Perguntas em aberto

Nenhuma pendente. Os IDs permanecem como histórico das decisões.

- [x] Q-012 — As quantidades devem subir a cada minuto processado (a cada ~70 s)
  ou a cada veículo que cruza a linha? **Respondida: a cada veículo.** A
  duplicata da emenda é filtrada antes de chegar à tela (SUP-053), e o único
  caso de redução que sobra é o de Q-014. Viraram AC-016.2 e AC-016.3.
- [x] Q-013 — Quando a sessão termina, as quantidades finais e o tempo total
  continuam na tela junto ao resultado? **Respondida: sim, em todo desfecho.**
  O tempo total aparece em todo desfecho que registra instante de término, e as
  quantidades finais aparecem só na sessão concluída (SUP-060). Viraram AC-018.1
  a AC-018.3.
- [x] Q-014 — Com a contagem subindo a cada veículo, o que a tela faz quando um
  clipe falha no meio da leitura e os eventos daquele minuto são descartados?
  **Respondida: desconta.** A tela continua batendo com o banco e a planilha
  (AC-016.4), ao custo de as quantidades poderem baixar só nesse caso. Virou
  AC-016.8.
- [x] Q-015 — Que tempo total mostrar quando o processo da sessão morre sem
  registrar desfecho? **Respondida: nenhum.** Sem instante de término, qualquer
  número seria estimativa. Virou AC-018.4.

## Specs afetadas

Revisado história por história.

- `interface-sessao`
  - AC-012.2: a fase de processamento passa a mostrar quantidades por
    categoria, e as duas fases passam a mostrar o tempo decorrido, ao lado do
    progresso em minutos, que continua igual.
  - AC-012.4: passa a valer também para quantidades e tempo, que precisam ser
    reencontrados ao reabrir a interface (AC-016.7 e AC-017.4).
  - AC-012.3: a tela de resultado ganha quantidades finais e tempo total
    (AC-018.1).
  - AC-012.5: a tela de resultado de uma sessão cancelada passa a mostrar o
    tempo total, mas não as quantidades (AC-018.3), em linha com "nenhum
    resultado de contagem é gravado". O usuário terá visto quantidades parciais
    durante o processamento, e elas somem com o cancelamento.
  - AC-012.6: a sessão sem planilha passa a mostrar o tempo total, mas não as
    quantidades (AC-018.3), para não exibir zeros que pareçam contagem.
  - Fora de escopo daquela spec: "Monitoramento contínuo, painel ao vivo das
    câmeras" continua fora. O que esta feature mostra ao vivo é a sessão em
    curso, não as câmeras.
  - SUP-038 continua valendo por SUP-058.
- `contagem-veiculos`
  - AC-007.1 e AC-007.2: o resultado não muda, mas muda o momento em que são
    aplicados. Por SUP-053, a deduplicação de emenda passa a ser avaliada
    evento a evento, quando o cruzamento é gerado, contra os eventos do fim do
    clipe anterior, e não depois do clipe inteiro. Os eventos gravados precisam
    ser os mesmos de hoje.
  - AC-006.6: o limite de um evento por rastreio e sentido também precisa valer
    no momento em que o evento é gerado, para que um cruzamento repetido nunca
    chegue à tela.
  - D-4: o descarte dos eventos de um clipe que falha no meio da leitura passa
    a ter de ser comunicado ao progresso, para a tela descontar (AC-016.8).
  - AC-016.2: exige que o processamento publique cada evento aceito, com a
    categoria, à medida que ele é gerado, e não só que o minuto terminou.
  - AC-005.4: o critério não muda, mas passa a ser afetado. Com uma regravação
    do estado a cada evento aceito (SUP-058), essa publicação acontece dentro do
    laço do processamento e não pode levar o tempo médio por frame analisado
    acima de 133 ms. O tempo exibido também é a medida, na prática, desse
    orçamento.
  - Nenhuma regra de detecção, rastreamento ou categoria (SUP-023) é alterada.
- `persistencia-resultados`
  - AC-016.4 e AC-018.1: amarram o que a tela mostra aos eventos gravados por
    AC-008.2.
  - AC-008.1: não muda, porque o tempo da sessão não é gravado (Fora de
    escopo). Nenhuma migration.
- `captura-clipes`
  - Fora de escopo daquela spec: "Processar vídeo durante a fase de captura" é
    preservado, e é o que impõe AC-016.5.
  - AC-003.6: o encerramento antecipado é uma das passagens para o
    processamento cobertas por AC-017.2.
  - AC-003.4: não muda. O relógio local de SUP-056 mede só a duração exibida,
    não o período da sessão.
- `exportacao-xlsx` — nenhum critério alterado. A planilha não recebe o tempo da
  sessão (AC-010.4 intacto), e as quantidades exibidas são as mesmas que
  AC-010.2 escreve.
- `validacao-acuracia` — nenhum critério alterado. A validação roda fora da
  interface e mede os eventos, que esta feature não muda.
- `configuracao-camera` — nenhum critério alterado. Esta feature não usa linha
  nem rótulos de sentido, porque as quantidades não são separadas por sentido
  (SUP-054).

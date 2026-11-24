# Feature: processamento-upload

## Contexto

`upload-videos` termina num botão "Processar N vídeos", com uma lista de vídeos
válidos e uma câmera selecionada. Esta feature define o que acontece a partir do
clique: os vídeos viram uma sessão, são contados com a calibração da câmera, e o
resultado é gravado no banco e exportado para a planilha, como numa sessão ao
vivo.

Detecção, rastreamento, cruzamento com sentido, persistência e exportação são
os mesmos da sessão ao vivo. O que muda é a premissa de que todo vídeo é um
clipe de 1 minuto vindo da URL, que está espalhada pelas specs atuais:

- **Não há captura.** A sessão começa direto no processamento. Não existe
  minuto perdido por rede nem ETag, e não existe Last-Modified, que hoje é a
  referência de tempo de tudo (AC-003.4, AC-006.5).
- **Não há hora do dia.** Um vídeo enviado não traz data e hora confiáveis de
  gravação. Por decisão do autor (Q-020), cada evento é localizado pelo tempo
  desde o início do seu vídeo, e a sessão é datada pelo próprio processamento,
  sempre marcada como "horário do processamento".
- **Um vídeo não é um minuto.** Um arquivo pode ter 10 s ou 15 min, e qualquer
  fps. Dentro de um arquivo o vídeo é contínuo, então não há emenda a deduplicar
  na virada de minuto: o minuto passa a ser só a divisão usada nos agregados.
- **Dois vídeos não são vizinhos.** Nada garante que o segundo arquivo comece
  onde o primeiro terminou. Entre eles vale a regra de clipes não adjacentes de
  AC-007.4.

O protótipo mostra o processamento com o título "Contagem · vídeo k/N" e o
estado de cada vídeo ao lado dele: fila, processando, concluído ou
interrompido.

## Histórias

US-028 — Processar os vídeos enviados como uma sessão
Como integrante do projeto de extensão, quero que os vídeos enviados sejam
contados como uma sessão, com a calibração da câmera escolhida, para ter o mesmo
resultado que teria se a câmera tivesse sido capturada ao vivo naquele trecho.

Critérios de aceite:
  AC-028.1 — Dado N vídeos válidos e a câmera C selecionada, dentro dos limites
  de AC-027.10 e AC-027.11, quando o usuário aciona "Processar N vídeos", então
  é criada uma única sessão associada a C, que começa direto na fase de
  processamento, sem captura, e processa os vídeos na ordem da lista.

  AC-028.2 — Dado uma sessão em andamento, de qualquer fonte, quando alguém tenta
  iniciar uma sessão de upload ou uma sessão ao vivo, então a segunda é recusada
  como em AC-013.1, e a sessão em andamento não é afetada.

  AC-028.3 — Dado uma sessão de upload em processamento, quando a interface é
  consultada, então o painel ao vivo tem o título "Contagem · vídeo k/N", em que
  k é o vídeo em processamento, e cada vídeo da lista mostra um destes estados:
  "fila", "processando", "concluído", "falhou" ou "interrompido". Há no máximo
  um vídeo em "processando" por vez.

  AC-028.4 — Dado um vídeo em que veículos cruzam a linha de contagem da câmera
  C, quando ele é processado, então os eventos usam a linha e os rótulos de
  sentido de C (AC-006.3), com o mesmo limiar de confiança da sessão ao vivo.

  AC-028.5 — Dado um vídeo de F fps e D segundos, quando ele é processado, então
  o número de frames analisados é ⌊D × min(F, 10)⌋, com tolerância de 1 frame, e
  os demais frames não passam por inferência.

  AC-028.6 — Dado um veículo que cruza a linha no instante em que um minuto do
  vídeo vira o seguinte, quando o vídeo é processado, então é registrado um único
  evento, porque o rastreador não é reiniciado dentro do mesmo vídeo.

  AC-028.7 — Dado dois vídeos consecutivos da lista, quando o segundo começa a
  ser processado, então o rastreador é reiniciado, a deduplicação de emenda não
  é aplicada entre o fim do primeiro e o início do segundo, e todos os
  cruzamentos dos dois são contados.

  AC-028.8 — Dado vídeos de durações D1, D2, …, Dn, quando a sessão é
  processada, então os minutos da sessão são numerados em sequência através dos
  vídeos: o vídeo 1 ocupa os minutos 1 a ⌈D1/60⌉, o vídeo 2 começa no minuto
  seguinte, e assim por diante. Cada evento fica no minuto correspondente ao seu
  deslocamento dentro do vídeo.

  AC-028.9 — Dado um vídeo que falha no meio da leitura no minuto m dele,
  quando o sistema trata a falha, então:
  - os minutos daquele vídeo concluídos antes de m mantêm seus eventos;
  - o minuto m e os seguintes daquele vídeo ficam marcados como sem dado;
  - o vídeo fica como "falhou";
  - o processamento segue para o próximo vídeo.

  As quantidades exibidas descontam só os eventos do minuto m, como em
  AC-016.8.

  AC-028.10 — Dado uma sessão de upload em processamento, quando a interface é
  consultada, fechada e reaberta, então valem as regras da sessão ao vivo: as
  quantidades de AC-016.1, AC-016.2 e AC-016.7, o tempo decorrido de AC-017.1,
  AC-017.3 e AC-017.4 e o tempo estimado de AC-022.6. Fechar a aba não
  interrompe o processamento (AC-012.4).

US-029 — Parar o processamento dos vídeos antes do fim
Como integrante do projeto de extensão, quero poder parar um processamento longo
de vídeos enviados, para liberar a máquina sem perder os vídeos.

Critérios de aceite:
  AC-029.1 — Dado uma sessão de upload em processamento, quando o usuário
  confirma "Parar antecipadamente", então a contagem para, nenhum resultado de
  contagem é gravado, os vídeos da sessão permanecem em disco e o resultado
  informa que o processamento foi cancelado, sem oferecer download, como em
  AC-012.5.

  AC-029.2 — Dado uma sessão de upload cancelada, quando o resultado é exibido,
  então o vídeo que estava em processamento aparece como "interrompido", os
  anteriores como "concluído" ou "falhou" e os seguintes como "fila".

  AC-029.3 — Dado uma sessão de upload cancelada, quando `session process
  <id_sessao>` é executado, então todos os vídeos da sessão são processados desde
  o primeiro e o resultado é gravado como no processamento de uma sessão de
  upload que não foi cancelada.

US-030 — Gravar e exportar a sessão de upload
Como docente responsável pelo projeto, quero que a sessão feita a partir de
vídeos enviados fique gravada e exportada com a indicação de onde vieram os
vídeos, para não confundir esse resultado com o de uma captura ao vivo.

Critérios de aceite:
  AC-030.1 — Dado uma sessão de upload processada, quando ela é persistida, então
  o registro de sessão tem origem UPLOAD e guarda, para cada vídeo, o nome
  original, a posição na lista, a duração, o sha256 e os minutos da sessão que
  ele ocupa. As sessões ao vivo têm origem CAMERA, inclusive as gravadas antes
  desta feature.

  AC-030.2 — Dado sessões ao vivo e de upload gravadas, quando o histórico é
  listado (AC-009.2), então cada sessão aparece com a sua origem.

  AC-030.3 — Dado uma sessão de upload processada, quando a planilha é gerada,
  então ela tem as três abas de AC-010.1, e:
  - a aba Sessao traz a origem UPLOAD e uma linha por vídeo, com nome, duração
    e minutos ocupados;
  - o período da sessão é o início e o término do processamento, identificado
    na aba Sessao como "horário do processamento";
  - o nome do arquivo segue SUP-032, com a data e a hora do início do
    processamento no horário de Brasília e `_upload` antes do sufixo de status,
    como em `000013_20261107_1430_12min_upload_DEGRADADA.xlsx`.

  AC-030.4 — Dado uma sessão de upload de M minutos com P minutos sem dado por
  falha de leitura, quando o status é calculado, então ele segue os limites de
  AC-004.4 a AC-004.6 com P como minutos perdidos e M como duração: COMPLETA com
  P = 0, DEGRADADA com 0 < P ≤ 20% de M e INVÁLIDA acima disso.

  AC-030.5 — Dado um evento de um vídeo enviado, quando a planilha é gerada,
  então a linha dele na aba Eventos traz o nome do vídeo e o deslocamento do
  cruzamento desde o início daquele vídeo, no formato MM:SS e com resolução de
  1 segundo, e não traz data nem hora do dia.

  AC-030.6 — Dado uma sessão de upload concluída, quando ela é encerrada, então
  nenhum dos vídeos enviados permanece no diretório de dados, nem no de envio
  nem no da sessão.

  AC-030.7 — Dado a linha de comando com uma câmera do registro e um ou mais
  arquivos de vídeo válidos, quando `session upload <id_camera> <arquivo>...` é
  executado, então o pipeline completo roda até a geração do XLSX sem que a
  interface web seja iniciada. Arquivo inválido é recusado antes de qualquer
  processamento, com mensagem que nomeia o arquivo.

## Fora de escopo

- Data e hora reais de gravação dos vídeos, informadas pelo usuário ou lidas
  dos metadados do arquivo.
- Manter os vídeos enviados depois da sessão concluída, ou oferecê-los para
  download, inteiros ou em trechos.
- Gravar resultado parcial quando o processamento é parado antes do fim.
- Continuar uma sessão de upload acrescentando vídeos depois de iniciada.
- Juntar numa mesma sessão vídeos enviados e minutos capturados ao vivo.
- Detectar que dois vídeos são contínuos e aplicar a deduplicação de emenda
  entre eles.
- Validar a acurácia da contagem em vídeos enviados: a meta de
  `validacao-acuracia` continua medida na câmera 000013, em clipes da URL.
- Processar vídeos de câmeras diferentes numa mesma sessão.

## Suposições

- [x] SUP-088 — Todos os vídeos de um envio formam uma sessão e uma planilha,
  como no protótipo, que gera um único `.xlsx` para a lista inteira. O limite
  de 15 min vale para a soma das durações (AC-027.11). Confirmado pelo autor.
  Afeta AC-028.1 e AC-030.3.
- [x] SUP-089 — Os estados de cada vídeo são os quatro do protótipo, mais
  "falhou", que vem da regra de AC-028.9. O título usa a posição do vídeo na
  lista, contando a partir de 1. Confirmado pelo autor. Afeta AC-028.3 e
  AC-029.2.
- [x] SUP-090 — A amostragem é por fps efetivo, e não por "1 frame a cada 3":
  10 frames analisados por segundo de vídeo, que é o que SUP-017 dá em 30 fps.
  Assim, um vídeo de 60 fps não tem o dobro de frames analisados nem um de
  15 fps a metade, e a amostragem fica igual à que foi validada em AC-014.3.
  Vídeo com até 10 fps tem todos os frames analisados. É também o que mantém
  válido, no upload, o orçamento de 80 s por minuto do tempo estimado (SUP-070
  de `layout-interface`). Afeta AC-028.5 e AC-028.10.
- [x] SUP-091 — Dentro de um mesmo vídeo o rastreamento é contínuo, e o minuto é
  só a divisão dos agregados. AC-007.3, que reinicia o rastreador, passa a valer
  na troca de vídeo, e não na troca de minuto. Afeta AC-028.6 e AC-028.7.
- [x] SUP-092 — Dois vídeos consecutivos da lista são tratados como não
  adjacentes, pela regra de AC-007.4. O sistema não sabe se um começa onde o
  outro terminou, e aplicar a janela de emenda entre trechos sem relação apagaria
  veículos reais. O risco aceito é contar duas vezes um veículo que esteja em
  cima da linha no corte entre dois vídeos contínuos. Confirmado pelo autor.
  Afeta AC-028.7.
- [x] SUP-093 — O último minuto de cada vídeo pode ser parcial e entra na série
  como um minuto normal. A duração de cada vídeo vai para a aba Sessao, para quem
  quiser normalizar a contagem do minuto parcial. A duração pedida e a duração
  real da sessão são as duas iguais a M, o total de minutos da sessão, que pode
  passar de 15 quando há vários vídeos curtos, mesmo com a duração somada dentro
  do limite. Confirmado pelo autor. Afeta AC-028.8, AC-030.1, AC-030.3 e
  AC-030.4.
- [x] SUP-094 — A falha no meio da leitura segue a D-4 de `contagem-veiculos`,
  aplicada ao minuto, e não ao vídeo inteiro: só o que ainda não foi lido vira
  sem dado. Se nenhum vídeo render um frame legível, a sessão termina sem
  planilha, pela D-1 de `interface-sessao`. Confirmado pelo autor. Afeta
  AC-028.9.
- [x] SUP-095 — Na sessão de upload, os minutos perdidos que entram no status
  são os minutos sem dado por falha de leitura, porque não há captura que perca
  minuto. O percentual de AC-010.5 usa esses minutos. Confirmado pelo autor.
  Afeta AC-030.4.
- [x] SUP-096 — A origem é coluna nova da tabela de sessões, e os vídeos ficam
  numa tabela nova ligada à sessão, as duas criadas pela migration 003. As
  sessões que já existem recebem CAMERA na migration. Os campos de captura,
  como ETag e Last-Modified por minuto, ficam vazios na sessão de upload.
  Afeta AC-030.1 e AC-030.2.
- [x] SUP-097 — Ao iniciar, os vídeos válidos são movidos do diretório de envio
  para `<data_dir>/sessions/<id_sessao>/`. Na sessão concluída, eles são sempre
  apagados ao fim, porque o upload não tem a opção de manter (Q-022). No
  cancelamento, eles ficam para reprocessar, como em AC-012.5. O arquivo
  original no computador do usuário nunca é tocado: o que o sistema apaga é a
  cópia que recebeu. Afeta AC-029.1, AC-029.3 e AC-030.6.
- [x] SUP-098 — O comando de linha é `session upload <id_camera> <arquivo>...`,
  sem `--keep-clips`, coerente com Q-022. É o que a interface dispara em segundo
  plano, como `session run` na sessão ao vivo (SUP-038), e pega a mesma trava
  de sessão única (SUP-052). As validações de `upload-videos` (extensão,
  legibilidade, resolução, tamanho e duração) são as mesmas nos dois caminhos.
  A duplicata, que na interface só gera aviso (SUP-085), gera aviso também no
  terminal. Afeta AC-028.2 e AC-030.7.
- [x] SUP-099 — A câmera, o limiar de confiança e a versão do modelo ficam
  gravados na sessão de upload como na sessão ao vivo (AC-008.1). A taxa de
  amostragem gravada é a de SUP-090, em frames por segundo de vídeo. Afeta
  AC-028.4, AC-028.5 e AC-030.1.
- [x] SUP-100 — Conforme Q-020, o banco não recebe hora do dia para os eventos
  de upload.
  - A migration 003 acrescenta ao evento o vídeo de origem e o deslocamento em
    segundos desde o início dele, e é isso que a aba Eventos mostra.
  - Como `evento.timestamp` é obrigatório desde a migration 001, ele recebe uma
    posição na linha do tempo da sessão: o início do processamento, mais
    60 s × (minuto inicial do vídeo − 1), mais o deslocamento. Isso preserva a
    ordenação e a coerência com o minuto ordinal, e esse valor nunca é exibido
    como hora do dia.
  - O início e o fim da sessão são o início e o término do processamento, no
    relógio local, como T0 e o término de SUP-056.

  Afeta AC-030.3 e AC-030.5.

## Perguntas em aberto

Nenhuma pendente. Os IDs permanecem como histórico das decisões.

- [x] Q-020 — Qual é a data e a hora de início de cada vídeo enviado?
  **Respondida: nenhuma, porque não há data real.** Os eventos ficam com o
  deslocamento desde o início do vídeo, e a sessão é datada pelo
  processamento, marcada como "horário do processamento". As alternativas
  descartadas foram o usuário informar a data e a hora de cada vídeo e usar o
  metadado de criação do arquivo, que costuma ser o da cópia. Consequência
  aceita: a sessão de upload não permite análise por hora do dia. Virou
  AC-030.3, AC-030.5 e SUP-100.
- [x] Q-021 — O que "Parar antecipadamente" faz numa sessão de upload?
  **Respondida: cancela sem gravar**, como na sessão ao vivo (AC-012.5). Os
  vídeos ficam para reprocessar. A alternativa do protótipo, que é gravar a
  planilha dos vídeos já concluídos, foi descartada, e as duas fontes ficam
  com uma regra só. Está em AC-029.1 a AC-029.3.
- [x] Q-022 — O que "Manter clipes de vídeo" guarda numa sessão de upload?
  **Respondida: nada, porque a opção não é oferecida no upload.** O usuário já
  tem os arquivos originais. A cópia recebida é apagada ao fim da sessão
  concluída e mantida só no cancelamento, para reprocessar. Virou AC-030.6,
  SUP-097, SUP-098 e AC-024.5 de `download-clipes`.

## Specs afetadas

Revisado história por história.

- `captura-clipes`
  - AC-003.1 e AC-003.4: na sessão de upload não há ETag nem Last-Modified, e o
    período da sessão deixa de ser o período real do vídeo para ser o do
    processamento (AC-030.3, SUP-100).
  - AC-004.4 a AC-004.6: os limites de status são reaproveitados, com outra
    fonte de minuto perdido (SUP-095).
  - AC-003.5: o descarte ao fim da sessão passa a valer também para os vídeos
    enviados, sem a opção de manter (AC-030.6, SUP-097).
- `contagem-veiculos`
  - Contexto, "O rastreador é reiniciado a cada clipe" e o clipe de 1 minuto:
    no upload o rastreador é reiniciado a cada vídeo (SUP-091).
  - AC-005.3: assume clipe de 59,93 s a 30 fps. A amostragem passa a ser por fps
    efetivo no upload (AC-028.5, SUP-090), o que mexe em SUP-017.
  - AC-006.5: no upload, o timestamp do evento deixa de partir do Last-Modified
    e passa a ser o deslocamento dentro do vídeo (AC-030.5, SUP-100).
  - AC-007.3 e AC-007.4: o reinício e a não adjacência passam a valer na troca de
    vídeo, e não na troca de minuto (AC-028.6, AC-028.7).
  - D-4 do `_tasks.md` daquela feature: a falha de leitura passa a valer por
    minuto dentro de um vídeo longo (SUP-094).
- `persistencia-resultados`
  - AC-008.1: ganha a origem e a lista de vídeos, pela migration 003
    (SUP-096). O schema já commitado não é alterado.
  - AC-008.2: no upload, o evento ganha vídeo de origem e deslocamento, e o
    `timestamp` passa a ser uma posição na linha do tempo da sessão, e não hora
    real (SUP-100).
  - AC-009.2: a listagem ganha a origem (AC-030.2), e o "período real" de uma
    sessão de upload é o horário do processamento.
  - D-4 do `_tasks.md` daquela feature: o minuto ordinal passa a atravessar os
    vídeos (AC-028.8).
- `exportacao-xlsx`
  - AC-010.1 e SUP-032: o nome do arquivo ganha `_upload`, e a data e a hora
    passam a ser as do início do processamento (AC-030.3).
  - AC-010.2: no upload, a aba Eventos troca a data e a hora do cruzamento pelo
    nome do vídeo e pelo deslocamento (AC-030.5).
  - AC-010.4: a aba Sessao ganha a origem, a lista de vídeos e a marca
    "horário do processamento".
  - SUP-033: a conversão para o horário de Brasília deixa de se aplicar aos
    eventos de upload, e continua valendo para o período e o nome do arquivo.
  - D-5 do `_tasks.md` daquela feature: o percentual passa a ser sobre os minutos
    sem dado por falha de leitura (SUP-095).
- `interface-sessao`
  - AC-011.4: ganha o equivalente de linha de comando para o upload (AC-030.7).
  - AC-012.2: a sessão de upload tem uma fase só, a de processamento.
  - AC-012.5: aplicado ao upload sem mudança, em AC-029.1.
  - AC-013.1, AC-013.2 e SUP-052: a trava passa a valer também para
    `session upload` (SUP-098).
- `acompanhamento-ao-vivo`
  - AC-016.5 e AC-017.2: não se aplicam, porque não há captura.
  - AC-016.8: o desconto passa a ser do minuto que falhou, e não do clipe
    inteiro (AC-028.9).
- `layout-interface`
  - AC-019.2: o cabeçalho vai direto para "Processando".
  - AC-022.1: o título é substituído por "Contagem · vídeo k/N" (AC-028.3).
  - AC-022.5: o tempo estimado da captura não se aplica, e AC-022.6 vale desde
    o início, com o orçamento de 80 s mantido por SUP-090.
  - AC-023.2: a nota "Interrompida pelo usuário" não ocorre, porque a sessão
    não registra encerramento pelo usuário (SUP-093).
- `download-clipes`
  - AC-024.5: a opção de manter clipes não aparece no upload.
  - AC-025.1 a AC-025.6 não se aplicam à sessão de upload, que não tem lista de
    clipes (Q-022).
- `upload-videos` — fornece a lista de vídeos válidos de AC-027.9, com as
  validações que SUP-098 repete na linha de comando. A duplicata aceita com
  aviso (AC-027.7) entra na sessão como um vídeo qualquer.
- `configuracao-camera`
  - AC-028.4 usa a linha e os rótulos de AC-001.1 sem alterá-los.
  - A resolução de calibração vem do campo novo registrado em `upload-videos`
    (SUP-086).
- `validacao-acuracia` — nenhum critério muda. Revisado: o upload não é
  validado (Fora de escopo), e SUP-090 existe para manter a amostragem validada
  em AC-014.3.

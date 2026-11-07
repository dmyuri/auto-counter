# Feature: persistencia-resultados

## Contexto

Os vídeos são apagados ao fim da sessão. O banco é, portanto, a única coisa que
sobrevive: se um número não estiver gravado aqui, ele não pode mais ser
recuperado, porque o clipe de origem não existe mais e a URL não guarda
histórico.

São gravadas três coisas: a sessão (o que foi pedido, o que de fato aconteceu e
com qual configuração), os eventos de cruzamento (o dado bruto que sustenta cada
número) e os agregados por minuto (o que alimenta a planilha e os gráficos).

Nenhuma imagem é persistida. A decisão é deliberada: como os vídeos são
descartados, guardar recortes de veículos reintroduziria imagens de placas e de
pessoas identificáveis sem prazo de descarte.

O schema, uma vez commitado, é imutável. Qualquer mudança posterior — nova
categoria de veículo, novo campo — exige migration numerada, conforme
`CLAUDE.md`.

## Histórias

US-008 — Gravar o resultado da sessão
Como integrante do projeto de extensão, quero que a sessão inteira fique gravada
com o que foi contado e em que condições, para que o resultado continue
interpretável depois que os vídeos forem apagados.

Critérios de aceite:
  AC-008.1 — Dado uma sessão processada, quando ela é persistida, então existe um
  registro de sessão com id, id da câmera, início e fim reais, duração pedida,
  duração real, indicação de encerramento pelo usuário, status, quantidade e
  lista dos minutos perdidos, versão do modelo, taxa de amostragem e limiar de
  confiança usados.
  > **Alterado por:** feature `processamento-upload`, em 2026-11-07.
  > O registro de sessão passa a ter a origem, CAMERA ou UPLOAD, e, na sessão
  > de upload, a lista de vídeos com nome, posição, duração, sha256 e minutos
  > ocupados, pela migration 003 (AC-030.1 e SUP-096).
  > Ver `.spec/features/processamento-upload/spec.md`.

  AC-008.2 — Dado os cruzamentos detectados numa sessão, quando eles são
  persistidos, então cada evento fica ligado ao id daquela sessão e guarda
  timestamp, categoria, sentido, id de rastreio e confiança.
  > **Alterado por:** feature `processamento-upload`, em 2026-11-07.
  > Na sessão de upload, o evento passa a guardar também o vídeo de origem e o
  > deslocamento dentro dele, e o timestamp passa a ser uma posição na linha do
  > tempo da sessão, e não hora real (SUP-100).
  > Ver `.spec/features/processamento-upload/spec.md`.

  AC-008.3 — Dado os eventos de uma sessão, quando os agregados são calculados,
  então existe uma linha para cada minuto do período com a contagem por sentido e
  por categoria, e um minuto capturado em que nenhum veículo cruzou aparece com
  contagem zero, nunca ausente da série.

  AC-008.4 — Dado um minuto marcado como não capturado, quando os agregados são
  gravados, então esse minuto aparece marcado como sem dado, em estado
  distinguível de um minuto com contagem zero.

  AC-008.5 — Dado uma sessão já persistida, quando a persistência daquela mesma
  sessão é executada de novo, então os eventos e agregados dela não são
  duplicados e o resultado final é igual ao da primeira execução.

US-009 — Consultar o histórico de sessões
Como docente responsável pelo projeto, quero consultar as sessões já executadas
mesmo depois do descarte dos vídeos, para comparar períodos sem precisar
reprocessar nada.

Critérios de aceite:
  AC-009.1 — Dado uma sessão cujos vídeos já foram apagados, quando o histórico é
  consultado, então ela continua listada com câmera, período, status e totais.

  AC-009.2 — Dado várias sessões gravadas, quando o histórico é listado, então as
  sessões vêm ordenadas da mais recente para a mais antiga, cada uma com id da
  câmera, período real, status e total de veículos contados.
  > **Alterado por:** feature `processamento-upload`, em 2026-11-07.
  > A listagem passa a mostrar a origem de cada sessão, e o período de uma
  > sessão de upload é o horário do processamento (AC-030.2 e AC-030.3).
  > Ver `.spec/features/processamento-upload/spec.md`.

## Fora de escopo

- Guardar imagens: nem frame, nem recorte do veículo, nem vídeo, em nenhuma
  tabela.
- Banco em servidor, acesso concorrente por mais de um processo e replicação.
- Placas, cor, modelo ou qualquer atributo que identifique um veículo específico.
- Comparação estatística entre sessões, séries temporais consolidadas e
  relatórios analíticos: o banco entrega o dado, a análise é feita fora.
- Interface de edição ou correção manual das contagens gravadas.
- Descarte automático de sessões antigas por prazo.

## Suposições

- [x] SUP-024 — O banco é um arquivo SQLite único em
  `<data_dir>/auto_counter.db`, criado na primeira execução, com a versão do
  schema gravada em tabela própria e migrations numeradas. Afeta AC-008.1.
- [x] SUP-027 — "Versão do modelo" é o nome do arquivo do modelo somado ao hash
  curto do seu conteúdo, para que dois resultados só sejam comparáveis quando
  vierem do mesmo detector. Afeta AC-008.1.
- [x] SUP-028 — Minuto sem dado é representado por uma coluna de estado na tabela
  de agregados (CAPTURADO ou SEM_DADO), e não por ausência de linha ou por
  contagem nula. Afeta AC-008.3 e AC-008.4.
- [x] SUP-029 — As sessões nunca expiram nem são apagadas automaticamente: o dado
  é agregado, sem imagem e sem identificação de pessoa ou veículo, então não há
  motivo de privacidade para descarte, e o histórico acumulado é justamente o que
  permite comparar a mesma via em meses diferentes. Quem quiser zerar apaga o
  arquivo do banco. Confirmado. Afeta AC-009.1 e AC-009.2.
- [x] SUP-030 — Os timestamps são gravados em UTC no banco; a conversão para
  horário local acontece só na exportação. Afeta AC-008.2 e AC-008.3.

## Perguntas em aberto

Nenhuma, e nenhuma foi aberta nesta spec desde o início. Revisado história por
história: o único ponto de negócio em disputa aqui era guardar ou não recortes de
imagem, decidido por não guardar, com o efeito declarado em Fora de escopo. As
decisões tomadas em outras specs que afetam o conteúdo destas tabelas — Q-003
sobre sessão interrompida e Q-004 sobre cruzamento repetido — já estão
respondidas e refletidas em AC-008.1 e no volume de eventos de AC-008.2.

## Specs afetadas

Revisado história por história.

- `captura-clipes` — AC-008.1 grava o status e os minutos perdidos definidos em
  AC-004.4 a AC-004.6 e, por causa de AC-003.6, passou a gravar também a duração
  real e a marca de encerramento pelo usuário. Não foi criado um quarto status: o
  vocabulário de três continua íntegro.
- `contagem-veiculos` — AC-008.2 persiste os campos de evento de AC-006.1 e
  AC-006.5; AC-008.1 persiste a amostragem de SUP-017 e o limiar de SUP-016.
  AC-006.6 limita a no máximo um evento por rastreio e sentido, o que reduz o
  volume gravado em horário de pico.
- `exportacao-xlsx` — AC-010.2, AC-010.3 e AC-010.4 leem exatamente estas
  tabelas, e AC-010.6 só é possível porque a exportação não reprocessa vídeo.
  A distinção de SUP-028 entre SEM_DADO e zero é o que sustenta AC-010.3, e os
  campos novos de AC-008.1 são o que AC-010.4 imprime na aba Sessao.
- `interface-sessao` — AC-012.3 mostra o status vindo de AC-008.1, e AC-012.4
  depende de o registro de sessão existir desde o início da captura para que o
  progresso seja reencontrado ao reabrir a interface.
- `validacao-acuracia` — AC-014.1 compara contra os eventos gravados por
  AC-008.2.

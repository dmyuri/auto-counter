# Feature: nova-camera

## Contexto

Até aqui o registro de câmeras tem uma única entrada, a **000013** (Praça
Getúlio Vargas), calibrada na entrega do MVP. A spec `configuracao-camera`
deixou o mecanismo pronto para crescer: cada câmera é um YAML em
`config/cameras/<id>.yaml`, e acrescentar uma câmera não exige alteração de
código (Contexto e AC-001.1 de `configuracao-camera`).

Esta feature acrescenta **uma** câmera nova ao registro versionado, a
**000012 — Praia x Mariz Barros** (Q-023), com calibração própria, e garante
que ela aparece como opção na interface ao lado da 000013. A pessoa usuária
continua só selecionando: ela não cadastra nem edita câmera. Quem inclui a
câmera é o mantenedor, editando os arquivos versionados.

A 000012 publica no mesmo esquema da 000013 (SUP-103, confirmado). Ela é
oferecida sem passar pela validação de acurácia, que continua medida só na
000013 (Q-024). Por ter o menor id do registro, ela passa a ser a câmera
selecionada por padrão numa aba recém-aberta, pela regra já vigente em
`layout-interface` (Q-025).

A 000013 não muda: ela continua com a mesma linha, os mesmos sentidos e a mesma
prévia, e continua sendo a câmera do conjunto de referência de
`validacao-acuracia`.

## Histórias

US-031 — Registrar a câmera nova no registro versionado
Como responsável pela manutenção do sistema, quero incluir a câmera 000012 no
registro versionado com calibração própria, para que ela possa ser analisada sem
herdar nada da calibração da 000013.

Critérios de aceite:
  AC-031.1 — Dado o diretório versionado `config/cameras/`, quando o sistema
  carrega o registro, então retorna exatamente 2 câmeras, de ids "000012" e
  "000013", e nenhum arquivo é rejeitado.

  AC-031.2 — Dado o registro versionado carregado, quando a câmera "000012" é
  consultada, então ela tem o id como string com os zeros à esquerda
  preservados, o nome "Praia x Mariz Barros", `sentido_a` e `sentido_b` não
  vazios e diferentes entre si, linha com dois pontos distintos, e resolução de
  calibração declarada, com os dois pontos da linha dentro dos limites dessa
  resolução.

  AC-031.3 — Dado o registro versionado com a câmera nova, quando o sistema o
  carrega, então a câmera 000013 tem o mesmo nome, os mesmos rótulos de
  sentido, a mesma linha (p1 = (1053, 348), p2 = (351, 445)) e a mesma prévia
  de antes desta feature.

  AC-031.4 — Dado a câmera "000012" e a base URL configurada, quando o sistema
  monta a URL do clipe, então produz `<base_url>/000012/last_video.mp4`,
  preservando os zeros à esquerda do id.

  AC-031.5 — Dado o registro versionado, quando o comando `camera list` é
  executado, então a saída lista as duas câmeras, cada uma com o seu id e o seu
  nome de local.

US-032 — Escolher a câmera nova na interface
Como integrante do projeto de extensão, quero ver a câmera 000012 entre as
opções da interface e iniciar uma sessão com ela, para analisar outra via além
da Praça Getúlio Vargas.

Critérios de aceite:
  AC-032.1 — Dado o registro versionado, quando a interface é aberta, então ela
  exibe exatamente 2 cartões de câmera, nesta ordem: um com "000012" e "Praia x
  Mariz Barros", e outro com "000013" e "Praça Getúlio Vargas".

  AC-032.2 — Dado o cartão da câmera 000012, quando ele é exibido, então mostra
  a imagem de prévia indicada no YAML dela, e não "sem prévia", sem que a
  interface faça nenhuma requisição de rede.

  AC-032.3 — Dado uma aba recém-aberta, quando os cartões são exibidos, então a
  câmera 000012 aparece como a única "SELECIONADA".

  AC-032.4 — Dado o cartão da câmera 000012 selecionado e a duração de 1 minuto,
  quando o usuário aciona "Iniciar sessão", então a sessão disparada recebe o id
  de câmera "000012", o id da sessão começa com "000012-", e a captura
  requisita apenas `<base_url>/000012/last_video.mp4`, sem nenhuma requisição à
  URL da 000013.

  AC-032.5 — Dado uma sessão da câmera 000012 com um cruzamento simulado no
  sentido da normal de p1 para p2 da linha dela e outro no sentido oposto,
  quando a sessão é processada, então os eventos gravados trazem
  respectivamente o `sentido_a` e o `sentido_b` da 000012, lidos do YAML dela.

  AC-032.6 — Dado uma sessão COMPLETA da câmera 000012 processada, quando ela é
  exportada, então o arquivo XLSX tem o nome
  `000012_<AAAAMMDD>_<HHMM>_<N>min.xlsx` e a aba de metadados registra o id
  "000012" e o nome "Praia x Mariz Barros".

  AC-032.7 — Dado a fonte "Fazer upload de vídeos" marcada e a câmera 000012
  selecionada, quando um vídeo é adicionado à lista, então o aviso cita
  "000012" e "Praia x Mariz Barros", e o vídeo é recusado se a resolução dele
  for diferente da resolução de calibração da 000012, mesmo que seja igual à da
  000013.

## Fora de escopo

- Interface para cadastrar, editar ou remover câmera: continua sendo manutenção
  sobre os arquivos versionados (Fora de escopo de `configuracao-camera`).
- Mais de uma câmera nova nesta feature.
- Capturar de duas câmeras ao mesmo tempo: continua uma sessão por vez.
- Parâmetros de detecção, amostragem ou modelo diferentes por câmera. A 000012
  usa a mesma configuração padrão de `contagem-veiculos`.
- Medir o orçamento de tempo por frame (AC-005.4) na 000012: ele continua
  medido na máquina de referência com clipes da 000013.
- Validar a acurácia da contagem na 000012, ou montar um conjunto de referência
  contado à mão para ela (Q-024).
- Aviso de "contagem não validada" no cartão ou na planilha da 000012 (Q-024).
- Descoberta automática da câmera no servidor da NitTrans.

## Suposições

- [x] SUP-101 — Esta feature inclui exatamente uma câmera nova, a 000012, e o
  registro versionado passa de 1 para 2 câmeras. Afeta AC-031.1 e AC-032.1.
- [x] SUP-102 — Removida na revisão de 2026-11-08: não mudava o resultado. Que
  a câmera nova entra só com arquivos em `config/cameras/`, sem lista no
  código, já é garantido pelo AC-001.1 de `configuracao-camera`.
- [x] SUP-103 — A câmera 000012 publica no mesmo esquema da 000013: o arquivo
  `<base_url>/000012/last_video.mp4`, na mesma base URL de
  `AUTO_COUNTER_BASE_URL`, com resposta HTTP 200, `ETag` e `Last-Modified`, e
  um clipe de cerca de 1 minuto substituído a cada minuto. Confirmado pelo
  autor na fonte. Afeta AC-031.4 e AC-032.4.
- [x] SUP-104 — A linha, os rótulos dos sentidos e a resolução de calibração da
  000012 são definidos pelo mantenedor com o comando `camera preview`
  (AC-002.1), conferindo no PNG qual lado é qual, como foi feito com a 000013.
  As coordenadas são pixels absolutos do frame nativo da 000012 (SUP-002), e a
  resolução é lida do vídeo real dela, que pode ser diferente de 1280×720
  (SUP-007). Pelo precedente de Q-002, o texto dos rótulos não é decisão de
  spec. Afeta AC-031.2 e AC-032.5.
- [x] SUP-105 — O YAML da 000012 segue o schema vigente quando ela for
  implementada, inclusive o campo obrigatório `resolucao` de SUP-086
  (`upload-videos`). Hoje nem o modelo de câmera nem o YAML da 000013 têm esse
  campo. Enquanto `upload-videos` não estiver implementada, a 000012 entra sem
  `resolucao`, e ficam bloqueados a parte de resolução de AC-031.2 ("resolução
  de calibração declarada, com os dois pontos da linha dentro dos limites dessa
  resolução") e o AC-032.7 inteiro. Os demais critérios não dependem dela.
  Decidido pelo autor em 2026-11-08. Afeta AC-031.2 e AC-032.7.
- [x] SUP-106 — A 000012 tem prévia: uma imagem fixa versionada em
  `config/cameras/`, indicada no campo `preview` do YAML dela, escolhida sem
  placa nem pessoa identificável, como recomenda o README. Confirmado pelo
  autor. Afeta AC-032.2.
- [x] SUP-107 — A 000012 aparece nas duas fontes da interface, "Câmera ao vivo"
  e "Fazer upload de vídeos", porque os cartões vêm do mesmo registro
  (AC-026.2). Confirmado pelo autor. Afeta AC-032.1 e AC-032.7.

## Perguntas em aberto

Nenhuma pendente. Os IDs permanecem como histórico das decisões.

- [x] Q-023 — Qual é a câmera nova? **Respondida: 000012, com o nome de local
  "Praia x Mariz Barros"**. Afeta todos os critérios desta spec.
- [x] Q-024 — A câmera nova pode ser oferecida na interface sem passar pela
  validação de acurácia? **Respondida: sim, sem aviso.** A 000012 aparece igual
  à 000013, sem marcação de "contagem não validada" no cartão nem na planilha,
  e o gate de `validacao-acuracia` continua medindo só a 000013. Nenhum
  critério novo foi acrescentado.
- [x] Q-025 — Qual câmera vem selecionada numa aba recém-aberta? **Respondida:
  vale a regra atual** (SUP-065 e AC-020.4 de `layout-interface`), a de menor
  id, que é a 000012. Afeta AC-032.1 e AC-032.3.

## Specs afetadas

Revisei história por história as 12 specs de `.spec/features/`. Alteram ou
contradizem esta feature:

- `configuracao-camera`
  - **Contexto**: o texto "É a única câmera calibrada da entrega" deixa de ser
    verdade. O mecanismo de AC-001.1 a AC-001.5 e AC-002.1 a AC-002.4 não muda:
    esta feature só o usa.
  - **Specs afetadas**: a nota "AC-011.1 lista exatamente as câmeras de
    AC-001.1" continua valendo, agora com N = 2.
- `validacao-acuracia`
  - **Fora de escopo**, "Validar acurácia em câmera diferente da 000013: o MVP
    tem uma câmera calibrada": o item continua fora de escopo por decisão
    (Q-024), mas a justificativa muda. O MVP passa a ter duas câmeras
    calibradas, e só uma é validada.
  - **Contexto**, "nenhuma afirmação de que o sistema 'conta bem' vale" sem a
    validação: a 000012 é oferecida sem validação e sem aviso, por decisão
    registrada em Q-024. AC-014.3 continua medindo só a 000013, então a
    contagem da 000012 não tem gate de acurácia.
- `layout-interface`
  - **AC-020.4 e SUP-065**: o texto não muda, mas o comportamento percebido
    muda. A câmera selecionada por padrão numa aba recém-aberta deixa de ser a
    000013 e passa a ser a 000012, que tem o menor id (Q-025 e AC-032.3).
  - **AC-020.1 e AC-020.2**: não mudam, mas passam a valer com 2 cartões, e a
    000012 precisa de prévia própria (SUP-106).
- `upload-videos`
  - **SUP-086 e AC-027.5**: a 000012 precisa declarar `resolucao`, e os vídeos
    enviados para ela são validados contra essa resolução, não contra os
    1280×720 da 000013 (AC-032.7).
  - **AC-026.2**: o aviso passa a poder citar a 000012. Como ela vem
    selecionada por padrão, o aviso de uma aba recém-aberta passa a citá-la.
- `processamento-upload`
  - **Fora de escopo**, "`validacao-acuracia` continua medida na câmera 000013,
    em clipes da URL": continua igual. Vídeos enviados para a 000012 são
    contados sem gate de acurácia (Q-024).
- `contagem-veiculos`
  - **AC-005.4 e SUP-017**: o orçamento de 133 ms por frame foi medido em clipes
    1280×720 da 000013. O comportamento não muda, mas o orçamento não garante
    nada para a 000012 se ela tiver outra resolução (ver Fora de escopo).

Revisadas sem alteração:

- `captura-clipes`: AC-003.1 aceita qualquer câmera do registro. As medições do
  Contexto são da 000013, e a 000012 segue o mesmo esquema de publicação
  (SUP-103).
- `interface-sessao`: AC-011.1 e AC-011.3 são genéricos em N, e AC-011.4 vale
  para a 000012.
- `exportacao-xlsx`: o nome do arquivo já usa o id da câmera, e o exemplo com
  "000013" é só ilustração.
- `persistencia-resultados`, `acompanhamento-ao-vivo` e `download-clipes`: não
  dependem de qual câmera está em uso.

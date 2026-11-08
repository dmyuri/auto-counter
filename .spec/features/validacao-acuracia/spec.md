# Feature: validacao-acuracia

## Contexto

Esta feature é o gate da entrega. Pela `CLAUDE.md`, nenhuma afirmação de que o
sistema "conta bem" vale: quem declara a contagem pronta é o resultado desta
validação contra vídeo de referência contado à mão.

> **Alterado por:** feature `nova-camera`, em 2026-11-08.
> A câmera 000012 passa a ser oferecida na interface sem passar por esta
> validação e sem aviso, por decisão registrada em Q-024, então a contagem
> dela não tem gate de acurácia.
> Ver `.spec/features/nova-camera/spec.md`.

A meta é dupla e foi fixada antes de qualquer medição, para que o número não
seja escrito depois para caber no resultado:

- erro percentual absoluto de no máximo 10% na contagem total de cada sentido;
- acerto de categoria de no mínimo 80%.

A meta vale por clipe: os três precisam passar individualmente. Média entre
clipes deixaria o sistema ser declarado pronto enquanto falha de forma conhecida
numa das condições medidas.

O conjunto de referência é de 3 clipes de 1 minuto da câmera 000013, em três
condições agendáveis: horário de pico, fora de pico e noite. São 3 minutos de
tráfego contados veículo a veículo por uma pessoa — o trabalho mais caro do
projeto, e a razão de o conjunto ser pequeno. Chuva não entra como condição
obrigatória porque não se agenda: se surgir durante o projeto, vira um clipe
extra medido e reportado, sem poder reprovar a entrega.

A validação roda offline, sobre clipes preservados em disco pela flag de manter
vídeos da captura. Ela precisa ser reproduzível: a mesma entrada tem que dar o
mesmo veredito hoje e na semana da defesa.

## Histórias

US-014 — Validar a contagem contra o ground truth
Como autor do TCC, quero medir a contagem automática contra uma contagem manual
nos clipes de referência, para poder afirmar com número que o sistema atende à
meta declarada.

Critérios de aceite:
  AC-014.1 — Dado os clipes de referência e suas contagens manuais, quando a
  validação é executada, então ela calcula, para cada clipe e cada sentido, o
  erro percentual absoluto entre a contagem automática e a manual.

  AC-014.2 — Dado os clipes de referência e suas contagens manuais, quando a
  validação é executada, então ela calcula o percentual de acerto de categoria
  sobre os veículos pareados entre as duas contagens.

  AC-014.3 — Dado os 3 clipes de referência, um de pico, um de fora de pico e um
  noturno, quando a validação é executada e em todos eles o erro de contagem é
  menor ou igual a 10% em cada sentido e o acerto de categoria é maior ou igual a
  80%, então ela passa.

  AC-014.4 — Dado que algum dos 3 clipes de referência viola qualquer um dos dois
  limites, quando a validação é executada, então ela falha e aponta qual clipe,
  qual métrica e qual valor medido.

  AC-014.5 — Dado a validação em execução, quando ela roda, então usa apenas os
  clipes e as contagens manuais presentes em disco, sem nenhuma requisição de
  rede, e duas execuções sobre a mesma entrada produzem o mesmo veredito.

US-015 — Relatório da validação
Como autor do TCC, quero um relatório com os números por clipe e o erro por
categoria, para levar a evidência à banca em vez de uma afirmação.

Critérios de aceite:
  AC-015.1 — Dado uma execução da validação, quando ela termina, então grava um
  relatório contendo, para cada clipe de referência: contagem manual e automática
  por sentido, erro percentual por sentido, matriz de confusão das quatro
  categorias e o veredito daquele clipe; e quando existir um clipe extra de
  chuva, seus números aparecem no relatório identificados como medição fora da
  meta, sem influenciar o veredito de AC-014.3.

## Fora de escopo

- Validar acurácia em câmera diferente da 000013: o MVP tem uma câmera calibrada
  e a meta é medida nela.
  > **Alterado por:** feature `nova-camera`, em 2026-11-08.
  > O item continua fora de escopo, mas por decisão (Q-024), já que o MVP
  > passa a ter duas câmeras calibradas, 000013 e 000012, e só a 000013 é
  > validada.
  > Ver `.spec/features/nova-camera/spec.md`.
- Métricas de detecção por frame (mAP, IoU) e avaliação do modelo isoladamente:
  o que se mede aqui é a contagem entregue ao usuário.
- Ajuste automático de parâmetros para atingir a meta.
- Segunda conferência independente da contagem manual.
- Chuva como condição obrigatória do conjunto de referência.
- Validação da acurácia do timestamp ou da duração dos clipes.

## Suposições

- [x] SUP-044 — O conjunto de referência fica em `tests/ground_truth/`. São
  versionados os CSVs de contagem manual e um `manifest.yaml` que registra, para
  cada clipe, a condição, a câmera, o Last-Modified e o ETag de origem. Os
  vídeos (~32 MB cada) ficam em `tests/ground_truth/clipes/`, único diretório
  ignorado pelo git — a separação é por diretório e não por extensão, para que
  nenhum padrão amplo de vídeo varra junto as fixtures de validação. Os CSVs são
  poucos KB e representam horas de trabalho irrecuperável, já que a URL não
  guarda histórico para recontar, então quem clonar o repositório vê qual foi a
  contagem de referência mesmo sem os vídeos. Sem os arquivos de vídeo a
  validação é pulada com aviso que nomeia o clipe ausente a partir do manifest —
  e como o `audit.py` trata teste pulado igual a teste que falhou, o gate reprova
  em vez de passar em silêncio. Afeta AC-014.5.
- [x] SUP-045 — Cada clipe de referência tem um CSV ao lado com uma linha por
  veículo contendo instante do cruzamento, categoria e sentido. É o único formato
  que torna AC-014.2 real: sem o instante não há pareamento, e o acerto de
  categoria viraria comparação de totais, em que erros opostos se cancelam.
  Afeta AC-014.1, AC-014.2 e AC-015.1.
- [x] SUP-046 — O pareamento entre veículo automático e manual é feito por
  sentido, dentro de uma janela de 2 s no instante do cruzamento, casando cada
  veículo manual com no máximo um automático. Afeta AC-014.2.
- [x] SUP-047 — A validação roda sob marcador pytest `accuracy`, fora da suíte
  rápida, conforme já previsto no README. Afeta AC-014.3 e AC-014.4.
- [x] SUP-048 — A contagem manual é feita uma vez, por uma pessoa, sem segunda
  conferência; o erro humano do ground truth não é medido e entra como limitação
  declarada do trabalho. Consequência assumida: não há parâmetro para saber se um
  erro de 8% do sistema está dentro ou fora do ruído da própria referência.
  Afeta AC-014.1.
- [x] SUP-049 — O relatório é gravado como arquivo de texto no diretório de dados,
  legível sem ferramenta especial, para poder ser citado no TCC. Afeta AC-015.1.
- [x] SUP-050 — Os clipes de referência são obtidos com a opção de preservar
  vídeos da própria captura, e não por download manual à parte: roda-se uma
  sessão em cada uma das três condições e escolhe-se um minuto de cada. Afeta
  AC-014.5.

## Perguntas em aberto

Nenhuma pendente. Os IDs permanecem como histórico das decisões.

- [x] Q-007 — A meta vale por clipe ou na média dos três? **Respondida: por
  clipe, os 3 precisam passar.** É a leitura literal da meta acordada e a única
  que sustenta a afirmação sem asterisco. Risco aceito explicitamente: YOLO11n em
  720p à noite é o cenário mais provável de reprova, e a `CLAUDE.md` proíbe
  afrouxar o número depois para acomodar o resultado. Está em AC-014.3.
- [x] Q-008 — Qual é a terceira condição do conjunto de referência? **Respondida:
  noturno fixo; chuva vira clipe extra opcional.** Noite existe todo dia e cabe
  numa única jornada de coleta; chuva não se agenda e, com a meta valendo por
  clipe, um clipe que talvez nunca exista bloquearia a entrega inteira. Se houver
  chuva durante o projeto, o clipe é coletado, contado e reportado em AC-015.1
  sem poder reprovar.

## Specs afetadas

Revisado história por história.

- `contagem-veiculos` — esta feature mede a saída de AC-006.1 e AC-006.3 e é o
  juiz do padrão de amostragem de SUP-017: se a configuração padrão não atender a
  AC-014.3, ela precisa mudar, ainda que isso estoure o orçamento de AC-005.4.
  AC-006.6, que limita a um evento por rastreio e sentido, muda diretamente os
  números comparados aqui — é o que dá chance ao clipe de pico de fechar em 10%.
- `captura-clipes` — AC-014.5 depende dos clipes preservados pela opção de
  SUP-012 e AC-003.5; sem essa opção não existe conjunto de referência. As três
  sessões de coleta descritas em SUP-050 usam o fluxo normal de US-003.
- `persistencia-resultados` — AC-014.1 compara contra os eventos gravados por
  AC-008.2.
- `configuracao-camera` — deixou de haver bloqueio: com Q-001 respondida, os
  clipes de referência saem da câmera 000013, cujas características medidas estão
  no Contexto daquela spec.

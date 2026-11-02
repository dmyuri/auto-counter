# Feature: contagem-veiculos

## Contexto

Segunda fase da sessão: os clipes já estão no disco e são processados sem
pressão de tempo real. Para cada clipe o sistema detecta veículos, rastreia-os
dentro daquele clipe e registra um evento sempre que um veículo cruza a linha de
contagem da câmera, com o sentido do cruzamento.

As quatro categorias — carro, moto, ônibus e caminhão — são as que o modelo
pré-treinado entrega sem retreino. São imutáveis: incluir uma quinta categoria é
mudança de schema e exige migration nova, conforme `CLAUDE.md`.

O rastreador é reiniciado a cada clipe, porque os clipes são arquivos
independentes. Isso cria o problema da emenda: um veículo em cima da linha no
corte entre dois clipes pode ser contado duas vezes. Uma sessão de 15 minutos
tem 14 emendas. US-007 trata exatamente disso, com uma janela de deduplicação de
2 s de cada lado do corte.

Orçamento de performance, derivado da decisão de processar 15 min de vídeo em até
20 min na máquina de referência (notebook 4 núcleos, 8 GB, sem GPU):
15 min × 60 s × 30 fps ≈ 27.000 frames; amostrando 1 frame a cada 3 restam ~9.000
frames analisados em 1.200 s, ou seja, no máximo 133 ms por frame analisado.

O teto começou em 100 ms, derivado de processar 15 min de vídeo em 15 min. A
medição na máquina de referência deu 117,7 ms por frame (9.000 frames em
1.059,4 s), e o autor do projeto renegociou o orçamento para 20 min em vez de
mexer na amostragem: **a captura e o processamento são fases sequenciais, não
simultâneas**, então o processamento nunca precisou caber no tempo da captura —
a premissa que produzia os 15 min era mais forte do que o projeto exige. A
amostragem de SUP-017 fica intocada, e com ela a acurácia de AC-014.3.

## Histórias

US-005 — Detectar e classificar veículos
Como integrante do projeto de extensão, quero que o sistema identifique os
veículos e o tipo de cada um, para que a planilha separe o fluxo por categoria.

Critérios de aceite:
  AC-005.1 — Dado um frame com objetos de várias classes, quando o detector roda,
  então apenas detecções de carro, moto, ônibus e caminhão são mantidas, e
  qualquer outra classe do modelo (pessoa, bicicleta, semáforo e demais) é
  descartada antes do rastreamento.

  AC-005.2 — Dado uma detecção com confiança abaixo do limiar configurado, quando
  o sistema filtra as detecções do frame, então ela não é entregue ao rastreador.

  AC-005.3 — Dado um clipe de 59,93 s a 30 fps e a taxa de amostragem
  configurada, quando o clipe é processado, então o número de frames analisados
  corresponde à taxa declarada e os demais frames não passam por inferência.

  AC-005.4 — Dado a máquina de referência e a configuração padrão, quando uma
  sessão de 15 minutos já baixada é processada, então o tempo médio por frame
  analisado é de no máximo 133 ms.

US-006 — Contar cruzamentos da linha com sentido
Como docente responsável pelo projeto, quero que cada veículo que atravessa a
linha gere um registro com horário, tipo e sentido, para poder analisar o fluxo
por mão da via.

Critérios de aceite:
  AC-006.1 — Dado um veículo rastreado cuja trajetória passa de um lado da linha
  para o outro, quando o sistema avalia o cruzamento, então registra exatamente
  um evento contendo timestamp, categoria, sentido e id de rastreio.

  AC-006.2 — Dado um veículo rastreado que se aproxima da linha mas não a
  atravessa, quando o sistema avalia sua trajetória, então nenhum evento é
  registrado.

  AC-006.3 — Dado dois veículos atravessando a linha em sentidos opostos, quando
  o sistema avalia os cruzamentos, então cada evento recebe o rótulo de sentido
  correspondente à sua direção, conforme os rótulos configurados para aquela
  câmera.

  AC-006.4 — Dado um veículo que atravessa a linha e em seguida a atravessa de
  volta no sentido oposto dentro do mesmo clipe, quando o sistema avalia, então
  registra dois eventos, um em cada sentido.

  AC-006.5 — Dado o Last-Modified do clipe e o índice do frame em que o
  cruzamento ocorreu, quando o evento é registrado, então seu timestamp é o
  início do clipe somado ao deslocamento do frame, com resolução de 1 segundo.

  AC-006.6 — Dado um mesmo id de rastreio que dispara mais de um cruzamento no
  mesmo sentido dentro de um clipe, quando o sistema avalia os cruzamentos, então
  apenas o primeiro deles gera evento — no máximo um evento por id de rastreio em
  cada sentido.

US-007 — Não contar duas vezes na emenda entre clipes
Como docente responsável pelo projeto, quero que um veículo que passa bem no
corte entre dois clipes seja contado uma vez só, para que o total não seja
inflado pela forma como o vídeo é entregue.

Critérios de aceite:
  AC-007.1 — Dado um veículo que cruza a linha nos últimos 2 s de um clipe e um
  cruzamento de assinatura compatível nos primeiros 2 s do clipe imediatamente
  seguinte, quando o segundo clipe é processado, então o segundo cruzamento não
  gera novo evento.

  AC-007.2 — Dado dois veículos distintos, um cruzando no fim de um clipe e outro
  cruzando no início do clipe seguinte com assinatura diferente, quando os clipes
  são processados, então os dois eventos são registrados.

  AC-007.3 — Dado a passagem de um clipe para o seguinte, quando o próximo clipe
  começa a ser processado, então o estado do rastreador é reiniciado e nenhum id
  de rastreio é reaproveitado entre clipes.

  AC-007.4 — Dado que o minuto entre dois clipes processados foi marcado como não
  capturado, quando o clipe posterior é processado, então a janela de
  deduplicação de emenda não é aplicada, porque os dois clipes não são
  adjacentes, e todos os cruzamentos são contados.

## Fora de escopo

- Categorias além das quatro fixadas, incluindo bicicleta, pedestre e
  subdivisões de caminhão.
- Retreino ou ajuste fino do modelo de detecção com dados da NitTrans.
- Leitura de placa, identificação de veículo específico ou qualquer dado pessoal.
- Estimativa de velocidade, de ocupação de faixa ou de tempo de fila.
- Continuidade de identidade de veículo entre clipes: o rastreador reinicia, e a
  única ponte entre clipes é a janela de deduplicação de US-007.
- Processamento com GPU.

## Suposições

- [x] SUP-015 — A detecção usa YOLO11n exportado para ONNX, executado no ONNX
  Runtime em CPU, com entrada de 640×640. Afeta AC-005.1 e AC-005.4.
- [x] SUP-016 — O limiar de confiança padrão é 0,35, configurável, e o valor
  usado fica registrado na sessão. Afeta AC-005.2.
- [x] SUP-017 — A amostragem padrão é 1 frame a cada 3 (10 fps efetivos),
  configurável. O padrão só é válido se sustentar ao mesmo tempo o orçamento de
  AC-005.4 e a meta de acurácia de AC-014.3 — se conflitarem, quem manda é a
  acurácia e o orçamento de tempo é renegociado. Foi exatamente o que aconteceu:
  a medição deu 117,7 ms contra os 100 ms originais, e quem cedeu foi o
  orçamento, que passou a 133 ms — a amostragem continua 1 a cada 3, e a
  acurácia de AC-014.3 não foi tocada para caber no tempo. Afeta AC-005.3 e
  AC-005.4.
- [x] SUP-018 — O rastreamento usa ByteTrack, da biblioteca supervision, e o
  ponto do veículo é o centro da base da caixa delimitadora (contato com o
  solo). O cruzamento é a troca de lado da linha desse ponto entre a última
  posição conhecida da trilha dentro da faixa perpendicular ao segmento da linha
  e a posição atual, sem descartar, dentro do clipe, a trilha que some da
  detecção por alguns frames. A regra substituiu o LineZone da supervision em
  2026-11-02: na versão 0.30, o LineZone apaga o histórico da trilha ausente por
  2 frames analisados seguidos e perdia o cruzamento de veículos detectados de
  forma intermitente, como motos encobertas por carros, o que foi medido na
  sessão 000013-20261102T010600Z. Afeta AC-006.1 e AC-006.2.
- [x] SUP-019 — A assinatura usada para deduplicar a emenda é a tripla categoria +
  sentido + posição do cruzamento ao longo da linha, com tolerância de 10% do
  comprimento da linha. Afeta AC-007.1 e AC-007.2.
- [x] SUP-021 — Sessões com status INVÁLIDA são processadas normalmente: o status
  qualifica o resultado, não impede o processamento. Confirmado pela resposta de
  Q-005, que manteve a geração da planilha para essas sessões. Afeta AC-007.4.
- [x] SUP-023 — A categoria do evento é a classe mais frequente entre os frames em
  que aquele id de rastreio foi detectado, e não a do frame do cruzamento, para
  reduzir troca de classe por oclusão momentânea. Afeta AC-006.1 e AC-006.3.

## Perguntas em aberto

Nenhuma pendente. Os IDs permanecem como histórico das decisões.

- [x] Q-004 — Como contar um veículo que oscila sobre a linha em fila parada?
  **Respondida: no máximo um evento por id de rastreio em cada sentido**, o que
  virou AC-006.6. A oscilação de fila repete sempre o mesmo sentido e é
  eliminada; a manobra de ida e volta usa dois sentidos diferentes e continua
  contando duas vezes, então AC-006.4 permanece válido sem alteração. O único
  caso perdido é o veículo que faz duas conversões completas no mesmo minuto.

## Specs afetadas

Revisado história por história.

- `configuracao-camera` — AC-006.3 consome os rótulos de sentido de AC-001.1 e a
  orientação de linha de SUP-003; nenhuma alteração daquela spec.
- `captura-clipes` — AC-007.4 exige a lista de minutos perdidos produzida por
  AC-004.5 e AC-004.6. Além disso, AC-003.5 só pode apagar os vídeos depois que
  esta feature terminar, o que impõe ordem entre as duas fases. AC-003.6 entrega
  sessões de duração menor que a pedida, que esta feature processa sem
  tratamento especial.
- `persistencia-resultados` — AC-008.2 grava exatamente os campos de evento
  definidos em AC-006.1, e AC-008.1 registra a amostragem de SUP-017 e o limiar
  de SUP-016. Com AC-006.6, a contagem gravada passa a ter no máximo um evento
  por rastreio e sentido, o que reduz o volume de eventos em horário de pico.
- `validacao-acuracia` — AC-014.1 e AC-014.2 medem a saída desta feature, e o
  pareamento de AC-014.2 assume os campos de AC-006.1. AC-006.6 muda os números
  comparados lá: sem ela, o clipe de pico tenderia a estourar a meta de 10%.

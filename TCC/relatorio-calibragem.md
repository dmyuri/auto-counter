# Relatório de calibração da contagem automática de veículos

Câmera 000013 (Praça Getúlio Vargas, Niterói), sessões de 1º e 2 de novembro de 2026.

## 1. Objetivo

Este relatório registra o processo de calibração da contagem automática: as medições feitas, as hipóteses testadas, a correção implementada e as limitações identificadas. O objetivo foi aproximar a contagem automática da contagem manual com os recursos disponíveis no projeto e documentar até onde foi possível chegar.

A referência é a meta de acurácia fixada na especificação antes de qualquer medição (`validacao-acuracia`):

- erro percentual absoluto de no máximo **10%** na contagem total de cada sentido;
- acerto de categoria de no mínimo **80%**.

As rodadas descritas aqui são **exploratórias**. Elas não substituem a validação formal contra o conjunto de referência previsto na especificação.

## 2. Sistema avaliado

| Componente | Configuração |
|---|---|
| Detecção | YOLO11n pré-treinado no COCO, exportado para ONNX (`yolo11n.onnx@2b0c33ca3fef`), entrada 640×640, ONNX Runtime em CPU |
| Categorias | carro, moto, ônibus e caminhão (classes COCO 2, 3, 5 e 7) |
| Limiar de confiança | 0,35 |
| Amostragem | 1 frame analisado a cada 3 (10 fps efetivos, sobre vídeo de 30 fps) |
| Rastreamento | ByteTrack da biblioteca `supervision` (versão 0.30.2) |
| Cruzamento | troca de lado da linha de contagem pelo ponto de contato com o solo (centro da base da caixa) |
| Vídeo | clipes de 1 minuto, 1280×720, 30 fps, H.264 |

## 3. Metodologia

### 3.1 Coleta

Foram capturadas duas sessões de 3 minutos consecutivos, com preservação dos vídeos (`--keep-clips`), para permitir o reprocessamento do mesmo material com configurações diferentes:

| Sessão | Horário local | Condição | Status da captura |
|---|---|---|---|
| `000013-20261102T010600Z` | 01/11/2026, cerca de 22h02 | noturna, com iluminação pública | completa (3 de 3 minutos) |
| `000013-20261102T155810Z` | 02/11/2026, cerca de 12h54 | diurna, volume alto | completa (3 de 3 minutos) |

### 3.2 Contagem manual

Os veículos de cada clipe foram contados manualmente por uma pessoa, em uma única passagem, por minuto e por categoria. Na sessão noturna também foram anotados o instante e o sentido de cada moto, o que permitiu cruzar a contagem manual com as detecções do modelo.

### 3.3 Comparação e experimentos

A contagem automática foi comparada com a manual por categoria e por minuto. Para testar cada hipótese, a sessão noturna foi reprocessada em uma **cópia**, sem alterar os resultados gravados, variando um fator de cada vez:

- limiar de confiança do detector;
- limiar de ativação de trilhas do ByteTrack;
- regra de cruzamento (com e sem o descarte do histórico de trilhas ausentes);
- área de detecção (frame inteiro ou recorte em volta da linha);
- modelo (YOLO11n e YOLO11s).

Além da contagem final, foram inspecionadas as etapas intermediárias: as detecções brutas próximas da linha, por classe e faixa de confiança; a proporção de detecções que viram trilha; e o trajeto das trilhas de moto em relação à linha.

## 4. Resultado inicial (configuração padrão)

### 4.1 Sessão noturna

| Categoria | Manual | Automático | Diferença |
|---|---:|---:|---:|
| Carro | 36 | 34 | −2 |
| Moto | 11 | 0 | −11 |
| Ônibus | 4 | 3 | −1 |
| Caminhão | 0 | 1 | +1 |
| **Total** | **51** | **38** | **−13 (erro de 25,5%)** |

O caminhão contado no minuto 3 corresponde, pelo instante e pela contagem manual daquele minuto, a um ônibus classificado como caminhão.

### 4.2 Leitura inicial

A diferença está concentrada nas motos: **nenhuma das 11 foi contada**. Sem as motos, a contagem ficaria em 38 contra 40 veículos, um erro de cerca de 5%.

## 5. Investigação das motos

### 5.1 Ajuste do limiar de confiança

A primeira hipótese foi que as motos eram detectadas com confiança abaixo do limiar e descartadas. Baixar o limiar de 0,35 até 0,15 **não recuperou nenhuma moto** e acrescentou apenas 1 carro (erro de 23,5%).

### 5.2 O que o modelo detecta perto da linha

As detecções foram inspecionadas sem filtro de classe nem de limiar, em todos os frames analisados. Cruzando com os instantes anotados na contagem manual:

- o modelo detectou como moto **8 ou 9 das 11 motos**, nos instantes corretos, mas quase sempre com confiança entre **0,10 e 0,35** e de forma intermitente (a moto aparece em alguns frames e some em outros);
- as motos não detectadas vinham no sentido Centro, de frente para a câmera;
- perto da linha há muitas detecções da classe **"pessoa"** com confiança acima de 0,35. O modelo reconhece o **piloto**, e não o conjunto moto e piloto. A classe "pessoa" é descartada pelo sistema, como determina a especificação.

### 5.3 Rastreamento e cruzamento

No minuto 2 da sessão noturna, uma moto foi detectada com confiança acima de 0,35 em 52 frames e rastreada do início ao fim pela mesma trilha. A trilha atravessa a linha de contagem dentro do segmento, mas **nenhum evento foi registrado**.

A causa foi encontrada na biblioteca `supervision` (versão 0.30.2): o `LineZone`, componente que decidia o cruzamento, **apaga o histórico de uma trilha quando ela fica 2 frames analisados seguidos sem detecção** enquanto outros veículos estão em cena. A moto foi vista antes da linha, ficou 4 frames sem ser detectada (encoberta por um carro que passava ao lado) e reapareceu depois da linha. Como o histórico tinha sido apagado nesse intervalo, a troca de lado nunca foi percebida.

Carros raramente somem da detecção e, por isso, quase não são afetados. Motos, menores e frequentemente encobertas por outros veículos, são as mais prejudicadas.

### 5.4 Limiar de ativação de trilhas

Com a regra de cruzamento corrigida para a medição, também foi baixado o limiar a partir do qual o ByteTrack abre uma trilha nova, junto com o limiar do detector, até 0,10. O resultado não mudou: no minuto 1, as detecções de moto que chegam ao rastreador sobem de 4 para 47, e **nenhuma vira trilha**, por terem confiança baixa e intermitente demais para confirmar uma trilha. Em contrapartida, as detecções de carro viraram ruído: 4.278 detecções, das quais só 29% foram rastreadas.

### 5.5 Recorte em volta da linha

Para que a moto chegasse maior ao modelo, a detecção foi feita apenas em um recorte da via em volta da linha (região de 850×330 px). O recorte não recuperou motos e piorou a contagem de carros (32 de 36), porque veículos que cruzam a linha perto da borda do recorte deixaram de ser rastreados. Foi descartado.

### 5.6 Modelo maior (YOLO11s)

O YOLO11s, versão maior da mesma família, também pré-treinada no COCO, foi exportado com a mesma resolução de entrada e aplicado à mesma sessão.

| Modelo | Carro (36) | Moto (11) | Ônibus (4) | Caminhão (0) | Erro total | Tempo de detecção por frame* |
|---|---:|---:|---:|---:|---:|---:|
| YOLO11n | 35 | 1 | 3 | 1 | 21,6% | 90 ms |
| YOLO11s | 35 | 2 | 4 | 0 | 19,6% | 206 ms |

\* Ambos com a regra de cruzamento corrigida, medidos na máquina de desenvolvimento, que não é a máquina de referência da especificação.

O YOLO11s corrigiu a confusão entre ônibus e caminhão, mas o ganho em motos foi marginal (1 moto a mais) e o tempo de detecção ficou **2,3 vezes maior**. Na máquina de referência, onde o YOLO11n mede cerca de 118 ms por frame, isso corresponde a cerca de 270 ms, o dobro do orçamento de 133 ms por frame fixado na especificação.

### 5.7 Consolidado dos experimentos (sessão noturna)

| Configuração | Carro (36) | Moto (11) | Ônibus (4) | Caminhão (0) | Total (51) | Erro |
|---|---:|---:|---:|---:|---:|---:|
| Padrão (limiar 0,35, com `LineZone`) | 34 | 0 | 3 | 1 | 38 | 25,5% |
| Limiar 0,15 a 0,25, com `LineZone` | 35 | 0 | 3 | 1 | 39 | 23,5% |
| Cruzamento corrigido, limiar 0,35 | 35 | 1 | 3 | 1 | 40 | 21,6% |
| Cruzamento corrigido, limiar e ativação até 0,10 | 35 | 1 | 3 | 1 | 40 | 21,6% |
| Recorte em volta da linha | 32 | 1 | 3 | 0 | 36 | 29,4% |
| YOLO11s, cruzamento corrigido | 35 | 2 | 4 | 0 | 41 | 19,6% |

## 6. Correção implementada

A regra de cruzamento foi reimplementada no próprio projeto, no lugar do `LineZone`. O cruzamento passou a ser decidido pela **troca de lado da linha entre a última posição conhecida da trilha e a posição atual**, considerando apenas posições dentro da faixa perpendicular ao segmento da linha. Uma trilha que some da detecção por alguns frames não perde essa posição dentro do clipe.

O comportamento anterior que estava correto foi preservado:

- atravessar o prolongamento da linha, fora do segmento, não conta;
- o sentido continua sendo dado pela normal da linha configurada para a câmera;
- continua valendo no máximo um evento por trilha e sentido.

A mudança foi registrada na especificação (`contagem-veiculos`, SUP-018) e coberta por testes automatizados. Entre eles está o caso de um veículo que some por 4 frames, com outro veículo em cena, e reaparece do outro lado da linha. Esse teste falhava com o `LineZone` e passa com a nova regra. A suíte rápida do projeto passou integralmente depois da mudança (commit `9f3ce4b`).

Na sessão noturna, a correção recuperou 1 moto e 1 carro: o erro total caiu de **25,5% para 21,6%**.

## 7. Verificação na sessão diurna

A sessão diurna foi processada já com a correção e com a configuração padrão.

| Categoria | Manual | Automático | Diferença |
|---|---:|---:|---:|
| Carro | 66 | 64 | −2 |
| Moto | 17 | 3 | −14 |
| Ônibus | 4 | 4 | 0 |
| Caminhão | 0 | 0 | 0 |
| **Total** | **87** | **71** | **−16 (erro de 18,4%)** |

Por minuto, a contagem de carros foi de 24 contra 25, 15 contra 16 e 25 contra 25. O volume de carros por minuto foi alto e a contagem se manteve próxima da manual. A diferença está, de novo, nas motos, que se concentraram nos minutos 2 e 3 (9 e 7 motos), passando em grupo e entre os carros.

O mesmo diagnóstico da sessão noturna foi aplicado à sessão diurna, e o padrão se repetiu:

- **Só 3 trilhas de moto cruzaram a linha** nos 3 minutos (duas no minuto 2 e uma no minuto 3), com 10 a 22 detecções cada. São exatamente as 3 motos contadas pelo sistema. A regra de cruzamento corrigida registrou todas as trilhas de moto que atravessaram a linha.
- **As demais motos foram detectadas como moto em um único frame ou em nenhum.** Com uma detecção isolada não se forma trilha, e sem trilha não há cruzamento.
- **Perto da linha, a classe "pessoa" predomina sobre a classe "moto"**, como na sessão noturna. No minuto 3, foram 670 detecções brutas de "pessoa" com confiança acima de 0,35 contra 72 de "moto". O modelo reconhece o piloto, mas não o conjunto moto e piloto.

Os números de detecções brutas são contados antes da supressão de caixas duplicadas e por isso não correspondem ao número de veículos. Eles servem para comparar as classes entre si. A sessão diurna confirma, assim, que a subcontagem de motos não depende da iluminação e não é efeito do rastreamento ou da regra de cruzamento.

## 8. Discussão

### 8.1 Desempenho por categoria

| Categoria | Noturna (após a correção) | Diurna (após a correção) |
|---|---|---|
| Carro | 35 de 36 (erro de 2,8%) | 64 de 66 (erro de 3,0%) |
| Ônibus | 3 de 4 | 4 de 4 |
| Moto | 1 de 11 | 3 de 17 |
| Total sem motos | 39 de 40 (erro de 2,5%) | 68 de 70 (erro de 2,9%) |
| **Total geral** | **40 de 51 (erro de 21,6%)** | **71 de 87 (erro de 18,4%)** |

Para carros e ônibus, a contagem automática ficou abaixo do limite de 10% nas duas condições, inclusive com volume alto. **A meta para o total não foi atingida** nas duas sessões, e a causa é a mesma: a subcontagem de motos.

### 8.2 Causa da subcontagem de motos

A investigação descartou, uma a uma, as causas ajustáveis por parâmetro:

1. **Limiar de confiança:** baixá-lo não recupera motos. As detecções de moto são poucas e intermitentes, e não apenas fracas.
2. **Amostragem e rastreamento:** quando o modelo detecta a moto com confiança suficiente, ela é rastreada normalmente. Ela se perdia apenas no descarte de histórico do `LineZone`, que foi corrigido.
3. **Resolução:** o recorte, que aumenta o tamanho aparente da moto, não trouxe ganho.
4. **Capacidade do modelo:** o modelo maior da mesma família trouxe ganho marginal.

A causa remanescente é a **adequação do modelo pré-treinado ao cenário**. Os modelos treinados no conjunto COCO reconhecem, neste enquadramento, o piloto como "pessoa" e a moto apenas de forma esporádica e com baixa confiança. Isso acontece tanto de dia quanto à noite. Contribuem a perspectiva elevada da câmera, o tamanho reduzido da moto no quadro e a oclusão frequente por carros, já que as motos costumam circular entre as faixas.

### 8.3 Alternativas descartadas

- **Contar a classe "pessoa" que cruza a linha como moto:** a linha fica junto de uma faixa de pedestres, e pedestres passariam a ser contados como veículos.
- **Adotar o YOLO11s:** dobra o custo de processamento, ultrapassa o orçamento de tempo da especificação e acrescenta apenas uma moto.
- **Reduzir o limiar de confiança:** não recupera motos e aumenta o ruído nas detecções de carro.

## 9. Limitações deste estudo

- **Amostra pequena:** duas sessões de 3 minutos (138 veículos contados manualmente), em um único ponto e em um único dia de cada condição.
- **Contagem manual única:** feita por uma pessoa, sem segunda conferência. O erro da própria referência não foi medido.
- **Comparação por totais:** a comparação foi feita por categoria e por minuto. Sem o instante e o sentido de cada veículo, não foi possível parear veículo a veículo. Por isso o erro por sentido e o acerto de categoria da meta não foram calculados. Só as motos da sessão noturna foram anotadas com instante e sentido.
- **Calibração e medição no mesmo material:** os experimentos foram avaliados na mesma sessão noturna em que as hipóteses foram formuladas. A sessão diurna serviu como verificação independente apenas da configuração final.
- **Tempo de processamento:** os tempos da seção 5.6 foram medidos na máquina de desenvolvimento. Servem para comparar os modelos entre si, e não como medição do orçamento da especificação.

## 10. Conclusões e trabalhos futuros

O processo de calibração produziu três resultados:

1. **Uma falha de software foi identificada e corrigida.** O descarte do histórico de trilhas ausentes no `LineZone` fazia o sistema perder cruzamentos de veículos detectados de forma intermitente. A correção foi especificada, testada e incorporada ao sistema.
2. **A configuração padrão foi mantida** (YOLO11n, limiar 0,35, amostragem 1 a cada 3). Nenhuma variação de parâmetro testada trouxe ganho que justificasse a mudança.
3. **A limitação principal foi caracterizada.** Para carros e ônibus, o sistema ficou dentro da meta nas duas sessões. Para motos, ele não atinge a meta, por limitação do modelo pré-treinado neste cenário, e não por parâmetros de configuração.

Como trabalho futuro, a alternativa com maior potencial é o **ajuste fino (fine-tuning) do YOLO11n com imagens desta câmera**, anotando motos de dia e de noite. Ele ataca diretamente a causa identificada e mantém o mesmo custo de processamento. Também é recomendável repetir a medição com contagem manual por veículo (instante, categoria e sentido), para calcular o erro por sentido e o acerto de categoria previstos na meta.

## Apêndice: reprodutibilidade

- **Código:** commit `9f3ce4b` do repositório do projeto.
- **Modelo:** `yolo11n.onnx@2b0c33ca3fef` (`uv run auto-counter model export`).
- **Biblioteca de rastreamento:** `supervision` 0.30.2.
- **Calibração da câmera:** `config/cameras/000013.yaml`, linha de (1053, 348) a (351, 445).
- **Captura de uma sessão:**

  ```powershell
  uv run auto-counter session capture 000013 --minutes 3 --keep-clips
  ```

- **Processamento com a configuração padrão:**

  ```powershell
  uv run auto-counter session process <id_sessao>
  ```

- **Variação de limiar e amostragem:**

  ```powershell
  uv run auto-counter session process <id_sessao> --threshold 0.25 --sample-rate 2
  ```

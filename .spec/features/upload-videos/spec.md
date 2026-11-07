# Feature: upload-videos

## Contexto

Até aqui, o vídeo só tem uma origem: a URL pública da NitTrans, que expõe só o
último minuto. Por isso não existe seleção de data e hora, só "duração a partir
de agora" (Fora de escopo de `captura-clipes`). Um trecho gravado por outro
meio, como um download feito pela própria NitTrans ou uma gravação antiga, não
tem como ser contado.

O protótipo `Contagem de Veiculos.html` acrescenta uma segunda fonte, "Fazer
upload de vídeos — Processa arquivos enviados manualmente". O usuário:

- escolhe a câmera;
- arrasta ou seleciona vários arquivos;
- confere a duração e o tamanho de cada um;
- remove o que não quer;
- inicia o processamento.

Esta feature cobre essa entrada, da escolha da fonte até o botão de iniciar. O
que acontece depois do clique está em `processamento-upload`.

A câmera continua obrigatória no upload. A linha de contagem é calibrada em
pixels absolutos do frame de cada câmera (SUP-002), então um vídeo só é contado
no ponto certo se tiver sido gravado por aquela câmera, com aquele enquadramento
e na resolução da calibração. O sistema não consegue confirmar o enquadramento
a partir do arquivo, mas consegue conferir a resolução. Por isso a tela avisa de
qual câmera os vídeos precisam ser, e recusa todo vídeo cuja resolução seja
diferente da resolução de calibração da câmera (Q-019).

O envio tem limite: 1 GB por arquivo e 15 min de duração somada, o mesmo teto da
sessão ao vivo (Q-018).

## Histórias

US-026 — Escolher a fonte da sessão
Como integrante do projeto de extensão, quero escolher entre a câmera ao vivo e
vídeos que eu já tenho, para contar também trechos que a URL da câmera não guarda
mais.

Critérios de aceite:
  AC-026.1 — Dado a interface sem sessão em andamento, quando ela é exibida,
  então oferece as fontes "Câmera ao vivo" e "Fazer upload de vídeos", com
  exatamente uma marcada, e "Câmera ao vivo" vem marcada numa aba recém-aberta.

  AC-026.2 — Dado a fonte "Fazer upload de vídeos" marcada, quando a interface é
  exibida, então:
  - o campo de duração, os atalhos e a opção "Manter clipes de vídeo" não
    aparecem;
  - a área de envio aparece;
  - os cartões de câmera continuam disponíveis;
  - aparece o aviso "Envie apenas vídeos gravados pela <id>", com o nome do
    local da câmera selecionada.

  AC-026.3 — Dado a fonte de upload com arquivos na lista, quando o usuário
  passa para "Câmera ao vivo" e volta para o upload, então a lista continua com
  os mesmos arquivos, na mesma ordem.

  AC-026.4 — Dado a fonte "Câmera ao vivo" marcada e arquivos na lista de envio,
  quando o usuário inicia a sessão, então é disparada a sessão de captura de
  AC-011.4 e nenhum dos arquivos da lista entra nela.

  AC-026.5 — Dado uma sessão em andamento ou um resultado exibido, quando a
  interface é consultada, então a fonte não pode ser trocada, e a área de envio e
  os botões de remover ficam indisponíveis.

US-027 — Enviar e conferir os vídeos
Como integrante do projeto de extensão, quero ver a duração e o tamanho de cada
vídeo enviado e saber na hora se algum não serve, para só iniciar o
processamento com o material certo.

Critérios de aceite:
  AC-027.1 — Dado a área de envio, quando o usuário envia um ou mais arquivos
  de uma vez, arrastando ou selecionando, com extensão `.mp4`, `.mov`, `.avi` ou
  `.mkv`, sem diferença entre maiúsculas e minúsculas, e até 1 GB cada, então
  cada um entra na lista, na ordem em que foi recebido.

  AC-027.2 — Dado um arquivo com qualquer outra extensão, quando ele é enviado,
  então não entra na lista, e a interface mostra uma mensagem com o nome do
  arquivo e as quatro extensões aceitas.

  AC-027.3 — Dado um arquivo aceito, quando a leitura dele termina, então a
  linha mostra o nome, a duração em MM:SS e o tamanho. Abaixo da lista aparecem
  "N vídeos · <tamanho total>" e "duração total MM:SS", somando só os vídeos
  válidos.

  AC-027.4 — Dado um arquivo aceito pela extensão que não abre como vídeo
  legível, quando a leitura dele termina, então a linha fica marcada como
  inválida, com o motivo, e o arquivo fica fora da contagem de vídeos, da
  duração total e da sessão.

  AC-027.5 — Dado um vídeo da lista e a câmera selecionada, quando a resolução
  do vídeo é diferente da resolução de calibração daquela câmera, então a linha
  do vídeo fica marcada como inválida, com uma mensagem que cita as duas
  resoluções, e o vídeo fica fora da contagem de vídeos, da duração total e da
  sessão.

  AC-027.6 — Dado vídeos na lista, quando o usuário seleciona outra câmera,
  então o aviso de AC-026.2 passa a citar a nova câmera, e todos os vídeos da
  lista são avaliados de novo pela regra de AC-027.5 contra a resolução de
  calibração dela.

  AC-027.7 — Dado um arquivo cujo conteúdo é byte a byte igual ao de outro que já
  está na lista, quando ele é enviado, então ele entra na lista marcado como
  duplicata, com um aviso que cita o nome do arquivo igual. Continua válido, e
  entra na sessão se não for removido.

  AC-027.8 — Dado um arquivo na lista, quando o usuário aciona "Remover" naquela
  linha, então o arquivo sai da lista e dos totais. Se ele era o par de uma
  duplicata, o aviso de duplicata do outro arquivo some.

  AC-027.9 — Dado a fonte de upload, quando a interface é exibida, então o botão
  de iniciar:
  - fica indisponível com "Importe vídeos para iniciar" quando não há nenhum
    vídeo válido;
  - fica indisponível com "Lendo vídeos…" enquanto algum arquivo ainda está em
    leitura;
  - fora disso, fica disponível com "Processar N vídeos", em que N é o número
    de vídeos válidos, ou "Processar 1 vídeo" quando há um só, ressalvado
    AC-027.11.

  AC-027.10 — Dado um arquivo com mais de 1 GB (1.000.000.000 bytes), quando ele
  é enviado, então não entra na lista, e a interface mostra uma mensagem com o
  nome do arquivo e o limite de 1 GB.

  AC-027.11 — Dado vídeos válidos cuja duração somada passa de 15 min (900 s),
  quando a interface é exibida, então o botão de iniciar fica indisponível e a
  interface mostra uma mensagem com o limite de 15 min e a duração somada.

## Fora de escopo

- Reordenar os vídeos da lista: a ordem é a de recebimento (AC-027.1).
- Cortar, juntar ou editar vídeo antes de processar.
- Converter a resolução do vídeo para a da calibração, ou reescalar a linha
  para a resolução do vídeo.
- Enviar uma pasta inteira, ou indicar vídeo por URL ou caminho digitado.
- Usar vídeos de exemplo, como o botão do protótipo.
- Descobrir sozinho de qual câmera é o vídeo, ou confirmar que ele é da câmera
  selecionada além da resolução (AC-027.5).
- Processar vídeo de câmera que não está no registro: o upload usa a calibração
  de uma câmera cadastrada, e cadastrar continua fora da interface.
- Enviar vídeo de outra máquina: a interface continua só em 127.0.0.1
  (SUP-041).

## Suposições

- [x] SUP-082 — O envio usa o componente nativo de upload do Streamlit, que
  aceita arrastar e selecionar vários arquivos. O limite de 1 GB é conferido
  pela própria aplicação, em bytes, e não só pela configuração de tamanho do
  Streamlit, que usa outra unidade. Cada arquivo aceito é gravado num diretório
  de envio dentro de `AUTO_COUNTER_DATA_DIR` assim que chega, e é dali que
  partem a leitura e, depois, a sessão. A ordem de recebimento é a que o
  navegador entrega o lote. Afeta AC-027.1, AC-027.3 e AC-027.10.
- [x] SUP-083 — As quatro extensões aceitas são as do protótipo. A extensão só
  filtra o envio, e quem decide se o vídeo serve é a leitura. "Legível" segue
  SUP-011: o arquivo abre no OpenCV e o primeiro e o último frame são
  decodificáveis. A duração é lida do próprio arquivo (frames ÷ fps), truncada
  ao segundo, no formato de SUP-057. Afeta AC-027.1 a AC-027.4 e AC-027.11.
- [x] SUP-084 — Removida na revisão de 2026-11-07: a formatação do tamanho
  exibido não mudava o resultado. O limite de AC-027.10 é definido em bytes no
  próprio critério.
- [x] SUP-085 — Duplicata é conteúdo com o mesmo sha256, a regra de conteúdo de
  SUP-051, comparado com todos os arquivos da lista, e não só com o anterior.
  Por decisão do autor, a duplicata não é recusada: entra com aviso, e o usuário
  decide se remove. Se não remover, os veículos dela são contados de novo, como
  em qualquer outro vídeo. Nome igual com conteúdo diferente não é duplicata.
  Afeta AC-027.7 e AC-027.8.
- [x] SUP-086 — Conforme Q-019, cada câmera passa a declarar no YAML a resolução
  de calibração, a do frame em que a linha foi definida: `resolucao: {largura,
  altura}`, 1280×720 na 000013. O campo é obrigatório, como os demais de
  AC-001.2. A resolução do vídeo enviado é lida do próprio arquivo e comparada
  com ela. Com resolução igual, a linha sempre cabe no frame, porque já foi
  validada contra essas dimensões na calibração (AC-002.2). Afeta AC-027.5 e
  AC-027.6.
- [x] SUP-087 — A fonte padrão é "Câmera ao vivo", como no protótipo. A lista de
  envio vale para a aba aberta: se ela for fechada antes de iniciar, a lista se
  perde. Os arquivos do diretório de envio que não entraram em nenhuma sessão
  são apagados quando a próxima sessão de upload começa. Confirmado pelo autor.
  Afeta AC-026.1 e AC-026.3.

## Perguntas em aberto

Nenhuma pendente. Os IDs permanecem como histórico das decisões.

- [x] Q-018 — Qual é o limite do que pode ser enviado de uma vez? **Respondida:
  1 GB por arquivo e 15 min de duração somada**, o mesmo teto da sessão ao vivo,
  que mantém o processamento dentro de ~20 min na máquina de referência. A
  alternativa de 60 min no total levaria a ~80 min de processamento. Virou
  AC-027.10 e AC-027.11.
- [x] Q-019 — O que fazer com um vídeo de resolução diferente da usada na
  calibração da câmera? **Respondida: recusar.** O vídeo fica inválido, e a
  resolução de calibração passa a ser registrada em cada câmera (SUP-086). As
  alternativas eram reescalar a linha, que só acerta com o mesmo enquadramento,
  e aceitar com aviso. As duas permitiriam uma contagem errada sem erro
  nenhum. Virou AC-027.5 e AC-027.6.

## Specs afetadas

Revisado história por história.

- `captura-clipes`
  - Contexto e Fora de escopo, "Buscar trechos passados" e "não existe seleção
    de data e hora": continua valendo para a URL. O upload é a forma de contar
    um trecho passado sem passar por ela.
  - AC-003.3: o limite de 1 a 15 minutos não se aplica ao upload, que tem o
    limite equivalente de 15 min de duração somada (AC-027.11).
  - AC-004.3 e SUP-011: a regra de vídeo legível é reaproveitada em AC-027.4.
  - SUP-051: a regra de conteúdo por sha256 é reaproveitada em AC-027.7, mas
    comparando com a lista inteira e só para avisar, sem recusar (SUP-085).
- `configuracao-camera`
  - AC-001.1 e AC-001.2: o YAML de cada câmera ganha o campo obrigatório
    `resolucao` (SUP-086). Câmera sem esse campo passa a ser rejeitada, e o YAML
    da 000013 precisa recebê-lo (1280×720).
  - AC-002.2 e SUP-007: a linha passa a poder ser validada contra a resolução
    declarada, além das dimensões lidas do vídeo. Na sessão ao vivo, SUP-007
    continua valendo como está.
  - SUP-002: a linha em pixels absolutos é o motivo de AC-027.5.
  - Contexto, "A URL do vídeo é derivada do ID": a câmera passa a ser também a
    calibração aplicada a vídeos que não vieram da URL.
- `interface-sessao`
  - Contexto, "escolhe uma câmera... e define a duração de 1 a 15 minutos": no
    upload, a duração não é escolhida, porque é a dos vídeos.
  - AC-011.2: vale só para a fonte "Câmera ao vivo" (AC-026.2).
  - AC-011.1: o upload não é campo de id, URL ou endereço, então a proibição
    continua.
  - AC-013.1: a área de envio fica indisponível com sessão em andamento
    (AC-026.5).
  - Fora de escopo, "Publicação da interface na internet ou acesso por outra
    máquina": continua, e o envio também só acontece em 127.0.0.1.
- `layout-interface`
  - AC-020.1 a AC-020.5: os cartões continuam no upload, e a câmera selecionada
    é a do aviso e da validação de resolução.
  - AC-021.1 a AC-021.3: os atalhos de duração não aparecem no upload.
  - AC-023.6: "Nova sessão" volta à configuração com a lista de envio vazia,
    porque os vídeos da sessão anterior já entraram nela (SUP-087).
- `download-clipes`
  - AC-024.5: a opção de manter clipes não aparece no upload, e AC-026.2 a
    repete.
- `persistencia-resultados`
  - Contexto e Fora de escopo, sobre não guardar imagens: os vídeos enviados
    ficam no diretório de dados desde o envio. O descarte deles é o de
    `processamento-upload`.
- `contagem-veiculos`, `exportacao-xlsx`, `acompanhamento-ao-vivo` e
  `validacao-acuracia` — nenhum critério muda por esta feature. Revisado: tudo
  o que ela produz é uma lista de vídeos válidos, e quem os conta, grava, exporta
  e descarta é `processamento-upload`. A duplicata aceita com aviso (AC-027.7)
  pode dobrar a contagem de um trecho, o que é consequência aceita pelo autor, e
  não mudança de regra de contagem.

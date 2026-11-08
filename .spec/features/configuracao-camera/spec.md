# Feature: configuracao-camera

## Contexto

O sistema só opera câmeras previamente cadastradas e calibradas. A lista é
pré-definida e versionada no repositório: o usuário seleciona, nunca adiciona
nem edita. Cada câmera tem ID estável, nome do local, os rótulos dos seus dois
sentidos e uma linha de contagem própria — calibração de uma câmera nunca é
reaproveitada em outra.

A URL do vídeo é derivada do ID: `<base_url>/<id>/last_video.mp4`. A base URL
fica em variável de ambiente, nunca no código, conforme `.spec/constitution.md`.

A câmera do MVP é a **000013**, medida diretamente na fonte: responde com HTTP
200, 1280×720 a 30 fps, H.264, clipes de 59,93 s e ~32 MB, com `ETag` e
`Last-Modified` presentes em toda resposta. É a única câmera calibrada da
entrega; o mecanismo de lista existe para que outras sejam acrescentadas depois
sem alteração de código.

Esta é a feature base: nenhuma sessão de captura ou contagem pode começar sem
uma câmera válida vinda daqui.

Convenção de marcação usada em todas as specs: `- [x]` é item resolvido — SUP
decidida ou Q respondida — e `- [ ]` é pendência que faz o `audit.py` reprovar.
IDs nunca são reaproveitados nem apagados depois de criados.

## Histórias

US-001 — Registro versionado de câmeras
Como integrante do projeto de extensão, quero que o sistema conheça apenas as
câmeras já cadastradas e calibradas, para nunca rodar uma análise em câmera sem
linha de contagem válida.

Critérios de aceite:
  AC-001.1 — Dado o diretório de configuração com N arquivos de câmera válidos,
  quando o sistema carrega o registro, então retorna exatamente N câmeras, cada
  uma com id, nome do local, rótulo do sentido A, rótulo do sentido B e linha
  de contagem.
  > **Alterado por:** feature `layout-interface`, em 2026-11-07.
  > Cada câmera passa a poder declarar o campo opcional `preview`, com o
  > caminho da imagem exibida no cartão da interface (AC-020.2 e SUP-066).
  > Ver `.spec/features/layout-interface/spec.md`.

  > **Alterado por:** feature `upload-videos`, em 2026-11-07.
  > Cada câmera passa a ter também a resolução de calibração, no campo
  > `resolucao`, com a largura e a altura do frame em que a linha foi definida
  > (SUP-086).
  > Ver `.spec/features/upload-videos/spec.md`.

  AC-001.2 — Dado um arquivo de câmera sem um dos campos obrigatórios (id, nome,
  sentido_a, sentido_b, linha) ou com tipo inválido, quando o sistema carrega o
  registro, então esse arquivo é rejeitado com erro que nomeia o arquivo e o
  campo problemático, e as demais câmeras permanecem disponíveis.
  > **Alterado por:** feature `layout-interface`, em 2026-11-07.
  > O campo `preview` não entra entre os obrigatórios, e a falta dele ou um
  > caminho que não abre não rejeita a câmera (SUP-066).
  > Ver `.spec/features/layout-interface/spec.md`.

  > **Alterado por:** feature `upload-videos`, em 2026-11-07.
  > O campo `resolucao` passa a ser obrigatório, e o arquivo sem ele, ou com
  > tipo inválido, é rejeitado pela mesma regra (SUP-086).
  > Ver `.spec/features/upload-videos/spec.md`.

  AC-001.3 — Dado dois arquivos de câmera declarando o mesmo id, quando o
  sistema carrega o registro, então o carregamento falha com erro que cita o id
  duplicado e nenhuma câmera é disponibilizada.

  AC-001.4 — Dado uma câmera de id "000013" e a base URL configurada, quando o
  sistema monta a URL do clipe, então produz `<base_url>/000013/last_video.mp4`,
  preservando os zeros à esquerda do id.

  AC-001.5 — Dado que a variável de ambiente da base URL não está definida,
  quando o sistema tenta montar a URL de qualquer câmera, então falha com erro
  explícito e nenhuma URL embutida no código é usada como padrão.

US-002 — Calibração da linha de contagem
Como responsável pela manutenção do sistema, quero definir a linha de contagem
de uma câmera e conferi-la visualmente antes que ela valha, para garantir que a
contagem acontece no ponto certo da via.

Critérios de aceite:
  AC-002.1 — Dado uma câmera com linha definida por dois pontos em coordenadas
  de pixel, quando o comando de preview é executado, então grava um arquivo PNG
  contendo um frame daquela câmera, a linha desenhada entre os dois pontos e os
  rótulos dos sentidos A e B posicionados em lados opostos da linha.

  AC-002.2 — Dado uma linha com pelo menos um ponto fora dos limites do frame da
  câmera, quando o sistema valida a configuração, então rejeita a câmera com
  erro que cita a coordenada inválida e as dimensões do frame.
  > **Alterado por:** feature `upload-videos`, em 2026-11-07.
  > A linha passa a ser validada também contra a resolução declarada em
  > `resolucao`, que é a resolução que os vídeos enviados precisam ter
  > (AC-027.5 e SUP-086).
  > Ver `.spec/features/upload-videos/spec.md`.

  AC-002.3 — Dado uma linha cujos dois pontos são iguais (comprimento zero),
  quando o sistema valida a configuração, então rejeita a câmera com erro
  específico de linha degenerada.

  AC-002.4 — Dado uma câmera A com linha calibrada e uma câmera B cadastrada sem
  linha, quando o sistema carrega o registro, então B é rejeitada e em nenhuma
  hipótese a linha de A é aplicada a B.

## Fora de escopo

- Interface para o usuário final cadastrar, editar ou remover câmeras: a lista é
  pré-definida e alterá-la é tarefa de manutenção sobre os arquivos versionados.
- Tela clicável de calibração no navegador (descartada em favor do preview PNG).
- Descoberta automática de câmeras disponíveis no servidor da NitTrans.
- Detecção automática da posição da linha por heurística de fluxo.
- Múltiplas linhas ou contagem por faixa numa mesma câmera.

## Suposições

- [x] SUP-001 — O arquivo de cada câmera é um YAML em `config/cameras/<id>.yaml`,
  validado com Pydantic, com o campo `id` repetido dentro do arquivo e o id
  tratado como string (para preservar zeros à esquerda). Afeta AC-001.1,
  AC-001.3 e AC-001.4.
- [x] SUP-002 — A linha é declarada por dois pontos em coordenadas de pixel
  absolutas do frame original da câmera (1280×720 na 000013), não normalizadas.
  Afeta AC-002.1 e AC-002.2.
- [x] SUP-003 — O sentido é derivado da orientação da linha: o vetor de p1 para
  p2 define uma normal, e `sentido_a` rotula os cruzamentos que ocorrem no
  sentido dessa normal; `sentido_b` rotula o sentido oposto. Qual rótulo cai de
  cada lado é conferido no PNG de AC-002.1 no momento da calibração. Afeta
  AC-002.1.
- [x] SUP-005 — O frame do preview é o primeiro frame legível de um clipe baixado
  na hora pelo próprio comando. Afeta AC-002.1.
- [x] SUP-006 — FFmpeg não é dependência do projeto: a fonte é um arquivo `.mp4`
  progressivo obtido por HTTP e lido pelo OpenCV, que já embarca a decodificação
  H.264 de que precisa. Confirmado. O README ainda lista FFmpeg como
  pré-requisito e como forma de captura e precisa ser corrigido — correção
  pendente de autorização, fora do escopo desta spec. Afeta AC-002.1.
- [x] SUP-007 — As dimensões do frame usadas na validação da linha são lidas do
  próprio vídeo da câmera, não fixadas em código, porque outra câmera da NitTrans
  pode ter resolução diferente da 000013. Afeta AC-002.2.

## Perguntas em aberto

Nenhuma pendente. Os IDs permanecem como histórico das decisões.

- [x] Q-001 — Qual é o ID da câmera do MVP? **Respondida: 000013**, a câmera
  medida na fonte, com as características registradas em Contexto. Fecha o
  bloqueio de `validacao-acuracia`, que precisava saber de qual câmera sairiam os
  clipes de referência.
- [x] Q-002 — Quais são os rótulos dos dois sentidos? **Respondida: não é decisão
  de especificação.** Nenhum critério de aceite depende do texto dos rótulos,
  apenas de o campo existir, ser obrigatório (AC-001.2) e aparecer na saída. Os
  valores são preenchidos no YAML da 000013 durante a calibração de US-002,
  conferindo no PNG de AC-002.1 qual lado é qual.

## Specs afetadas

Revisado história por história. Esta feature não altera nem contradiz o
comportamento de nenhuma outra spec — ela é a base sobre a qual as demais foram
escritas. As dependências que ela cria:

- `captura-clipes` — AC-003.1 só aceita câmera vinda do registro definido em
  AC-001.1, e a URL que ela baixa é a montada em AC-001.4.
- `contagem-veiculos` — AC-006.3 usa os rótulos de sentido de AC-001.1 e a
  orientação de linha de SUP-003.
- `interface-sessao` — AC-011.1 lista exatamente as câmeras de AC-001.1, e
  AC-011.3 depende da rejeição de câmera sem linha definida em AC-002.4.
- `validacao-acuracia` — deixou de estar bloqueada: com Q-001 respondida, os 3
  clipes de referência de AC-014.1 saem da câmera 000013, e o orçamento de
  100 ms por frame de AC-005.4 vale para os 1280×720 a 30 fps medidos nela.

# Feature: exportacao-xlsx

## Contexto

Entrega final para o usuário. A planilha é lida por pessoas que não vão abrir o
banco nem rodar comando nenhum: o docente que analisa os dados e a banca do TCC.
Por isso ela precisa carregar, junto com os números, a informação de sob quais
condições eles foram produzidos.

São três abas, com papéis distintos:

- Eventos — um cruzamento por linha. É o dado bruto que permite responder "de
  onde veio esse número" na defesa.
- PorMinuto — o agregado pronto para gráfico, aproveitando que cada clipe já é
  um minuto.
- Sessao — os metadados: qual câmera, qual período real, qual status, o que
  faltou e com qual configuração o resultado foi produzido.

A exportação lê apenas do banco. Não decodifica vídeo, não roda detecção e
funciona depois que os clipes foram apagados.

Sessão INVÁLIDA também gera planilha. A alternativa seria recusar a exportação,
mas 15 minutos de captura não voltam e esconder o resultado não o torna mais
correto — o caminho escolhido é fazer o aviso viajar junto com o arquivo, dentro
das abas e no próprio nome dele.

## Histórias

US-010 — Exportar o resultado da sessão em XLSX
Como docente responsável pelo projeto, quero receber a contagem em uma planilha
que traga o dado bruto, o agregado por minuto e as condições da coleta, para
analisar o fluxo e saber o quanto posso confiar naqueles números.

Critérios de aceite:
  AC-010.1 — Dado uma sessão gravada, quando a exportação é executada, então é
  gerado um arquivo XLSX com exatamente três abas, nomeadas Eventos, PorMinuto e
  Sessao, cujo nome de arquivo identifica câmera, data, hora de início e duração.

  AC-010.2 — Dado a aba Eventos, quando a planilha é gerada, então ela tem uma
  linha por cruzamento com timestamp, categoria, sentido, id de rastreio e
  confiança, e o número de linhas é igual ao número de eventos daquela sessão no
  banco.

  AC-010.3 — Dado a aba PorMinuto, quando a planilha é gerada, então ela tem uma
  linha por minuto do período, com uma coluna para cada combinação de sentido e
  categoria mais o total do minuto, e um minuto não capturado aparece marcado
  como sem dado, visivelmente diferente de um minuto com contagem zero.

  AC-010.4 — Dado a aba Sessao, quando a planilha é gerada, então ela traz id e
  nome da câmera, os rótulos dos dois sentidos, período real, duração pedida,
  duração real, encerramento pelo usuário, status, lista dos minutos perdidos,
  versão do modelo, taxa de amostragem e limiar de confiança.

  AC-010.5 — Dado uma sessão com status DEGRADADA ou INVÁLIDA, quando a planilha
  é gerada, então o status e o percentual de minutos perdidos aparecem na
  primeira linha de cada uma das três abas e o status também aparece no nome do
  arquivo gerado.

  AC-010.6 — Dado a mesma sessão exportada duas vezes, quando as duas planilhas
  são comparadas, então o conteúdo das três abas é idêntico.

  AC-010.7 — Dado uma sessão cujos vídeos já foram apagados, quando a exportação
  é executada, então a planilha é gerada normalmente, sem acesso a arquivo de
  vídeo e sem acesso à rede.

## Fora de escopo

- Gráficos, tabelas dinâmicas, formatação condicional e qualquer visualização
  dentro da planilha: o arquivo entrega dados, a análise é feita pelo usuário.
- Exportar mais de uma sessão no mesmo arquivo ou consolidar períodos.
- Outros formatos de saída (CSV, JSON, PDF) nesta versão.
- Envio automático da planilha por e-mail, nuvem ou qualquer serviço externo.
- Recalcular ou corrigir contagem durante a exportação: o que sai é o que está
  gravado.
- Recusar a exportação de sessão INVÁLIDA.

## Suposições

- [x] SUP-032 — O nome do arquivo segue o padrão
  `<id_camera>_<AAAAMMDD>_<HHMM>_<N>min.xlsx` para sessão COMPLETA e recebe o
  sufixo do status quando ele não for COMPLETA, como em
  `000013_20260907_0800_15min_INVALIDA.xlsx`. Gravado no diretório de dados.
  Afeta AC-010.1 e AC-010.5.
- [x] SUP-033 — Os timestamps dos eventos e o período real da sessão são
  convertidos de UTC para o horário local de Brasília na exportação e escritos
  como data e hora reais do Excel, não como texto. A coluna de minuto da aba
  PorMinuto não é timestamp: é o minuto ordinal da sessão (1..N), como gravado
  pela persistência (D-4 de `persistencia-resultados`). Afeta AC-010.2,
  AC-010.3 e AC-010.4.
- [x] SUP-034 — A aba PorMinuto tem 11 colunas: minuto, estado do minuto, oito
  combinações de sentido e categoria (2 sentidos × 4 categorias) e o total.
  Afeta AC-010.3.
- [x] SUP-035 — Minuto sem dado é escrito como a palavra SEM_DADO na coluna de
  estado, com as colunas de contagem vazias — célula vazia, não zero. Afeta
  AC-010.3.
- [x] SUP-036 — Uma sessão com status INVÁLIDA gera planilha, com o aviso de
  AC-010.5 nas abas e no nome do arquivo, em vez de a exportação ser recusada.
  Confirmado pela resposta de Q-005. Afeta AC-010.5.
- [x] SUP-037 — A exportação de uma sessão ainda em andamento é recusada com erro,
  em vez de gerar planilha parcial. Afeta AC-010.6.

## Perguntas em aberto

Nenhuma pendente. Os IDs permanecem como histórico das decisões.

- [x] Q-005 — Uma sessão INVÁLIDA deve gerar planilha? **Respondida: sim, com
  aviso nas três abas e no nome do arquivo.** O risco levantado era o arquivo
  circular solto e virar gráfico em relatório sem ninguém ver o aviso; marcar o
  nome do arquivo faz o aviso chegar antes de a planilha ser aberta. Nenhuma
  outra spec precisou mudar: SUP-021 de `contagem-veiculos`, que manda processar
  a sessão inválida normalmente, continua coerente.

## Specs afetadas

Revisado história por história.

- `persistencia-resultados` — AC-010.2, AC-010.3 e AC-010.4 leem as tabelas de
  AC-008.1, AC-008.2 e AC-008.3, e AC-010.3 só funciona por causa da distinção
  entre SEM_DADO e zero fixada em SUP-028 e AC-008.4. AC-010.6 depende da
  idempotência de AC-008.5. AC-010.4 passou a imprimir a duração real e o
  encerramento pelo usuário, campos acrescentados a AC-008.1, e o nome da
  câmera, que levou à migration 002 acrescentando-o à linha de sessão.
- `captura-clipes` — AC-010.5 exibe os status de AC-004.4 a AC-004.6 e agora
  também no nome do arquivo. O conflito que estava anotado aqui deixou de
  existir: como a exportação de sessão INVÁLIDA foi mantida, SUP-021 de
  `contagem-veiculos` não precisa ser revisto. AC-010.4 imprime a duração real
  vinda de AC-003.6.
- `contagem-veiculos` — os rótulos de categoria e sentido das colunas de
  AC-010.3 vêm de AC-005.1 e AC-006.3; incluir uma quinta categoria mudaria
  SUP-034 e o schema.
- `configuracao-camera` — AC-010.4 imprime os rótulos de sentido de AC-001.1,
  cujos valores são preenchidos na calibração de US-002.
- `interface-sessao` — AC-012.3 oferece o download do arquivo gerado por
  AC-010.1. Como a exportação de sessão INVÁLIDA foi mantida, aquele critério não
  precisa de um caminho para sessão concluída sem planilha.

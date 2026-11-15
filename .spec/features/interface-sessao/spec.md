# Feature: interface-sessao

## Contexto

A superfície pela qual docente e integrantes usam o sistema. O pipeline vive em
comandos de linha, executáveis e testáveis sem navegador; o Streamlit é a casca
que expõe esses comandos para quem não usa terminal.

O usuário faz três coisas: escolhe uma câmera da lista pré-definida, define a
duração de 1 a 15 minutos e acompanha a sessão até poder baixar a planilha. Ele
não cadastra câmera, não digita URL nem ID, não calibra linha e não ajusta
parâmetro de detecção.

Uma sessão de 15 minutos leva ~15 min de captura mais até 15 min de
processamento, e é a única atividade da máquina nesse período: o sistema é
monousuário por decisão de escopo, e roda uma sessão por vez.

A sessão não depende da janela do navegador. A aba é uma vista sobre um processo
que roda por conta própria: fechá-la não encerra nada, e encerrar antes da hora
exige ação explícita — proteção contra perder minutos de captura que não voltam.

## Histórias

US-011 — Escolher câmera e duração
Como integrante do projeto de extensão, quero escolher a câmera numa lista e
definir por quantos minutos coletar, para iniciar uma análise sem conhecer
detalhe técnico nenhum do sistema.

Critérios de aceite:
  AC-011.1 — Dado um registro com N câmeras válidas, quando a interface é aberta,
  então ela apresenta exatamente essas N câmeras identificadas pelo nome do local
  e não oferece nenhum campo para digitar id, URL ou endereço de câmera.
  > **Alterado por:** feature `layout-interface`, em 2026-11-07.
  > As câmeras passam a aparecer em cartões com id, nome do local e imagem de
  > prévia, mantida a proibição de campo para digitar id, URL ou endereço
  > (AC-020.1 e AC-020.2).
  > Ver `.spec/features/layout-interface/spec.md`.

  AC-011.2 — Dado a interface aberta, quando o usuário informa a duração, então
  apenas valores inteiros de 1 a 15 minutos são aceitos para iniciar a sessão.
  > **Alterado por:** feature `upload-videos`, em 2026-11-07.
  > A duração de 1 a 15 minutos passa a valer só para a fonte "Câmera ao vivo",
  > e no upload ela não é escolhida, valendo o limite de 15 min de duração
  > somada dos vídeos (AC-026.2 e AC-027.11).
  > Ver `.spec/features/upload-videos/spec.md`.

  AC-011.3 — Dado um registro sem nenhuma câmera válida, quando a interface é
  aberta, então ela informa que não há câmera disponível e o comando de iniciar
  sessão fica indisponível.
  > **Alterado por:** feature `layout-interface`, em 2026-11-07.
  > O critério continua valendo e passa a ser detalhado para os cartões em
  > AC-020.6, que acrescenta que nenhum cartão é exibido.
  > Ver `.spec/features/layout-interface/spec.md`.

  AC-011.4 — Dado a linha de comando com uma câmera e uma duração válidas, quando
  o comando de sessão é executado, então o pipeline completo roda até a geração
  do XLSX sem que a interface web seja iniciada.

US-012 — Acompanhar a sessão em andamento
Como integrante do projeto de extensão, quero ver o progresso enquanto a sessão
roda, para saber que o sistema está trabalhando e quanto falta.

Critérios de aceite:
  AC-012.1 — Dado uma captura em andamento, quando um minuto é capturado ou
  perdido, então a interface passa a mostrar quantos minutos foram capturados do
  total pedido e quantos foram perdidos até ali.

  AC-012.2 — Dado uma sessão em andamento, quando a interface é consultada, então
  ela indica em qual das duas fases a sessão está, captura ou processamento, e o
  progresso dentro da fase atual.
  > **Alterado por:** feature `acompanhamento-ao-vivo`, em 2026-11-07.
  > Na fase de processamento a interface passa a mostrar também as quantidades
  > de carro, ônibus, caminhão, moto e total, atualizadas a cada veículo aceito,
  > e nas duas fases o tempo decorrido da sessão, mantido o progresso em minutos
  > (AC-016.1 a AC-016.8 e AC-017.1 a AC-017.3).
  > Ver `.spec/features/acompanhamento-ao-vivo/spec.md`.

  > **Alterado por:** feature `layout-interface`, em 2026-11-07.
  > O progresso da fase atual passa a vir acompanhado do percentual concluído,
  > do tempo estimado até o fim da sessão, da participação de cada categoria e
  > da taxa em veíc/min (AC-022.2 a AC-022.6).
  > Ver `.spec/features/layout-interface/spec.md`.

  > **Alterado por:** feature `processamento-upload`, em 2026-11-07.
  > A sessão de upload tem uma fase só, a de processamento, com o estado de
  > cada vídeo enviado (AC-028.1 e AC-028.3).
  > Ver `.spec/features/processamento-upload/spec.md`.

  AC-012.3 — Dado uma sessão concluída, quando o usuário acessa o resultado,
  então a interface exibe o status da sessão e oferece o download do XLSX
  correspondente àquela sessão.
  > **Alterado por:** feature `acompanhamento-ao-vivo`, em 2026-11-07.
  > O resultado da sessão concluída passa a exibir também as quantidades finais
  > por categoria, o total e o tempo total da sessão, sem mudar o status nem o
  > download (AC-018.1 e AC-018.2).
  > Ver `.spec/features/acompanhamento-ao-vivo/spec.md`.

  > **Alterado por:** feature `layout-interface`, em 2026-11-07.
  > O resultado passa para o painel "Sessão finalizada", com o cartão da
  > planilha mostrando o número de registros e a marca "✓ Baixado" depois do
  > download (AC-023.2 e AC-023.3).
  > Ver `.spec/features/layout-interface/spec.md`.

  > **Alterado por:** feature `download-clipes`, em 2026-11-07.
  > Com a opção "Manter clipes de vídeo" ligada, o resultado da sessão
  > concluída passa a listar os clipes para download individual e em `.zip`
  > (AC-025.1 a AC-025.4).
  > Ver `.spec/features/download-clipes/spec.md`.

  AC-012.4 — Dado uma sessão em andamento, quando a interface é fechada e aberta
  de novo, então a sessão continua em andamento, o progresso dela é reencontrado
  e nenhum minuto foi perdido por causa do fechamento; o encerramento antecipado
  só acontece por ação explícita do usuário.
  > **Alterado por:** feature `acompanhamento-ao-vivo`, em 2026-11-07.
  > Fechar e reabrir a interface passa a reencontrar também as quantidades
  > exibidas e o tempo decorrido, que continua contando do início da sessão
  > (AC-016.7 e AC-017.4).
  > Ver `.spec/features/acompanhamento-ao-vivo/spec.md`.

  > **Alterado por:** feature `layout-interface`, em 2026-11-07.
  > A ação explícita passa a ser o botão "Parar antecipadamente", com
  > confirmação, e reabrir a interface reencontra também o último resultado,
  > mesmo depois de "Nova sessão" (AC-023.1 e AC-023.7).
  > Ver `.spec/features/layout-interface/spec.md`.

  AC-012.5 — Dado uma sessão em processamento, quando o usuário a encerra
  explicitamente, então a contagem para sem terminar o clipe em análise, nenhum
  resultado de contagem é gravado, inclusive quando o pedido chega durante o
  último clipe, os vídeos da sessão permanecem em disco para reprocessamento e a
  interface informa que o processamento foi cancelado, sem oferecer download.
  > **Alterado em 2026-11-14:** "Dado uma sessão em processamento, quando o
  > usuário a encerra explicitamente, então a contagem para, nenhum resultado de
  > contagem é gravado, os vídeos da sessão permanecem em disco para
  > reprocessamento e a interface informa que o processamento foi cancelado, sem
  > oferecer download." Motivo: o critério não dizia quando a contagem para; a
  > parada era consultada só entre clipes, o usuário esperava o fim do clipe em
  > análise e o pedido feito durante o último clipe era ignorado, terminando a
  > sessão como concluída, com planilha.
  > **Alterado por:** feature `acompanhamento-ao-vivo`, em 2026-11-07.
  > O resultado da sessão cancelada passa a exibir o tempo total da sessão, sem
  > nenhuma quantidade de veículos e sem download, e as quantidades parciais
  > vistas durante o processamento deixam de aparecer (AC-018.3).
  > Ver `.spec/features/acompanhamento-ao-vivo/spec.md`.

  > **Alterado por:** feature `layout-interface`, em 2026-11-07.
  > O aviso de processamento cancelado passa a aparecer no painel de
  > resultados, sem cartão de planilha (AC-023.4).
  > Ver `.spec/features/layout-interface/spec.md`.

  AC-012.6 — Dado uma sessão encerrada em que nenhum clipe pôde ser processado,
  quando o usuário acessa o resultado, então a interface exibe o status da sessão
  e informa que não há planilha, sem oferecer download.
  > **Alterado por:** feature `acompanhamento-ao-vivo`, em 2026-11-07.
  > O resultado da sessão sem planilha passa a exibir o tempo total da sessão,
  > sem nenhuma quantidade de veículos e sem download (AC-018.3).
  > Ver `.spec/features/acompanhamento-ao-vivo/spec.md`.

  > **Alterado por:** feature `layout-interface`, em 2026-11-07.
  > O aviso de que não há planilha passa a aparecer no painel de resultados,
  > sem cartão de planilha (AC-023.4).
  > Ver `.spec/features/layout-interface/spec.md`.

  AC-012.7 — Dado uma sessão em captura iniciada pela interface, quando o
  usuário a encerra pelo botão "Parar antecipadamente" (AC-023.1), então a
  captura para, nenhum minuto segue para a contagem, os clipes já capturados são
  apagados do disco seja qual for a opção de manter os vídeos, o registro da
  sessão continua no banco marcado como cancelado pelo usuário (AC-008.6 de
  `persistencia-resultados`) e a interface informa "Sessão cancelada pelo
  usuário", sem oferecer download nem reprocessamento.

US-013 — Uma sessão por vez
Como integrante do projeto de extensão, quero que o sistema recuse iniciar uma
segunda sessão enquanto outra roda, para não disputar CPU e rede e acabar com as
duas sessões degradadas.

Critérios de aceite:
  AC-013.1 — Dado uma sessão em andamento, quando alguém tenta iniciar outra,
  então a segunda é recusada com mensagem que informa a câmera e o horário de
  início da sessão em curso, e a sessão em andamento não é afetada.
  > **Alterado por:** feature `upload-videos`, em 2026-11-07.
  > Com sessão em andamento, a área de envio de vídeos e os botões de remover
  > também ficam indisponíveis (AC-026.5).
  > Ver `.spec/features/upload-videos/spec.md`.

  > **Alterado por:** feature `processamento-upload`, em 2026-11-07.
  > A recusa passa a valer também entre sessão ao vivo e sessão de upload,
  > inclusive pelo comando `session upload` (AC-028.2 e SUP-098).
  > Ver `.spec/features/processamento-upload/spec.md`.

  AC-013.2 — Dado que o processo da sessão anterior terminou ou foi encerrado
  sem liberar a trava, quando uma nova sessão é iniciada, então a trava órfã é
  ignorada e a nova sessão começa normalmente.
  > **Alterado por:** feature `processamento-upload`, em 2026-11-07.
  > A trava órfã passa a ser ignorada também ao iniciar uma sessão de upload,
  > que pega a mesma trava pelo comando `session upload` (SUP-098).
  > Ver `.spec/features/processamento-upload/spec.md`.

## Fora de escopo

- Múltiplos usuários simultâneos, contas, login e controle de acesso.
- Execução agendada, recorrente ou disparada por evento.
- Monitoramento contínuo, painel ao vivo das câmeras e alerta.
- Cadastro, edição ou calibração de câmera pela interface.
- Ajuste de parâmetros de detecção (limiar, amostragem, modelo) pela interface.
- Publicação da interface na internet ou acesso por outra máquina.
- Visualização do vídeo com as caixas de detecção desenhadas.
- Encerrar a sessão por fechamento da aba ou por queda do navegador.

## Suposições

- [x] SUP-038 — O Streamlit chama a mesma camada de aplicação que a linha de
  comando; nenhuma regra de contagem, captura ou exportação vive na interface.
  É também o que torna AC-012.4 possível: o pipeline nunca dependeu da aba.
  Afeta AC-011.4 e AC-012.4.
- [x] SUP-039 — A trava de sessão única é um arquivo com o PID do processo no
  diretório de dados; se o PID não corresponder a um processo vivo, a trava é
  considerada órfã. Afeta AC-013.1 e AC-013.2.
- [x] SUP-041 — A interface roda apenas em localhost e sem autenticação, coerente
  com o uso monousuário em máquina local. Afeta AC-013.1.
- [x] SUP-043 — A duração é oferecida como valor inteiro em minutos, com padrão
  de 15. Afeta AC-011.2.
- [x] SUP-052 — A trava de sessão única vale para todo comando que baixa ou
  processa vídeo: `session run`, `session capture` e `session process`. Afeta
  AC-013.1 e AC-013.2.
- [x] SUP-108 — No processamento, o pedido de parada é consultado a cada frame
  amostrado, e não só antes de cada clipe, como já acontece no upload (D-12 do
  `_tasks.md` de `processamento-upload`). A consulta só entre clipes fazia o
  usuário esperar até o fim do clipe em análise e deixava passar o pedido feito
  durante o último clipe, que terminava como sessão concluída, com planilha.
  Confirmado pelo autor. Afeta AC-012.5.
  > **Corrigido em 2026-11-15:** a referência ao upload está errada. A D-12 do
  > `_tasks.md` de `processamento-upload` consulta a parada antes de cada vídeo
  > e no início de cada minuto dentro dele, e não a cada frame amostrado, e o
  > código segue a D-12. O upload tem, portanto, o mesmo defeito que esta SUP
  > corrigiu na sessão ao vivo: o usuário espera o fim do minuto em análise, e
  > o pedido feito durante o último minuto do último vídeo é ignorado, terminando
  > a sessão como concluída, com planilha. Isso contraria AC-029.1 de
  > `processamento-upload`, que remete a AC-012.5.
- [x] SUP-110 — `session process <id>` recusa a sessão marcada como cancelada
  na captura: sai com erro dizendo que a sessão foi cancelada pelo usuário e
  não tem vídeos para processar, e nada é processado nem gravado. Se a marca
  não chegou ao banco (SUP-111), o comando segue e a sessão termina sem
  planilha, porque os vídeos não existem; consequência aceita. Confirmado pelo
  autor. Afeta AC-012.7.
- [x] SUP-111 — No cancelamento da captura, se o banco falhar ao gravar a marca
  de cancelada, ou não tiver sido aberto durante a captura, o sistema só avisa
  no log e segue: apaga os clipes e termina como "Sessão cancelada pelo
  usuário". É a mesma regra da captura, em que falha de banco não derruba a
  sessão; o registro pode ficar sem a marca. Confirmado pelo autor. Afeta
  AC-012.7.

## Perguntas em aberto

Nenhuma pendente. Os IDs permanecem como histórico das decisões.

- [x] Q-006 — Fechar o navegador durante uma sessão a encerra? **Respondida:
  não.** A sessão segue até o fim e o progresso é reencontrado ao reabrir a
  interface, o que virou AC-012.4. Interromper passou a exigir ação explícita, e
  só então vale a regra de AC-003.6 de `captura-clipes`. A alternativa —
  encerrar ao fechar — deixaria um fechamento acidental custar minutos de captura
  que a URL não permite recuperar. Revista por Q-026: pela interface, a ação
  explícita na captura passou a cancelar a sessão (AC-012.7), e AC-003.6 ficou
  só para o terminal.
- [x] Q-009 — Uma sessão sem nenhum clipe processável tem planilha?
  **Respondida: não.** A D-6 de `exportacao-xlsx` continua valendo, e a interface
  exibe o status e informa que não há planilha, o que virou AC-012.6.
- [x] Q-010 — Encerrar explicitamente vale também no processamento?
  **Respondida: sim.** A contagem para, nada é gravado e os vídeos ficam para
  reprocessamento, o que virou AC-012.5. A alternativa de descartar os vídeos
  deixaria a sessão sem como ser refeita.
- [x] Q-011 — A trava de sessão única vale para quais comandos? **Respondida:
  todo comando que baixa ou processa vídeo**, o que virou SUP-052.
- [x] Q-026 — O que "Parar antecipadamente" faz na fase de captura?
  **Respondida: cancela a sessão inteira.** Até então valia AC-003.6: a captura
  parava e os minutos já capturados seguiam para a contagem. O autor decidiu que,
  pela interface, parar encerra tudo e não inicia a contagem. Decidido junto:
  - vale só para o botão da interface. O Ctrl+C no terminal continua com
    AC-003.6;
  - os clipes já capturados são apagados, seja qual for a opção de manter os
    vídeos, e a sessão não pode ser reprocessada;
  - o registro da sessão fica no banco, marcado como cancelado pelo usuário
    (AC-008.6 de `persistencia-resultados`);
  - o desfecho é próprio, "Sessão cancelada pelo usuário", distinto do
    processamento cancelado de AC-012.5, que continua mantendo os vídeos.

  Virou AC-012.7.

## Specs afetadas

Revisado história por história.

- `configuracao-camera` — AC-011.1 exibe exatamente as câmeras aceitas por
  AC-001.1, e AC-011.3 é a consequência visível da rejeição de câmera sem linha
  calibrada de AC-002.4. Os rótulos de sentido que o usuário lê vêm da
  calibração de US-002.
- `captura-clipes` — AC-011.2 impõe na interface o mesmo limite de 1 a 15 minutos
  já validado em AC-003.3; AC-012.1 exibe os minutos perdidos de AC-004.5 e
  AC-004.6. AC-012.4 e AC-003.6 passaram a se encaixar: fechar a aba não é
  interrupção, e só a ação explícita aciona a sessão de duração real. Com
  AC-012.7, AC-003.6 deixa de valer para a interface e fica só para o Ctrl+C no
  terminal.
- `contagem-veiculos` — AC-012.2 expõe a segunda fase, cujo tempo é limitado por
  AC-005.4; se o orçamento de performance for renegociado por SUP-017, a espera
  que a interface anuncia muda junto. AC-012.5 exige que o processamento possa
  ser interrompido no meio do clipe em análise, e não só entre dois minutos, sem
  gravar resultado (SUP-108).
- `persistencia-resultados` — AC-012.3 mostra o status gravado em AC-008.1, e
  AC-012.4 depende de esse registro existir desde o início da captura. AC-012.7
  mantém o registro da sessão cancelada na captura com a marca de AC-008.6, e o
  histórico de AC-009.2 passa a mostrar essa marca.
- `layout-interface` — AC-023.1 passa a encerrar a captura pela regra de
  AC-012.7, e não mais pela de AC-003.6. AC-023.4 ganha o desfecho da sessão
  cancelada na captura.
- `acompanhamento-ao-vivo` — AC-018.3 passa a valer também para a sessão
  cancelada na captura: só o tempo total, sem quantidades.
- `download-clipes` — AC-025.6 passa a valer também para a sessão cancelada na
  captura: sem lista de clipes, porque eles foram apagados mesmo com a opção
  ligada.
- `exportacao-xlsx` — AC-012.3 entrega o arquivo produzido por AC-010.1. Como
  Q-005 manteve a geração de planilha para sessão INVÁLIDA, aquele critério não
  precisa de caminho alternativo para sessão com clipes processados. A sessão
  sem nenhum clipe processável segue sem planilha pela D-6 daquela feature, e
  AC-012.6 define o que a interface mostra nesse caso.

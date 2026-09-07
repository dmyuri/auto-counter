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

  AC-011.2 — Dado a interface aberta, quando o usuário informa a duração, então
  apenas valores inteiros de 1 a 15 minutos são aceitos para iniciar a sessão.

  AC-011.3 — Dado um registro sem nenhuma câmera válida, quando a interface é
  aberta, então ela informa que não há câmera disponível e o comando de iniciar
  sessão fica indisponível.

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

  AC-012.3 — Dado uma sessão concluída, quando o usuário acessa o resultado,
  então a interface exibe o status da sessão e oferece o download do XLSX
  correspondente àquela sessão.

  AC-012.4 — Dado uma sessão em andamento, quando a interface é fechada e aberta
  de novo, então a sessão continua em andamento, o progresso dela é reencontrado
  e nenhum minuto foi perdido por causa do fechamento; o encerramento antecipado
  só acontece por ação explícita do usuário.

US-013 — Uma sessão por vez
Como integrante do projeto de extensão, quero que o sistema recuse iniciar uma
segunda sessão enquanto outra roda, para não disputar CPU e rede e acabar com as
duas sessões degradadas.

Critérios de aceite:
  AC-013.1 — Dado uma sessão em andamento, quando alguém tenta iniciar outra,
  então a segunda é recusada com mensagem que informa a câmera e o horário de
  início da sessão em curso, e a sessão em andamento não é afetada.

  AC-013.2 — Dado que o processo da sessão anterior terminou ou foi encerrado
  sem liberar a trava, quando uma nova sessão é iniciada, então a trava órfã é
  ignorada e a nova sessão começa normalmente.

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

## Perguntas em aberto

Nenhuma pendente. Os IDs permanecem como histórico das decisões.

- [x] Q-006 — Fechar o navegador durante uma sessão a encerra? **Respondida:
  não.** A sessão segue até o fim e o progresso é reencontrado ao reabrir a
  interface, o que virou AC-012.4. Interromper passou a exigir ação explícita, e
  só então vale a regra de AC-003.6 de `captura-clipes`. A alternativa —
  encerrar ao fechar — deixaria um fechamento acidental custar minutos de captura
  que a URL não permite recuperar.

## Specs afetadas

Revisado história por história.

- `configuracao-camera` — AC-011.1 exibe exatamente as câmeras aceitas por
  AC-001.1, e AC-011.3 é a consequência visível da rejeição de câmera sem linha
  calibrada de AC-002.4. Os rótulos de sentido que o usuário lê vêm da
  calibração de US-002.
- `captura-clipes` — AC-011.2 impõe na interface o mesmo limite de 1 a 15 minutos
  já validado em AC-003.3; AC-012.1 exibe os minutos perdidos de AC-004.5 e
  AC-004.6. AC-012.4 e AC-003.6 passaram a se encaixar: fechar a aba não é
  interrupção, e só a ação explícita aciona a sessão de duração real.
- `contagem-veiculos` — AC-012.2 expõe a segunda fase, cujo tempo é limitado por
  AC-005.4; se o orçamento de performance for renegociado por SUP-017, a espera
  que a interface anuncia muda junto.
- `persistencia-resultados` — AC-012.3 mostra o status gravado em AC-008.1, e
  AC-012.4 depende de esse registro existir desde o início da captura.
- `exportacao-xlsx` — AC-012.3 entrega o arquivo produzido por AC-010.1. Como
  Q-005 manteve a geração de planilha para sessão INVÁLIDA, aquele critério não
  precisa de caminho alternativo para sessão concluída sem planilha.

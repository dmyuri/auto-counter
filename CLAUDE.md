# Projeto
Este projeto usa a stack e os comandos documentados no README.md.

# Regras de trabalho
Antes de qualquer implementação, leia `.spec/constituicao.md` e a spec
da feature em que você vai implementar. Quando a tarefa envolver uma spec e o caminho
não estiver explícito no pedido, PARE e pergunte.

## Perguntas ao usuário

Sempre que precisar perguntar algo ao usuário:

- Use a interface interativa nativa do Claude Code.
- Uma pergunta de cada vez.
- Apresente as opções com uma breve explicação.
- Indique claramente a opção recomendada, preferencialmente como primeira opção.
- Não tome decisões que dependam do usuário sem perguntar.

## Proibições
- Não preencher lacuna de requisito com palpite silencioso. Se faltar informação, PARE e pergunte.
- Não escrever critério de aceite não observável.
  Nada de "detecta bem", "rápido o suficiente" ou "robusto" sem número,
  taxa de erro tolerada ou regra de decisão.
- Não alterar a especificação durante a implementação.
  Se encontrar contradição entre spec e código (ex.: spec diz uma coisa
  sobre a linha de contagem e o código faz outra), PARE e avise.
- Não declarar que a feature está pronta.
  Quem declara é o resultado do test runner e, quando o critério for de
  precisão de contagem, o resultado da validação contra o vídeo de
  referência (ground truth) — nunca uma afirmação sem esse número.
- Não assumir continuidade de estado (tracker, IDs, buffers) entre
  clipes sem que isso esteja explícito na spec da feature. Se a spec
  não disser o que fazer na virada de um clipe pro outro, PARE e
  pergunte — não decida sozinho.
- Não tratar falha de captura, OCR do timestamp ou clipe corrompido
  como exceção não tratada que derruba a execução. Se a spec não
  definir o comportamento de fallback para esse caso, PARE e pergunte.
- Nunca fazer commit ou push sem minha autorização.
- Nunca fazer commit colocando a <IA> como Co-author.
- Não toque em `.env` nem em qualquer arquivo de credencial de acesso
  às câmeras/URLs da NitTrans.
- Migrations e schemas de dados já commitados são imutáveis. Mudança
  de schema (ex.: nova categoria de veículo, novo campo na planilha) =
  migration/versão nova.

## Convenções
- Toda história recebe ID: US-001, US-002...
- Todo critério de aceite recebe ID: AC-001.1, AC-001.2...
- Toda tarefa recebe ID: T-01, e cita os IDs que atende.
- Todo teste tem o ID do critério no nome:
  test_AC_001_1_veiculo_na_borda_do_clipe_nao_conta_duas_vezes
- O identificador nunca muda depois de criado, mesmo que o texto
  do critério seja reescrito.
- Todo commit deve seguir o padrão: <tipo>(<escopo>): <descrição>
	Exemplo: "feat(tracking): adiciona deduplicação na borda do clipe"
- Toda câmera tem um ID estável e configuração própria (posição da
  linha de contagem). Nunca reaproveitar
  calibração de uma câmera em outra sem isso estar explícito na spec.
# Projeto
Este projeto usa a stack e os comandos documentados no README.md.

# Regras de trabalho
Antes de qualquer implementação, leia `.spec/constitution.md` e a spec
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
- Nunca fazer commit ou push sem minha autorização.
- Nunca fazer commit colocando a <IA> como Co-author.
- Não inclua o ID, número ou código da tarefa no commit (ex.: T-03, T02, etc). A descrição deve conter somente uma descrição objetiva da alteração realizada, sem referência à tarefa que a originou.

## Convenções
- Toda história recebe ID: US-001, US-002...
- Todo critério de aceite recebe ID: AC-001.1, AC-001.2...
- Toda tarefa recebe ID: T-01, e cita os IDs que atende.
- O identificador nunca muda depois de criado, mesmo que o texto
  do critério seja reescrito.
- Todo commit deve seguir o padrão: <tipo>(<escopo>): <descrição>
	Exemplo: "feat(tracking): adiciona deduplicação na borda do clipe" (sempre uma mensagem curta)
- Se alguma decisão durante a implementação contradiz a spec, pare e me avise.
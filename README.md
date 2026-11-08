# auto-counter

MVP local de contagem e classificação automática de veículos por visão computacional, processando as URLs públicas das câmeras de trânsito da NitTrans (Niterói).

## Como funciona

A câmera publica um único arquivo — `<base_url>/<id>/last_video.mp4` — com o último minuto de vídeo, substituído a cada minuto. Não há histórico: um clipe que não for baixado dentro da sua janela está perdido para sempre. Por isso a sessão tem duas fases separadas:

1. **Captura** — durante os N minutos escolhidos (1 a 15), o sistema só baixa. Clipe novo é identificado pelo `ETag` da resposta e datado pelo `Last-Modified`. É a operação barata, e nada compete com ela por CPU.
2. **Processamento** — os clipes já em disco são analisados sem pressão de tempo real: detecção, rastreamento dentro de cada clipe e registro de cada cruzamento da linha de contagem, com sentido.

O resultado é gravado no SQLite e exportado como XLSX de três abas (eventos, agregado por minuto, metadados da sessão). Os vídeos são apagados ao fim da sessão, salvo quando a flag de preservação (`--keep-clips`) é usada, ou quando a opção **Manter clipes de vídeo** é ligada na interface.

Câmera do MVP: **000013** — 1280×720 a 30 fps, H.264, clipes de 59,93 s e ~32 MB. Uma sessão de 15 min baixa ~480 MB.

## Stack
- Linguagem: Python 3.11+
- Framework: Typer (CLI) + Streamlit (interface local, sem servidor dedicado)
- Banco: SQLite 3 (módulo `sqlite3` da stdlib), arquivo único
- Export: XLSX via `openpyxl` (CSV, JSON e PDF estão fora do escopo desta versão)
- Testes: pytest (marcadores `accuracy` para a validação contra ground truth e `perf` para o orçamento de tempo por frame) + `audit.py` como relatório de rastreabilidade (informativo)
- Gerenciador de pacotes: uv (`pyproject.toml` + `uv.lock`)

Componentes de visão computacional:
- Detecção: Ultralytics YOLO11n — licença **AGPL-3.0**, portanto este repositório é AGPL-3.0
- Inferência: ONNX Runtime (CPU), com o modelo exportado para `.onnx`
- Rastreamento e contagem: `supervision` (ByteTrack), com cruzamento de linha com direção próprio, pela troca de lado do contato com o solo
- Captura: download HTTP do `.mp4` público, um arquivo por minuto; OpenCV lê o arquivo local. **FFmpeg não é usado** — a fonte já é um MP4 progressivo e o OpenCV embarca a decodificação H.264 necessária
- Configuração: um YAML por câmera em `config/cameras/<id>.yaml`, validado com Pydantic

## Como rodar

Pré-requisito: [uv](https://docs.astral.sh/uv/) disponível no PATH.

```powershell
uv --version
```

```powershell
# 1. Instalar dependências a partir do lockfile (cria .venv)
uv sync

# 2. Configurar o acesso às câmeras — nunca no código
copy .env.example .env
#    edite .env com os valores reais
```

O `.env` guarda a base URL do servidor de vídeo da NitTrans e o diretório onde ficam clipes e banco (`AUTO_COUNTER_DATA_DIR`). Nenhum endereço tem valor padrão embutido no código: sem a variável definida, o sistema falha com erro explícito em vez de tentar adivinhar.

> **Windows:** escreva o caminho **sem aspas** (`AUTO_COUNTER_DATA_DIR=C:\Repositories\auto-counter\data`) ou com barras normais (`"C:/Repositories/auto-counter/data"`). Entre aspas duplas, o `\a` de `\auto-counter` é lido como caractere de controle e o caminho fica inválido. Prefira caminho absoluto.

```powershell
# 3. Ver os comandos disponíveis nesta versão
uv run auto-counter --help

# 4. Abrir a interface local (câmera, duração e acompanhamento da sessão)
uv run auto-counter ui
```

### Interface

`uv run auto-counter ui` abre a interface em `http://127.0.0.1:8501` (use `--port` para mudar a porta e `--config-dir` para outro registro de câmeras). Nela você:

1. escolhe a câmera pelos cartões (id, nome do local e a imagem de prévia, quando a câmera indica uma) e a duração (1 a 15 minutos, padrão 15, com atalhos de 5, 10 e 15 min), decide na seção **Saída** se os vídeos ficam guardados (**Manter clipes de vídeo**, desligada por padrão, porque os clipes mostram placas e pessoas e uma sessão de 15 min ocupa ~480 MB) e clica em **Iniciar sessão**;
2. acompanha a sessão no painel **Contagem ao vivo**, atualizado sozinho a cada 2 s: a fase (captura ou processamento), os minutos capturados do total e os perdidos, o percentual concluído, o tempo decorrido e o **tempo estimado** (MM:SS, previsto pelo orçamento de processamento de 80 s por minuto de vídeo). Na captura não há quantidades, e a tela avisa que a contagem começa quando ela terminar. No processamento aparecem o total, a quantidade e a participação de cada categoria (carro, ônibus, caminhão e moto) e a taxa em veículos por minuto de vídeo;
3. pode **Parar antecipadamente** (com confirmação): na captura, os minutos já capturados são processados; no processamento, a contagem é cancelada, nada é gravado e os vídeos são mantidos para `session process`;
4. ao fim, o painel **Sessão finalizada** mostra se a sessão foi concluída ou interrompida pelo usuário, com o tempo total, o status e o cartão da planilha (nome do arquivo, número de registros e o botão **Baixar .xlsx**, que passa a **✓ Baixado**). Com a opção de manter clipes ligada, a sessão concluída lista também os clipes (nome `<id_camera>_<AAAAMMDD>_<HHMM>.mp4`, duração, tamanho e um botão **Baixar** por clipe, que passa a **✓**) e o botão **Baixar todos (.zip)**; clipes que já não estão em disco são omitidos e a tela avisa quantos. Sem a opção, a tela informa que os clipes não foram mantidos. Os valores finais ficam no painel ao vivo. Sessão cancelada, sem nenhum clipe processável ou que falhou mostra só a mensagem, sem quantidades nem lista de clipes. **Nova sessão** libera a configuração de volta, com a câmera e a duração anteriores; abrir a interface em outra aba mostra o último resultado de novo.

O cabeçalho mostra o estado do sistema (Aguardando, Capturando, Processando, Em andamento, para sessão iniciada pelo terminal, ou Finalizado) e alterna entre o tema escuro, que é o padrão, e o claro. A escolha de tema vale só para a aba aberta e não é gravada em disco. A interface usa as fontes IBM Plex Sans e JetBrains Mono quando instaladas na máquina; sem elas, usa a fonte do sistema, porque não carrega nada da internet.

A sessão roda em um processo separado, então fechar a aba ou parar o `ui` não a interrompe; ao reabrir a interface, ela reencontra a sessão em andamento. O estado fica em `AUTO_COUNTER_DATA_DIR` (`sessao.lock`, `sessao_atual.json`, `sessao.parar`) e o log de cada execução em `logs/run-<carimbo>.log`.

Só uma sessão roda por vez, seja disparada pela interface ou pelo terminal (`run`, `capture` ou `process`). Com outra em andamento, o botão fica indisponível e a mensagem diz qual câmera e desde quando.

### Gerar a planilha de uma sessão

Num único comando, da câmera ao XLSX (é o que a interface dispara):

```powershell
uv run auto-counter session run 000013 --minutes 3          # --keep-clips preserva os vídeos
```

Ctrl+C na captura encerra pela duração real e segue para o processamento; no processamento, cancela sem gravar nada.

Ou, passo a passo, pela linha de comando:

```powershell
# 1. Captura (1 a 15 minutos)
uv run auto-counter session capture 000013 --minutes 3

# 2. Processamento: conta os veículos e grava o resultado no banco
uv run auto-counter session process <ID_SESSAO>

# 3. Exportação para XLSX
uv run auto-counter session export <ID_SESSAO>
```

`uv run auto-counter session list` mostra as sessões gravadas e seus ids. O arquivo é gravado no diretório de dados (`AUTO_COUNTER_DATA_DIR`) com o nome `<id_camera>_<AAAAMMDD>_<HHMM>_<N>min.xlsx`, e recebe o sufixo do status quando a sessão não é COMPLETA (por exemplo, `_INVALIDA`). A exportação lê apenas do banco, então funciona depois que os vídeos foram apagados; sessão ainda em andamento ou não processada é recusada.

Os subcomandos concretos são definidos pelas specs de feature em `.spec/features/`; `--help` sempre lista o que existe na versão instalada.

A interface escuta apenas em 127.0.0.1, sem autenticação, e aceita uma sessão por vez — o sistema é monousuário por decisão de escopo. Não é feita para ser exposta em servidor.

Cada câmera tem ID estável e configuração própria (posição da linha de contagem e rótulos dos dois sentidos). Calibração de uma câmera nunca é reaproveitada em outra, e a lista é pré-definida: o usuário seleciona, não cadastra. O YAML pode ter o campo opcional `preview`, com o caminho de uma imagem fixa relativo a `config/cameras/`, mostrada no cartão da câmera; sem o campo, ou com um arquivo que não abre, o cartão mostra "sem prévia" e a câmera continua selecionável. A interface nunca acessa a câmera para obter a prévia. Escolha uma imagem sem placa nem pessoa identificável, porque o diretório de configuração é versionado.

## Especificação

O comportamento é definido em `.spec/`, e o código não pode divergir dela. Ordem de dependência:

| Spec | O que define |
|---|---|
| `configuracao-camera` | Registro versionado de câmeras e calibração da linha, com preview em PNG (a imagem de prévia do cartão é o campo opcional `preview`, outra imagem) |
| `captura-clipes` | Download dos clipes, tratamento de falha e status da sessão |
| `contagem-veiculos` | Detecção, rastreamento, cruzamento com sentido e deduplicação na emenda |
| `persistencia-resultados` | Schema do SQLite: sessões, eventos e agregados por minuto |
| `exportacao-xlsx` | Planilha de três abas gerada apenas a partir do banco |
| `interface-sessao` | Seleção de câmera e duração, progresso e trava de sessão única |
| `acompanhamento-ao-vivo` | Quantidades por categoria e tempo da sessão na interface |
| `layout-interface` | Layout em três painéis, cabeçalho com estado e tema, cartões de câmera, atalhos de duração, painel ao vivo e painel de resultados |
| `validacao-acuracia` | Gate de acurácia contra os clipes contados à mão |

`.spec/constitution.md` traz as regras que valem para o projeto inteiro.

## Como testar

Rodar da raiz do repositório — `audit.py` resolve `report.xml` e `.spec/features/**/spec.md` em caminhos relativos ao diretório atual.

```powershell
# Suíte rápida, sem validação de acurácia nem medição de performance
uv run pytest -m "not accuracy and not perf" --junitxml=report.xml

# Suíte completa, incluindo a validação contra os clipes de ground truth
uv run pytest --junitxml=report.xml
```

```powershell
python audit.py
```

O `audit.py` cruza os critérios de aceite ativos das specs com os testes que passaram no `report.xml` e aponta AC sem prova, teste órfão e pendência em aberto na spec. É um relatório de rastreabilidade: o resultado dele não define se uma feature está pronta. Usa apenas a stdlib — se não houver `python` no PATH, use `uv run python audit.py`.

### Ground truth

A validação de acurácia compara a contagem automática com 3 clipes de 1 minuto da câmera 000013 contados à mão — um em horário de pico, um fora de pico e um noturno. Para cada clipe há um CSV com uma linha por veículo (instante do cruzamento, categoria, sentido).

```
tests/ground_truth/
├── manifest.yaml      # condição, câmera, ETag e Last-Modified de cada clipe
├── pico.csv           # uma linha por veículo: instante, categoria, sentido
├── fora_pico.csv
├── noturno.csv
└── clipes/            # ignorado pelo git — só aqui moram os vídeos
    ├── pico.mp4
    ├── fora_pico.mp4
    └── noturno.mp4
```

Os **CSVs e o manifest são versionados**: são poucos KB e representam horas de trabalho que não dá para refazer, já que a URL não guarda histórico para recontar. Os **vídeos ficam fora do git** (~32 MB cada), isolados em `clipes/` — a separação é por diretório e não por extensão, para que nenhuma regra de vídeo varra junto as fixtures. Sem os vídeos, os testes marcados com `accuracy` são pulados com aviso que nomeia o clipe ausente — e o `audit.py` trata teste pulado como teste sem prova, então o relatório acusa a falta em vez de passar em silêncio.

Um clipe extra de chuva, se houver oportunidade de coletá-lo, entra como mais um par `chuva.csv` + `clipes/chuva.mp4`: ele é medido e reportado, mas não pode reprovar a validação.

O teste marcado com `perf` mede o tempo médio por frame analisado e só é significativo na máquina de referência declarada na spec `contagem-veiculos` (notebook de 4 núcleos, 8 GB, sem GPU).

Uma feature só está pronta quando o pytest passa e, no caso de critério de precisão de contagem, quando a validação contra o vídeo de referência bate o número declarado na spec.

# auto-counter

MVP local de contagem e classificação automática de veículos por visão computacional, processando as URLs públicas das câmeras de trânsito da NitTrans (Niterói).

## Como funciona

A câmera publica um único arquivo — `<base_url>/<id>/last_video.mp4` — com o último minuto de vídeo, substituído a cada minuto. Não há histórico: um clipe que não for baixado dentro da sua janela está perdido para sempre. Por isso a sessão tem duas fases separadas:

1. **Captura** — durante os N minutos escolhidos (1 a 15), o sistema só baixa. Clipe novo é identificado pelo `ETag` da resposta e datado pelo `Last-Modified`. É a operação barata, e nada compete com ela por CPU.
2. **Processamento** — os clipes já em disco são analisados sem pressão de tempo real: detecção, rastreamento dentro de cada clipe e registro de cada cruzamento da linha de contagem, com sentido.

O resultado é gravado no SQLite e exportado como XLSX de três abas (eventos, agregado por minuto, metadados da sessão). Os vídeos são apagados ao fim da sessão, salvo quando a flag de preservação é usada.

Câmera do MVP: **000013** — 1280×720 a 30 fps, H.264, clipes de 59,93 s e ~32 MB. Uma sessão de 15 min baixa ~480 MB.

## Stack
- Linguagem: Python 3.11+
- Framework: Typer (CLI) + Streamlit (interface local, sem servidor dedicado)
- Banco: SQLite 3 (módulo `sqlite3` da stdlib), arquivo único
- Export: XLSX via `openpyxl` (CSV, JSON e PDF estão fora do escopo desta versão)
- Testes: pytest (marcadores `accuracy` para a validação contra ground truth e `perf` para o orçamento de tempo por frame) + `audit.py` como gate de rastreabilidade
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

O `.env` guarda a base URL do servidor de vídeo da NitTrans e o diretório onde ficam clipes e banco. Nenhum endereço tem valor padrão embutido no código: sem a variável definida, o sistema falha com erro explícito em vez de tentar adivinhar.

```powershell
# 3. Ver os comandos disponíveis nesta versão
uv run auto-counter --help

# 4. Abrir a interface local (seleção de câmera e duração)
uv run auto-counter ui
```

### Gerar a planilha de uma sessão

O fluxo completo, pela linha de comando, tem três passos:

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

A interface roda em localhost, sem autenticação, e aceita uma sessão por vez — o sistema é monousuário por decisão de escopo. Fechar o navegador não encerra uma sessão em andamento.

Cada câmera tem ID estável e configuração própria (posição da linha de contagem e rótulos dos dois sentidos). Calibração de uma câmera nunca é reaproveitada em outra, e a lista é pré-definida: o usuário seleciona, não cadastra.

## Especificação

O comportamento é definido em `.spec/`, e o código não pode divergir dela. Ordem de dependência:

| Spec | O que define |
|---|---|
| `configuracao-camera` | Registro versionado de câmeras e calibração da linha, com preview em PNG |
| `captura-clipes` | Download dos clipes, tratamento de falha e status da sessão |
| `contagem-veiculos` | Detecção, rastreamento, cruzamento com sentido e deduplicação na emenda |
| `persistencia-resultados` | Schema do SQLite: sessões, eventos e agregados por minuto |
| `exportacao-xlsx` | Planilha de três abas gerada apenas a partir do banco |
| `interface-sessao` | Seleção de câmera e duração, progresso e trava de sessão única |
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

O gate cruza os critérios de aceite ativos das specs com os testes que passaram no `report.xml` e sai com código diferente de zero se algum AC estiver sem prova, se houver teste órfão ou se restar pendência em aberto na spec. Usa apenas a stdlib — se não houver `python` no PATH, use `uv run python audit.py`.

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

Os **CSVs e o manifest são versionados**: são poucos KB e representam horas de trabalho que não dá para refazer, já que a URL não guarda histórico para recontar. Os **vídeos ficam fora do git** (~32 MB cada), isolados em `clipes/` — a separação é por diretório e não por extensão, para que nenhuma regra de vídeo varra junto as fixtures. Sem os vídeos, os testes marcados com `accuracy` são pulados com aviso que nomeia o clipe ausente — e como o `audit.py` trata teste pulado igual a teste que falhou, o gate reprova em vez de passar em silêncio.

Um clipe extra de chuva, se houver oportunidade de coletá-lo, entra como mais um par `chuva.csv` + `clipes/chuva.mp4`: ele é medido e reportado, mas não pode reprovar a validação.

O teste marcado com `perf` mede o tempo médio por frame analisado e só é significativo na máquina de referência declarada na spec `contagem-veiculos` (notebook de 4 núcleos, 8 GB, sem GPU).

Uma feature só está pronta quando o pytest passa e, no caso de critério de precisão de contagem, quando a validação contra o vídeo de referência bate o número declarado na spec.

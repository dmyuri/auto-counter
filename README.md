# auto-counter

MVP local de contagem e classificação automática de veículos por visão computacional, processando as URLs públicas das câmeras de trânsito da NitTrans (Niterói).

## Stack
- Linguagem: Python 3.11+
- Framework: Typer (CLI) + Streamlit (interface local, sem servidor dedicado)
- Banco: SQLite 3 (módulo `sqlite3` da stdlib), arquivo único, com export CSV/XLSX sob demanda
- Testes: pytest (marcador `accuracy` para a validação contra ground truth) + `audit.py` como gate de rastreabilidade
- Gerenciador de pacotes: uv (`pyproject.toml` + `uv.lock`)

Componentes de visão computacional:
- Detecção: Ultralytics YOLO11n — licença **AGPL-3.0**, portanto este repositório é AGPL-3.0
- Inferência: ONNX Runtime (CPU), com o modelo exportado para `.onnx`
- Rastreamento e contagem: `supervision` (ByteTrack + LineZone, cruzamento de linha com direção)
- Captura: FFmpeg grava clipes de duração fixa em disco; OpenCV lê o arquivo local
- Configuração: um YAML por câmera em `config/cameras/<id>.yaml`, validado com Pydantic

## Como rodar

Pré-requisitos: [uv](https://docs.astral.sh/uv/) e FFmpeg disponíveis no PATH.

```powershell
uv --version
ffmpeg -version
```

```powershell
# 1. Instalar dependências a partir do lockfile (cria .venv)
uv sync

# 2. Configurar as URLs/credenciais das câmeras — nunca no código
copy .env.example .env
#    edite .env com os valores reais

# 3. Ver os comandos disponíveis nesta versão
uv run auto-counter --help

# 4. Abrir a interface local (seleção de câmera e período)
uv run auto-counter ui
```

Os subcomandos concretos são definidos pelas specs de feature em `.spec/features/`; `--help` sempre lista o que existe na versão instalada.

Cada câmera tem ID estável e configuração própria (posição da linha de contagem). Calibração de uma câmera nunca é reaproveitada em outra.

## Como testar

Rodar da raiz do repositório — `audit.py` resolve `report.xml` e `.spec/features/**/spec.md` em caminhos relativos ao diretório atual.

```powershell
# Suíte rápida, sem a validação de acurácia
uv run pytest -m "not accuracy" --junitxml=report.xml

# Suíte completa, incluindo a validação contra os clipes de ground truth
uv run pytest --junitxml=report.xml
```

```powershell
python audit.py
```

O gate cruza os critérios de aceite ativos das specs com os testes que passaram no `report.xml` e sai com código diferente de zero se algum AC estiver sem prova, se houver teste órfão ou se restar pendência em aberto na spec. Usa apenas a stdlib — se não houver `python` no PATH, use `uv run python audit.py`.

Uma feature só está pronta quando o pytest passa e, no caso de critério de precisão de contagem, quando a validação contra o vídeo de referência bate o número declarado na spec.

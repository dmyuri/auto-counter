# Contagem e Classificação de Veículos — Câmeras NitTrans

Ferramenta que baixa clipes das câmeras públicas da NitTrans, detecta e classifica
os veículos que cruzam uma linha de contagem, e exporta a contagem por minuto e
por categoria em planilha.

## Stack
- Linguagem: Python 3.11
- Framework: FastAPI + Uvicorn, com Jinja2 e HTMX servindo a interface web
- Banco: SQLite 3, acessado pelo módulo `sqlite3` da stdlib; migrations em
  arquivos `.sql` numerados em `migrations/`
- Visão computacional: OpenCV (`opencv-python-headless`) + Ultralytics YOLO11n
  (AGPL-3.0), rastreamento com ByteTrack
- Leitura do timestamp: template matching com OpenCV (templates em `templates/digits/`)
- HTTP: httpx (download dos clipes, com timeout explícito)
- Exportação: openpyxl (escrita incremental em `.xlsx`)
- Testes: pytest
- Gerenciador de pacotes: pip + venv + requirements.txt

Todas as dependências em `requirements.txt` são fixadas com `==`. Sem lockfile,
essa é a única garantia de que duas máquinas produzam o mesmo número.

Não há build de frontend. O HTML é renderizado pelo Jinja2 e o HTMX entra por
CDN ou arquivo estático em `static/`. O projeto sobe com um único processo.

## Como rodar

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m app.migrate            # aplica as migrations pendentes
uvicorn app.main:app --reload --port 8000
```

Interface em `http://localhost:8000`.

As análises rodam numa fila: um worker consome um job por vez, então duas
execuções simultâneas não competem pela CPU. O estado de cada job fica na
tabela `jobs`.

Variáveis de ambiente em `.env` (veja `.env.example`): URLs base das câmeras,
timeout de download, caminho do banco e diretório de saída das planilhas.

## Como testar

```bash
pytest --junitxml=reports/junit.xml
python audit.py
```
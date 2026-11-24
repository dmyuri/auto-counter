# auto-counter

Contagem e classificação automática de veículos por visão computacional nas câmeras de trânsito públicas da NitTrans (Niterói). É um MVP local e monousuário, feito para os integrantes do projeto de extensão: escolhe-se a câmera e a duração, e o sistema entrega uma planilha com cada veículo que cruzou a linha de contagem, com categoria e sentido.

## Funcionalidades

- Captura de 1 a 15 minutos de uma câmera ao vivo, seguida da contagem automática.
- Detecção e classificação em carro, ônibus, caminhão e moto, com o sentido de cada cruzamento da linha.
- Contagem de vídeos que você já tem em arquivo (`.mp4`, `.mov`, `.avi`, `.mkv`), sem passar pela câmera.
- Interface local no navegador, com acompanhamento ao vivo da sessão e parada antecipada.
- Linha de comando com os mesmos fluxos, inteiros ou passo a passo.
- Resultado gravado em SQLite e exportado em XLSX de três abas (eventos, agregado por minuto e metadados da sessão).
- Opção de manter os clipes de vídeo da sessão para download.
- Encerramento da captura quando o servidor de vídeo fica fora do ar por 2 minutos seguidos, com contagem dos minutos já capturados.
- Duas câmeras calibradas: **000013** (Praça Getúlio Vargas) e **000012** (Praia x Mariz Barros).

## Como funciona

A câmera publica um único arquivo, `<base_url>/<id>/last_video.mp4`, com o último minuto de vídeo, substituído a cada minuto. Não há histórico: um clipe que não for baixado dentro da sua janela está perdido. Por isso a sessão tem duas fases separadas:

1. **Captura**: durante os N minutos escolhidos, o sistema só baixa. O clipe novo é identificado pelo `ETag` da resposta e datado pelo `Last-Modified`.
2. **Processamento**: os clipes já em disco são analisados sem pressão de tempo real, com detecção (YOLO11n em ONNX Runtime, CPU), rastreamento (ByteTrack) e registro de cada cruzamento da linha, com sentido.

Ao fim da sessão os vídeos são apagados, a menos que você peça para mantê-los.

## Pré-requisitos

- [uv](https://docs.astral.sh/uv/) no PATH. Ele gerencia o ambiente e as dependências (`pyproject.toml` + `uv.lock`).
- Python 3.11 ou superior. O uv baixa um Python compatível se não houver um na máquina.
- A base URL do servidor de vídeo da NitTrans. Ela não está no repositório e precisa ser informada no `.env`.
- Internet na preparação, para baixar o modelo YOLO11n, e durante a captura.
- Espaço em disco: uma sessão de 15 min baixa cerca de 480 MB, apagados ao fim, salvo se você mantiver os clipes.

FFmpeg não é necessário: o OpenCV já embarca a decodificação H.264.

## Instalação

PowerShell:

```powershell
uv sync
copy .env.example .env
uv run auto-counter model export
```

Bash:

```bash
uv sync
cp .env.example .env
uv run auto-counter model export
```

1. `uv sync` cria o `.venv` a partir do lockfile.
2. Edite o `.env` com os valores reais (veja [Configuração](#configuração)) antes do passo seguinte.
3. `model export` baixa o YOLO11n e grava `yolo11n.onnx` em `<AUTO_COUNTER_DATA_DIR>/models/`. É feito uma vez por máquina. Sem esse arquivo, o processamento é recusado. Use `--force` para reexportar.

Confira a instalação com:

```bash
uv run auto-counter --help
```

## Uso

### Interface

```bash
uv run auto-counter ui
```

Abre a interface em `http://127.0.0.1:8501`. Escolha a câmera, a duração e a fonte (câmera ao vivo ou upload de vídeos), clique em **Iniciar sessão** e baixe a planilha ao fim. A sessão roda em um processo separado: fechar a aba não a interrompe, e reabrir a interface reencontra a sessão em andamento.

### Sessão completa pelo terminal

Da câmera ao XLSX em um comando:

```bash
uv run auto-counter session run 000013 --minutes 3
```

Ctrl+C na captura encerra pela duração real e segue para o processamento. No processamento, cancela sem gravar nada.

### Contar vídeos que você já tem

```bash
uv run auto-counter session upload 000013 trecho1.mp4 trecho2.mov
```

Os vídeos precisam ter a resolução de calibração da câmera e somar até 15 min. Os originais não são alterados. A sessão de upload é datada pelo horário do processamento, não pelo da gravação.

### Passo a passo

```bash
uv run auto-counter session capture 000013 --minutes 3
uv run auto-counter session process <ID_SESSAO>
uv run auto-counter session export <ID_SESSAO>
```

`uv run auto-counter session list` mostra as sessões gravadas e seus ids. A planilha é gravada em `AUTO_COUNTER_DATA_DIR` com o nome `<id_camera>_<AAAAMMDD>_<HHMM>_<N>min.xlsx`, mais o sufixo do status quando a sessão não é COMPLETA (por exemplo, `_DEGRADADA`) e `_upload` na sessão de upload. A exportação lê só do banco, então funciona depois que os vídeos foram apagados.

## Configuração

### Variáveis de ambiente (`.env`)

| Variável | Obrigatória | O que é |
|---|---|---|
| `AUTO_COUNTER_BASE_URL` | Sim | Base URL do servidor de vídeo. A URL do clipe é `<base_url>/<id>/last_video.mp4`. Não tem valor padrão: sem ela, a captura falha com erro explícito. |
| `AUTO_COUNTER_DATA_DIR` | Não | Diretório de clipes, banco, planilhas, modelo e logs. Padrão: `data/`, na raiz do repositório e ignorado pelo git. |

> **Windows:** escreva o caminho **sem aspas** (`AUTO_COUNTER_DATA_DIR=C:\Repositories\auto-counter\data`) ou com barras normais (`"C:/Repositories/auto-counter/data"`). Entre aspas duplas, o `\a` de `\auto-counter` é lido como caractere de controle e o caminho fica inválido. Prefira caminho absoluto.

### Câmeras (`config/cameras/<id>.yaml`)

Cada câmera tem um YAML próprio, validado com Pydantic, com a linha de contagem, os rótulos dos dois sentidos e a resolução de calibração (`resolucao: {largura, altura}`, obrigatória). O campo opcional `preview` aponta para uma imagem fixa mostrada no cartão da interface. A lista é pré-definida: na interface você seleciona a câmera, não a cadastra. Escolha uma imagem de prévia sem placa nem pessoa identificável, porque o diretório é versionado.

```bash
uv run auto-counter camera list              # câmeras cadastradas e arquivos recusados
uv run auto-counter camera preview 000013    # PNG de conferência da linha de contagem
```

### Opções principais

| Opção | Comandos | Efeito |
|---|---|---|
| `--minutes N` | `session run`, `session capture` | Duração da captura, de 1 a 15 minutos. |
| `--keep-clips` | `session run`, `session capture` | Mantém os vídeos em disco ao fim da sessão. |
| `--threshold X` | `session run`, `session process` | Limiar de confiança das detecções. |
| `--sample-rate N` | `session run`, `session process` | Analisa 1 frame a cada N. |
| `--port N` | `ui` | Porta local da interface (padrão 8501). |
| `--config-dir DIR` | `ui`, `camera list`, `camera preview`, `session capture`, `run`, `upload`, `process` | Outro diretório de registro de câmeras. |

A interface escuta só em `127.0.0.1`, sem autenticação, e roda uma sessão por vez, iniciada pela interface ou pelo terminal. Não é feita para ser exposta em servidor.

## Testes

```bash
# Suíte rápida, sem validação de acurácia nem medição de performance
uv run pytest -m "not accuracy and not perf"

# Suíte completa
uv run pytest
```

- `accuracy`: compara a contagem com clipes da câmera 000013 contados à mão. Os vídeos de referência ficam fora do git, em `tests/ground_truth/clipes/`. Sem eles, esses testes são pulados com aviso.
- `perf`: mede o tempo médio por frame. Só é significativo na máquina de referência da spec `contagem-veiculos` (4 núcleos, 8 GB, sem GPU).

O `audit.py` gera um relatório de rastreabilidade entre os critérios de aceite das specs e os testes que passaram. É informativo. Rode-o da raiz do repositório, depois do pytest com `--junitxml=report.xml`:

```bash
uv run pytest --junitxml=report.xml
uv run python audit.py
```

## Especificação

O comportamento é definido em `.spec/`, e o código não pode divergir dela. `.spec/constitution.md` traz as regras que valem para o projeto inteiro.

| Spec | O que define |
|---|---|
| `configuracao-camera` | Registro versionado de câmeras e calibração da linha |
| `nova-camera` | Inclusão da câmera 000012 no registro |
| `captura-clipes` | Download dos clipes, tratamento de falha e status da sessão |
| `servidor-indisponivel` | Encerramento da captura quando o servidor fica fora do ar |
| `contagem-veiculos` | Detecção, rastreamento, cruzamento com sentido e deduplicação na emenda |
| `persistencia-resultados` | Schema do SQLite: sessões, eventos e agregados por minuto |
| `exportacao-xlsx` | Planilha de três abas gerada apenas a partir do banco |
| `interface-sessao` | Seleção de câmera e duração, progresso e trava de sessão única |
| `acompanhamento-ao-vivo` | Quantidades por categoria e tempo da sessão na interface |
| `layout-interface` | Layout em três painéis, cabeçalho, cartões de câmera, painel ao vivo e de resultados |
| `download-clipes` | Opção de manter os clipes e download deles ao fim da sessão |
| `upload-videos` | Escolha da fonte, envio de vídeos e conferência de duração, tamanho e resolução |
| `processamento-upload` | Sessão a partir dos vídeos enviados e o comando `session upload` |
| `validacao-acuracia` | Gate de acurácia contra os clipes contados à mão |

`uv run auto-counter --help` sempre lista os comandos da versão instalada.

## Licença

[AGPL-3.0](LICENSE). O detector usa o Ultralytics YOLO11n, distribuído sob AGPL-3.0, e por isso o repositório inteiro segue a mesma licença.

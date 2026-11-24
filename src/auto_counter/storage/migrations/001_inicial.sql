-- Migration 001: esqueleto inicial do schema de persistência de resultados.
--
-- Comportamento em .spec/features/persistencia-resultados/spec.md: estrutura
-- exigida por AC-008.1, AC-008.2, AC-008.3 e AC-008.4, implementando
-- SUP-024 (arquivo único), SUP-028 (minuto sem dado é coluna de estado) e
-- SUP-030 (timestamps em UTC, texto ISO 8601).
--
-- Esta migration é imutável depois de commitada (CLAUDE.md): campo novo é a
-- migration 002, nunca uma edição deste arquivo.

CREATE TABLE schema_version (
    versao INTEGER NOT NULL,
    aplicada_em TEXT NOT NULL
);

-- Uma linha por sessão. O ciclo de vida tem três momentos: aberta no início
-- da captura (id, câmera, duração pedida; o resto nulo), fechada no fim da
-- captura (período real, duração real, encerramento, status, minutos
-- perdidos) e completada no processamento (versão do modelo, amostragem,
-- limiar). `status` nulo significa sessão ainda em captura — não é um quarto
-- status (o vocabulário de três de capture/status.py é fechado).
CREATE TABLE sessao (
    id_sessao TEXT PRIMARY KEY,
    id_camera TEXT NOT NULL,
    criada_em TEXT NOT NULL,
    inicio TEXT,
    fim TEXT,
    duracao_pedida INTEGER NOT NULL,
    duracao_real INTEGER,
    encerrada_pelo_usuario INTEGER NOT NULL DEFAULT 0
        CHECK (encerrada_pelo_usuario IN (0, 1)),
    status TEXT
        CHECK (status IN ('COMPLETA', 'DEGRADADA', 'INVALIDA')),
    minutos_perdidos_quantidade INTEGER NOT NULL DEFAULT 0,
    minutos_perdidos TEXT NOT NULL DEFAULT '[]',
    versao_do_modelo TEXT,
    amostragem INTEGER,
    limiar_de_confianca REAL,
    -- Rótulos vigentes na câmera no momento desta sessão (D-6): a contagem
    -- por sentido da tabela `minuto` é por papel (sentido_a/sentido_b), nunca
    -- pelo rótulo, porque recalibrar uma câmera pode trocar os dois rótulos.
    sentido_a TEXT,
    sentido_b TEXT
);

-- Um cruzamento de linha por linha. A chave primária é a mesma regra de
-- deduplicação de AC-006.6 de contagem-veiculos (no máximo um evento por par
-- rastreio+sentido), o que torna a idempotência de AC-008.5 uma propriedade
-- do schema, e não só do código que insere.
CREATE TABLE evento (
    id_sessao TEXT NOT NULL REFERENCES sessao (id_sessao) ON DELETE CASCADE,
    id_de_rastreio TEXT NOT NULL,
    sentido TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    categoria TEXT NOT NULL
        CHECK (categoria IN ('CARRO', 'MOTO', 'ONIBUS', 'CAMINHAO')),
    confianca REAL NOT NULL,
    minuto INTEGER NOT NULL,
    PRIMARY KEY (id_sessao, id_de_rastreio, sentido)
);

-- Uma linha por minuto ordinal da sessão (1..duração real). `estado`
-- distingue minuto sem veículo (CAPTURADO, contagem zero) de minuto sem
-- vídeo (SEM_DADO, contagem nula) — é a distinção de SUP-028 e AC-008.4,
-- imposta aqui pelo CHECK, não deixada para o código que grava lembrar.
CREATE TABLE minuto (
    id_sessao TEXT NOT NULL REFERENCES sessao (id_sessao) ON DELETE CASCADE,
    minuto INTEGER NOT NULL,
    estado TEXT NOT NULL
        CHECK (estado IN ('CAPTURADO', 'SEM_DADO')),
    motivo TEXT,
    sentido_a_carro INTEGER,
    sentido_a_moto INTEGER,
    sentido_a_onibus INTEGER,
    sentido_a_caminhao INTEGER,
    sentido_b_carro INTEGER,
    sentido_b_moto INTEGER,
    sentido_b_onibus INTEGER,
    sentido_b_caminhao INTEGER,
    PRIMARY KEY (id_sessao, minuto),
    CHECK (
        (
            estado = 'SEM_DADO'
            AND sentido_a_carro IS NULL AND sentido_a_moto IS NULL
            AND sentido_a_onibus IS NULL AND sentido_a_caminhao IS NULL
            AND sentido_b_carro IS NULL AND sentido_b_moto IS NULL
            AND sentido_b_onibus IS NULL AND sentido_b_caminhao IS NULL
        )
        OR
        (
            estado = 'CAPTURADO'
            AND sentido_a_carro IS NOT NULL AND sentido_a_moto IS NOT NULL
            AND sentido_a_onibus IS NOT NULL AND sentido_a_caminhao IS NOT NULL
            AND sentido_b_carro IS NOT NULL AND sentido_b_moto IS NOT NULL
            AND sentido_b_onibus IS NOT NULL AND sentido_b_caminhao IS NOT NULL
        )
    )
);

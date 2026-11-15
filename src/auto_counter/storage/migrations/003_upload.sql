-- Migration 003: origem da sessão, vídeos enviados e evento de upload.
--
-- Comportamento em .spec/features/processamento-upload/spec.md: AC-030.1 (a
-- origem CAMERA ou UPLOAD e os dados de cada vídeo enviado), SUP-096 (coluna e
-- tabela novas; as sessões que já existem recebem CAMERA) e SUP-100 (o evento de
-- upload guarda o vídeo de origem e o deslocamento em segundos desde o início
-- dele, e não uma hora do dia).
--
-- Esta migration é imutável depois de commitada (CLAUDE.md): campo novo é a
-- migration 004, nunca uma edição deste arquivo.

ALTER TABLE sessao ADD COLUMN origem TEXT NOT NULL DEFAULT 'CAMERA'
    CHECK (origem IN ('CAMERA', 'UPLOAD'));

ALTER TABLE evento ADD COLUMN video INTEGER;

ALTER TABLE evento ADD COLUMN deslocamento INTEGER;

CREATE TABLE video_da_sessao (
    id_sessao TEXT NOT NULL REFERENCES sessao (id_sessao) ON DELETE CASCADE,
    posicao INTEGER NOT NULL,
    nome_original TEXT NOT NULL,
    duracao_segundos INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    minuto_inicial INTEGER NOT NULL,
    minuto_final INTEGER NOT NULL,
    PRIMARY KEY (id_sessao, posicao)
);

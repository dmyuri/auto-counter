-- Migration 004: marca de sessão cancelada pelo usuário.
--
-- Comportamento em .spec/features/persistencia-resultados/spec.md: AC-008.6 (a
-- sessão cancelada na captura pela interface continua no banco com a marca,
-- sem evento nem agregado) e SUP-109 (a marca é campo próprio, e não um quarto
-- status). As sessões que já existem recebem 0.
--
-- Esta migration é imutável depois de commitada (CLAUDE.md): campo novo é a
-- migration 005, nunca uma edição deste arquivo.

ALTER TABLE sessao ADD COLUMN cancelada_pelo_usuario INTEGER NOT NULL DEFAULT 0
    CHECK (cancelada_pelo_usuario IN (0, 1));

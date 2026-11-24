-- Migration 002: nome da câmera na linha de sessão.
--
-- Comportamento em .spec/features/exportacao-xlsx/spec.md: AC-010.4 imprime o
-- nome da câmera na aba Sessao, e a exportação lê apenas do banco (D-2 de
-- exportacao-xlsx/_tasks.md). Vale o nome vigente na sessão, gravado como os
-- rótulos de sentido (D-6 de persistencia-resultados). Nulo em sessão gravada
-- antes desta migration.
--
-- Esta migration é imutável depois de commitada (CLAUDE.md): campo novo é a
-- migration 003, nunca uma edição deste arquivo.

ALTER TABLE sessao ADD COLUMN nome_camera TEXT;

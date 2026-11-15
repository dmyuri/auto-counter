-- Migration 005: marca de sessão encerrada por servidor indisponível.
--
-- Comportamento em .spec/features/servidor-indisponivel/spec.md: AC-036.1 (o
-- registro da sessão traz a indicação de encerramento por servidor
-- indisponível, "sim" para a sessão marcada e "não" para as outras; as sessões
-- gravadas antes desta feature são lidas como "não"). As sessões que já
-- existem recebem 0.
--
-- Esta migration é imutável depois de commitada (CLAUDE.md): campo novo é a
-- migration 006, nunca uma edição deste arquivo.

ALTER TABLE sessao ADD COLUMN encerrada_por_servidor_indisponivel INTEGER NOT NULL
    DEFAULT 0 CHECK (encerrada_por_servidor_indisponivel IN (0, 1));

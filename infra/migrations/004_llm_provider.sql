-- Migration 004: Add llm_provider to analysis_jobs
-- Stores which LLM backend was used (or requested) for a given analysis.
-- TEXT (not enum) for forward compatibility — new providers can be added without a schema change.

ALTER TABLE analysis_jobs
  ADD COLUMN IF NOT EXISTS llm_provider TEXT NOT NULL DEFAULT 'anthropic';

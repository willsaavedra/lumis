-- ─────────────────────────────────────────────────────────────────────────────
-- Migration 005: TS Agent Compatibility
-- Adds support for multi-agent architecture, new pillars, and extended findings.
-- ─────────────────────────────────────────────────────────────────────────────

-- 1. Dimension: enum → TEXT (allows domain agents to use custom dimensions)
ALTER TABLE findings ALTER COLUMN dimension TYPE TEXT;
DROP TYPE IF EXISTS dimension_enum;

-- 2. New pillars for domain agents
DO $$
BEGIN
  ALTER TYPE pillar_enum ADD VALUE IF NOT EXISTS 'security';
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
  ALTER TYPE pillar_enum ADD VALUE IF NOT EXISTS 'efficiency';
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
  ALTER TYPE pillar_enum ADD VALUE IF NOT EXISTS 'compliance';
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- 3. New analysis type: context
DO $$
BEGIN
  ALTER TYPE analysis_type_enum ADD VALUE IF NOT EXISTS 'context';
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- 4. analysis_results: new columns for agent breakdown and crossrun
ALTER TABLE analysis_results
  ADD COLUMN IF NOT EXISTS agent_breakdown JSONB;

-- previous_job_id and crossrun_summary may already exist
DO $$
BEGIN
  ALTER TABLE analysis_results
    ADD COLUMN IF NOT EXISTS crossrun_summary JSONB;
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;

DO $$
BEGIN
  ALTER TABLE analysis_results
    ADD COLUMN IF NOT EXISTS previous_job_id UUID REFERENCES analysis_jobs(id) ON DELETE SET NULL;
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;

-- 5. findings: new columns from TS agent multi-agent architecture
ALTER TABLE findings
  ADD COLUMN IF NOT EXISTS source_agent TEXT,
  ADD COLUMN IF NOT EXISTS prompt_mode TEXT,
  ADD COLUMN IF NOT EXISTS verified BOOLEAN DEFAULT false,
  ADD COLUMN IF NOT EXISTS confidence REAL,
  ADD COLUMN IF NOT EXISTS reasoning_excerpt TEXT;

-- 6. pillar: enum → TEXT (allows domain agents to use custom pillars beyond enum)
ALTER TABLE findings ALTER COLUMN pillar TYPE TEXT;
ALTER TABLE findings ALTER COLUMN severity TYPE TEXT;
DROP TYPE IF EXISTS pillar_enum;
DROP TYPE IF EXISTS severity_enum;

-- 7. Indexes for new columns
CREATE INDEX IF NOT EXISTS idx_findings_source_agent ON findings(source_agent);
CREATE INDEX IF NOT EXISTS idx_findings_confidence ON findings(confidence);
CREATE INDEX IF NOT EXISTS idx_findings_verified ON findings(verified);

-- ─────────────────────────────────────────────────────────────────────────────
-- Lumis — PostgreSQL 16 Schema
-- Run automatically on first postgres container startup via docker-entrypoint-initdb.d
-- ─────────────────────────────────────────────────────────────────────────────

-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ─────────────────────────────────────────────────────────────────────────────
-- ENUMS
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TYPE plan_enum AS ENUM ('free', 'starter', 'growth', 'scale', 'enterprise');
CREATE TYPE scm_type_enum AS ENUM ('github', 'gitlab', 'bitbucket', 'azure_devops');
CREATE TYPE job_status_enum AS ENUM ('pending', 'running', 'completed', 'failed');
CREATE TYPE trigger_enum AS ENUM ('pr', 'push', 'manual', 'scheduled');
CREATE TYPE analysis_type_enum AS ENUM ('quick', 'full', 'repository');
CREATE TYPE pillar_enum AS ENUM ('metrics', 'logs', 'traces', 'iac', 'pipeline');
CREATE TYPE severity_enum AS ENUM ('critical', 'warning', 'info');
CREATE TYPE dimension_enum AS ENUM ('cost', 'snr', 'pipeline', 'compliance', 'coverage');
CREATE TYPE billing_event_type_enum AS ENUM (
  'reserved', 'consumed', 'released', 'upgraded',
  'subscription_started', 'period_renewed', 'payment_failed',
  'subscription_canceled', 'overage_reported'
);
CREATE TYPE user_role_enum AS ENUM ('owner', 'admin', 'member', 'viewer');

-- ─────────────────────────────────────────────────────────────────────────────
-- CORE TABLES
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE tenants (
  id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name                        TEXT NOT NULL,
  slug                        TEXT NOT NULL UNIQUE,
  plan                        plan_enum NOT NULL DEFAULT 'free',
  credits_remaining           INT NOT NULL DEFAULT 50,
  credits_monthly_limit       INT NOT NULL DEFAULT 50,
  credits_used_this_period    INT NOT NULL DEFAULT 0,
  onboarding_step             INT NOT NULL DEFAULT 0,
  -- Stripe
  stripe_customer_id          TEXT UNIQUE,
  stripe_subscription_id      TEXT UNIQUE,
  stripe_subscription_status  TEXT,
  stripe_current_period_end   TIMESTAMPTZ,
  stripe_base_price_id        TEXT,
  stripe_overage_price_id     TEXT,
  billing_email               TEXT,
  -- Timestamps
  created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE organizations (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id   UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  name        TEXT NOT NULL,
  scm_type    scm_type_enum,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE users (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id      UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  org_id         UUID REFERENCES organizations(id) ON DELETE SET NULL,
  email          TEXT NOT NULL,
  password_hash  TEXT NOT NULL,
  role           user_role_enum NOT NULL DEFAULT 'member',
  is_active      BOOL NOT NULL DEFAULT TRUE,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, email)
);

CREATE TABLE api_keys (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id    UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  user_id      UUID REFERENCES users(id) ON DELETE SET NULL,
  key_hash     TEXT NOT NULL UNIQUE,
  key_hint     TEXT NOT NULL,  -- last 4 chars of plaintext key
  label        TEXT NOT NULL DEFAULT 'Default',
  scope        TEXT[] NOT NULL DEFAULT ARRAY['*'],
  is_active    BOOL NOT NULL DEFAULT TRUE,
  last_used_at TIMESTAMPTZ,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ─────────────────────────────────────────────────────────────────────────────
-- SCM CONNECTIONS
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE scm_connections (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id             UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  org_id                UUID REFERENCES organizations(id) ON DELETE SET NULL,
  scm_type              scm_type_enum NOT NULL,
  encrypted_token       BYTEA,
  token_scope           TEXT[],
  installation_id       TEXT,  -- GitHub App installation ID
  org_login             TEXT,
  org_avatar_url        TEXT,
  expires_at            TIMESTAMPTZ,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE repositories (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id         UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  org_id            UUID REFERENCES organizations(id),
  scm_connection_id UUID REFERENCES scm_connections(id) ON DELETE SET NULL,
  scm_repo_id       TEXT NOT NULL,
  full_name         TEXT NOT NULL,
  default_branch    TEXT NOT NULL DEFAULT 'main',
  clone_url         TEXT,
  is_active         BOOL NOT NULL DEFAULT FALSE,
  webhook_id        TEXT,  -- GitHub/GitLab webhook ID for cleanup
  -- Scheduled analysis
  schedule_enabled  BOOL NOT NULL DEFAULT FALSE,
  schedule_cron     TEXT NOT NULL DEFAULT '0 8 * * 1',
  schedule_ref      TEXT NOT NULL DEFAULT 'main',
  next_run_at       TIMESTAMPTZ,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, scm_repo_id)
);

-- ─────────────────────────────────────────────────────────────────────────────
-- ANALYSIS ENGINE
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE analysis_jobs (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id         UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  repo_id           UUID NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
  status            job_status_enum NOT NULL DEFAULT 'pending',
  trigger           trigger_enum NOT NULL,
  pr_number         INT,
  commit_sha        TEXT,
  branch_ref        TEXT,
  changed_files     JSONB,
  analysis_type     analysis_type_enum NOT NULL DEFAULT 'full',
  llm_provider      TEXT NOT NULL DEFAULT 'anthropic',
  credits_reserved  INT NOT NULL DEFAULT 0,
  credits_consumed  INT,
  error_message     TEXT,
  started_at        TIMESTAMPTZ,
  completed_at      TIMESTAMPTZ,
  fix_pr_url        TEXT,
  fix_pr_enqueued_at TIMESTAMPTZ,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE analysis_results (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id                UUID NOT NULL UNIQUE REFERENCES analysis_jobs(id) ON DELETE CASCADE,
  tenant_id             UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  -- Scores 0-100
  score_global          INT,
  score_metrics         INT,
  score_logs            INT,
  score_traces          INT,
  -- Efficiency scores
  score_cost            INT,
  score_snr             INT,
  score_pipeline        INT,
  score_compliance      INT,
  -- Findings & metadata
  findings              JSONB,
  call_graph_path       TEXT,
  raw_llm_calls         INT NOT NULL DEFAULT 0,
  input_tokens_total    INT NOT NULL DEFAULT 0,
  output_tokens_total   INT NOT NULL DEFAULT 0,
  cost_usd              DECIMAL(10,6) NOT NULL DEFAULT 0,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE findings (
  id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  result_id                   UUID NOT NULL REFERENCES analysis_results(id) ON DELETE CASCADE,
  tenant_id                   UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  pillar                      pillar_enum NOT NULL,
  severity                    severity_enum NOT NULL,
  dimension                   dimension_enum NOT NULL,
  title                       TEXT NOT NULL,
  description                 TEXT NOT NULL,
  file_path                   TEXT,
  line_start                  INT,
  line_end                    INT,
  suggestion                  TEXT,
  estimated_monthly_cost_impact DECIMAL(10,2) DEFAULT 0,
  created_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ─────────────────────────────────────────────────────────────────────────────
-- BILLING
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE billing_events (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id    UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  job_id       UUID REFERENCES analysis_jobs(id) ON DELETE SET NULL,
  event_type   billing_event_type_enum NOT NULL,
  credits_delta INT NOT NULL DEFAULT 0,
  usd_amount   DECIMAL(10,6) NOT NULL DEFAULT 0,
  description  TEXT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE stripe_events (
  id           TEXT PRIMARY KEY,  -- Stripe event ID (idempotency key)
  event_type   TEXT NOT NULL,
  payload      JSONB NOT NULL,
  processed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ─────────────────────────────────────────────────────────────────────────────
-- INDEXES
-- ─────────────────────────────────────────────────────────────────────────────

-- Organizations
CREATE INDEX idx_organizations_tenant_id ON organizations(tenant_id);

-- Users
CREATE INDEX idx_users_tenant_id ON users(tenant_id);
CREATE INDEX idx_users_email ON users(email);

-- API Keys
CREATE INDEX idx_api_keys_tenant_id ON api_keys(tenant_id);
CREATE INDEX idx_api_keys_key_hash ON api_keys(key_hash);

-- SCM Connections
CREATE INDEX idx_scm_connections_tenant_id ON scm_connections(tenant_id);

-- Repositories
CREATE INDEX idx_repositories_tenant_id ON repositories(tenant_id);
CREATE INDEX idx_repositories_scm_repo_id ON repositories(scm_repo_id);
CREATE INDEX idx_repositories_is_active ON repositories(is_active) WHERE is_active = TRUE;
CREATE INDEX idx_repositories_next_run ON repositories(next_run_at) WHERE schedule_enabled = TRUE;

-- Analysis Jobs
CREATE INDEX idx_analysis_jobs_tenant_id ON analysis_jobs(tenant_id);
CREATE INDEX idx_analysis_jobs_repo_id ON analysis_jobs(repo_id);
CREATE INDEX idx_analysis_jobs_status ON analysis_jobs(status);
CREATE INDEX idx_analysis_jobs_created_at ON analysis_jobs(created_at DESC);
CREATE INDEX idx_analysis_jobs_commit_idempotency ON analysis_jobs(repo_id, commit_sha, pr_number);

-- Analysis Results
CREATE INDEX idx_analysis_results_tenant_id ON analysis_results(tenant_id);
CREATE INDEX idx_analysis_results_job_id ON analysis_results(job_id);

-- Findings
CREATE INDEX idx_findings_result_id ON findings(result_id);
CREATE INDEX idx_findings_tenant_id ON findings(tenant_id);
CREATE INDEX idx_findings_severity ON findings(severity);
CREATE INDEX idx_findings_pillar ON findings(pillar);

-- Billing
CREATE INDEX idx_billing_events_tenant_id ON billing_events(tenant_id);
CREATE INDEX idx_billing_events_created_at ON billing_events(created_at DESC);

-- ─────────────────────────────────────────────────────────────────────────────
-- ROW LEVEL SECURITY
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE api_keys ENABLE ROW LEVEL SECURITY;
ALTER TABLE scm_connections ENABLE ROW LEVEL SECURITY;
ALTER TABLE repositories ENABLE ROW LEVEL SECURITY;
ALTER TABLE analysis_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE analysis_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE findings ENABLE ROW LEVEL SECURITY;
ALTER TABLE billing_events ENABLE ROW LEVEL SECURITY;

-- Tenants can only see their own tenant row
CREATE POLICY tenant_isolation ON tenants
  USING (id = current_setting('app.tenant_id', TRUE)::UUID);

-- All other tables use tenant_id column
CREATE POLICY tenant_isolation ON organizations
  USING (tenant_id = current_setting('app.tenant_id', TRUE)::UUID);

CREATE POLICY tenant_isolation ON users
  USING (tenant_id = current_setting('app.tenant_id', TRUE)::UUID);

CREATE POLICY tenant_isolation ON api_keys
  USING (tenant_id = current_setting('app.tenant_id', TRUE)::UUID);

CREATE POLICY tenant_isolation ON scm_connections
  USING (tenant_id = current_setting('app.tenant_id', TRUE)::UUID);

CREATE POLICY tenant_isolation ON repositories
  USING (tenant_id = current_setting('app.tenant_id', TRUE)::UUID);

CREATE POLICY tenant_isolation ON analysis_jobs
  USING (tenant_id = current_setting('app.tenant_id', TRUE)::UUID);

CREATE POLICY tenant_isolation ON analysis_results
  USING (tenant_id = current_setting('app.tenant_id', TRUE)::UUID);

CREATE POLICY tenant_isolation ON findings
  USING (tenant_id = current_setting('app.tenant_id', TRUE)::UUID);

CREATE POLICY tenant_isolation ON billing_events
  USING (tenant_id = current_setting('app.tenant_id', TRUE)::UUID);

-- stripe_events has no tenant_id — it's a global idempotency log, no RLS needed

-- ─────────────────────────────────────────────────────────────────────────────
-- TRIGGERS — updated_at auto-maintenance
-- ─────────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER tenants_updated_at BEFORE UPDATE ON tenants
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER users_updated_at BEFORE UPDATE ON users
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

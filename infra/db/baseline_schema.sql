-- ─────────────────────────────────────────────────────────────────────────────
-- Horion — PostgreSQL 16 + pgvector consolidated schema
-- Applied by the single Alembic baseline migration on fresh databases.
-- ─────────────────────────────────────────────────────────────────────────────

-- ═══════════════════════════════════════════════════════════════════════════
-- EXTENSIONS
-- ═══════════════════════════════════════════════════════════════════════════

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ═══════════════════════════════════════════════════════════════════════════
-- ENUMS
-- ═══════════════════════════════════════════════════════════════════════════

CREATE TYPE plan_enum AS ENUM ('free', 'starter', 'growth', 'scale', 'enterprise');
CREATE TYPE scm_type_enum AS ENUM ('github', 'gitlab', 'bitbucket', 'azure_devops');
CREATE TYPE job_status_enum AS ENUM ('pending', 'running', 'completed', 'failed');
CREATE TYPE trigger_enum AS ENUM ('pr', 'push', 'manual', 'scheduled');
CREATE TYPE analysis_type_enum AS ENUM ('quick', 'full', 'repository', 'context');
CREATE TYPE pillar_enum AS ENUM ('metrics', 'logs', 'traces', 'iac', 'pipeline', 'compliance', 'cost', 'snr');
CREATE TYPE severity_enum AS ENUM ('critical', 'warning', 'info');
CREATE TYPE dimension_enum AS ENUM ('cost', 'snr', 'pipeline', 'compliance', 'coverage');
CREATE TYPE billing_event_type_enum AS ENUM (
  'reserved', 'consumed', 'released', 'upgraded',
  'subscription_started', 'period_renewed', 'payment_failed',
  'subscription_canceled', 'overage_reported', 'wallet_credited'
);
CREATE TYPE user_role_enum AS ENUM ('owner', 'admin', 'member', 'viewer');
CREATE TYPE membership_role_enum AS ENUM ('admin', 'operator', 'viewer');
CREATE TYPE repo_type_enum AS ENUM ('app', 'iac', 'library', 'monorepo');
CREATE TYPE obs_backend_enum AS ENUM ('datadog', 'grafana', 'prometheus', 'dynatrace', 'splunk');
CREATE TYPE vendor_enum AS ENUM ('datadog', 'grafana', 'prometheus', 'dynatrace', 'splunk');
CREATE TYPE feedback_signal_enum AS ENUM ('thumbs_up', 'thumbs_down', 'ignored', 'applied');
CREATE TYPE feedback_target_enum AS ENUM ('finding', 'suggestion');

-- ═══════════════════════════════════════════════════════════════════════════
-- TABLES
-- ═══════════════════════════════════════════════════════════════════════════

-- Idempotency log — no tenant_id, no RLS
CREATE TABLE stripe_events (
  id            TEXT PRIMARY KEY,
  event_type    TEXT NOT NULL,
  payload       JSONB NOT NULL,
  processed_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE tenants (
  id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name                        TEXT NOT NULL,
  slug                        TEXT NOT NULL UNIQUE,
  plan                        plan_enum NOT NULL DEFAULT 'free',
  credits_remaining           INT NOT NULL DEFAULT 50,
  credits_monthly_limit       INT NOT NULL DEFAULT 50,
  credits_used_this_period    INT NOT NULL DEFAULT 0,
  extra_balance_usd           NUMERIC(12,2) NOT NULL DEFAULT 0,
  real_cost_used_this_period  NUMERIC(12,6) NOT NULL DEFAULT 0,
  onboarding_step             INT NOT NULL DEFAULT 0,
  needs_profile_completion    BOOL NOT NULL DEFAULT FALSE,
  stripe_customer_id          TEXT UNIQUE,
  stripe_subscription_id      TEXT UNIQUE,
  stripe_subscription_status  TEXT,
  stripe_current_period_end   TIMESTAMPTZ,
  stripe_base_price_id        TEXT,
  stripe_overage_price_id     TEXT,
  billing_email               TEXT,
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

CREATE TABLE tag_definitions (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  key             TEXT NOT NULL,
  label           TEXT NOT NULL,
  description     TEXT,
  required        BOOL NOT NULL DEFAULT FALSE,
  allowed_values  TEXT[],
  color_class     TEXT,
  sort_order      INT NOT NULL DEFAULT 0,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE tags (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id   UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  key         TEXT NOT NULL,
  value       TEXT NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_tags_tenant_key_value UNIQUE (tenant_id, key, value)
);

CREATE TABLE vendor_connections (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  vendor        vendor_enum NOT NULL,
  display_name  TEXT,
  api_key       TEXT,
  api_url       TEXT,
  extra_config  JSONB,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE scm_connections (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id         UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  org_id            UUID REFERENCES organizations(id),
  scm_type          scm_type_enum NOT NULL,
  encrypted_token   BYTEA,
  token_scope       TEXT[],
  installation_id   TEXT,
  org_login         TEXT,
  org_avatar_url    TEXT,
  expires_at        TIMESTAMPTZ,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE teams (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  name            TEXT NOT NULL,
  slug            TEXT NOT NULL,
  default_tag_id  UUID NOT NULL REFERENCES tags(id) ON DELETE RESTRICT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_teams_tenant_slug UNIQUE (tenant_id, slug)
);

CREATE TABLE users (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  org_id           UUID REFERENCES organizations(id),
  email            TEXT NOT NULL,
  password_hash    TEXT,
  oauth_google_sub TEXT UNIQUE,
  role             user_role_enum NOT NULL DEFAULT 'member',
  is_active        BOOL NOT NULL DEFAULT TRUE,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, email)
);

CREATE TABLE api_keys (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id    UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  user_id      UUID REFERENCES users(id) ON DELETE SET NULL,
  key_hash     TEXT NOT NULL UNIQUE,
  key_hint     TEXT NOT NULL,
  label        TEXT NOT NULL DEFAULT 'Default',
  scope        TEXT[] NOT NULL DEFAULT ARRAY['*'],
  is_active    BOOL NOT NULL DEFAULT TRUE,
  last_used_at TIMESTAMPTZ,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE repositories (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id             UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  org_id                UUID REFERENCES organizations(id),
  scm_connection_id     UUID REFERENCES scm_connections(id) ON DELETE SET NULL,
  scm_repo_id           TEXT NOT NULL,
  full_name             TEXT NOT NULL,
  default_branch        TEXT NOT NULL DEFAULT 'main',
  clone_url             TEXT,
  is_active             BOOL NOT NULL DEFAULT FALSE,
  webhook_id            TEXT,
  schedule_enabled      BOOL NOT NULL DEFAULT FALSE,
  schedule_cron         TEXT NOT NULL DEFAULT '0 8 * * 1',
  schedule_ref          TEXT NOT NULL DEFAULT 'main',
  next_run_at           TIMESTAMPTZ,
  repo_type             repo_type_enum,
  language              TEXT[],
  observability_backend obs_backend_enum,
  app_subtype           TEXT,
  iac_provider          TEXT,
  instrumentation       TEXT,
  obs_metadata          JSONB,
  context_summary       TEXT,
  context_updated_at    TIMESTAMPTZ,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, scm_repo_id)
);

CREATE TABLE team_memberships (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  team_id     UUID NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  tenant_id   UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_team_memberships_team_user UNIQUE (team_id, user_id)
);

CREATE TABLE tenant_invites (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  email               TEXT NOT NULL,
  role                membership_role_enum NOT NULL,
  token_hash          TEXT NOT NULL UNIQUE,
  invited_by_user_id  UUID REFERENCES users(id) ON DELETE SET NULL,
  expires_at          TIMESTAMPTZ NOT NULL,
  accepted_at         TIMESTAMPTZ,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE tenant_memberships (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  tenant_id   UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  role        membership_role_enum NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_tenant_memberships_user_tenant UNIQUE (user_id, tenant_id)
);

CREATE TABLE analysis_jobs (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id             UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  repo_id               UUID NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
  status                job_status_enum NOT NULL DEFAULT 'pending',
  trigger               trigger_enum NOT NULL,
  pr_number             INT,
  commit_sha            TEXT,
  branch_ref            TEXT,
  changed_files         JSONB,
  analysis_type         analysis_type_enum NOT NULL DEFAULT 'full',
  scope_type            TEXT NOT NULL DEFAULT 'full_repo',
  llm_provider          TEXT NOT NULL DEFAULT 'anthropic',
  credits_reserved      INT NOT NULL DEFAULT 0,
  billing_reservation   JSONB,
  credits_consumed      INT,
  input_tokens          INT NOT NULL DEFAULT 0,
  output_tokens         INT NOT NULL DEFAULT 0,
  input_tokens_cached   INT NOT NULL DEFAULT 0,
  llm_cost_usd          NUMERIC(10,6) NOT NULL DEFAULT 0,
  infra_cost_usd        NUMERIC(10,6) NOT NULL DEFAULT 0,
  total_cost_usd        NUMERIC(10,6) NOT NULL DEFAULT 0,
  margin_applied        NUMERIC(4,2) NOT NULL DEFAULT 3.0,
  estimated_cost_usd    NUMERIC(10,6) NOT NULL DEFAULT 0,
  selected_paths        JSONB NOT NULL DEFAULT '[]',
  error_message         TEXT,
  started_at            TIMESTAMPTZ,
  completed_at          TIMESTAMPTZ,
  fix_pr_url            TEXT,
  fix_pr_enqueued_at    TIMESTAMPTZ,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE repo_tags (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id   UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  repo_id     UUID NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
  key         TEXT NOT NULL,
  value       TEXT NOT NULL,
  source      TEXT NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE repository_tags (
  repository_id UUID NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
  tag_id        UUID NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
  PRIMARY KEY (repository_id, tag_id),
  CONSTRAINT uq_repository_tags_repo_tag UNIQUE (repository_id, tag_id)
);

CREATE TABLE analysis_results (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id              UUID NOT NULL UNIQUE REFERENCES analysis_jobs(id) ON DELETE CASCADE,
  tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  score_global        INT,
  score_metrics       INT,
  score_logs          INT,
  score_traces        INT,
  score_cost          INT,
  score_snr           INT,
  score_pipeline      INT,
  score_compliance    INT,
  previous_job_id     UUID REFERENCES analysis_jobs(id) ON DELETE SET NULL,
  crossrun_summary    JSONB,
  findings            JSONB,
  call_graph_path     TEXT,
  raw_llm_calls       INT NOT NULL DEFAULT 0,
  input_tokens_total  INT NOT NULL DEFAULT 0,
  output_tokens_total INT NOT NULL DEFAULT 0,
  cost_usd            NUMERIC(10,6) NOT NULL DEFAULT 0,
  cost_breakdown      JSONB DEFAULT '{}'::jsonb,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE analysis_tags (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id   UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  job_id      UUID NOT NULL REFERENCES analysis_jobs(id) ON DELETE CASCADE,
  key         TEXT NOT NULL,
  value       TEXT NOT NULL,
  source      TEXT NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE billing_events (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  job_id        UUID REFERENCES analysis_jobs(id) ON DELETE SET NULL,
  event_type    billing_event_type_enum NOT NULL,
  credits_delta INT NOT NULL DEFAULT 0,
  usd_amount    NUMERIC(10,6) NOT NULL DEFAULT 0,
  description   TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE cost_events (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id          UUID NOT NULL REFERENCES analysis_jobs(id) ON DELETE CASCADE,
  tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  event_type      TEXT NOT NULL,
  stage           TEXT,
  input_tokens    INT NOT NULL DEFAULT 0,
  output_tokens   INT NOT NULL DEFAULT 0,
  cached_tokens   INT NOT NULL DEFAULT 0,
  llm_provider    TEXT,
  cost_usd        NUMERIC(10,6) NOT NULL DEFAULT 0,
  cumulative_cost NUMERIC(10,6) NOT NULL DEFAULT 0,
  metadata_json   JSONB,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE findings (
  id                            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  result_id                     UUID NOT NULL REFERENCES analysis_results(id) ON DELETE CASCADE,
  tenant_id                     UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  pillar                        pillar_enum NOT NULL,
  severity                      severity_enum NOT NULL,
  dimension                     dimension_enum NOT NULL,
  title                         TEXT NOT NULL,
  description                   TEXT NOT NULL,
  file_path                     TEXT,
  line_start                    INT,
  line_end                      INT,
  suggestion                    TEXT,
  estimated_monthly_cost_impact NUMERIC(10,2) NOT NULL DEFAULT 0,
  created_at                    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE finding_feedback (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  finding_id  UUID NOT NULL REFERENCES findings(id) ON DELETE CASCADE,
  job_id      UUID NOT NULL REFERENCES analysis_jobs(id) ON DELETE CASCADE,
  tenant_id   UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  target_type feedback_target_enum NOT NULL DEFAULT 'finding',
  signal      feedback_signal_enum NOT NULL,
  note        TEXT,
  feedback_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ═══════════════════════════════════════════════════════════════════════════
-- KNOWLEDGE BASE (pgvector)
-- knowledge_chunks requires the pgvector extension. If the extension is not
-- available the migration Python code skips this section gracefully.
-- ═══════════════════════════════════════════════════════════════════════════

-- __PGVECTOR_START__

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS knowledge_chunks (
  id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id   UUID        REFERENCES tenants(id) ON DELETE CASCADE,
  source_type TEXT        NOT NULL,
  content     TEXT        NOT NULL,
  embedding   vector(1536) NOT NULL,
  metadata    JSONB       DEFAULT '{}',
  language    TEXT,
  pillar      TEXT,
  repo_id     UUID        REFERENCES repositories(id) ON DELETE CASCADE,
  expires_at  TIMESTAMPTZ,
  created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS knowledge_chunks_embedding_idx
  ON knowledge_chunks USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_tenant_source_lang
  ON knowledge_chunks (tenant_id, source_type, language);

CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_expires_at
  ON knowledge_chunks (expires_at) WHERE expires_at IS NOT NULL;

ALTER TABLE knowledge_chunks ENABLE ROW LEVEL SECURITY;

CREATE POLICY rag_isolation ON knowledge_chunks
  USING (tenant_id IS NULL OR tenant_id = current_setting('app.tenant_id', TRUE)::UUID);

-- __PGVECTOR_END__

-- ═══════════════════════════════════════════════════════════════════════════
-- INDEXES
-- ═══════════════════════════════════════════════════════════════════════════

-- Organizations
CREATE INDEX idx_organizations_tenant_id ON organizations(tenant_id);

-- Users
CREATE INDEX idx_users_tenant_id ON users(tenant_id);
CREATE INDEX idx_users_email ON users(email);
CREATE UNIQUE INDEX ix_users_oauth_google_sub ON users(oauth_google_sub);

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
CREATE INDEX idx_analysis_results_previous_job_id ON analysis_results(previous_job_id);

-- Findings
CREATE INDEX idx_findings_result_id ON findings(result_id);
CREATE INDEX idx_findings_tenant_id ON findings(tenant_id);
CREATE INDEX idx_findings_severity ON findings(severity);
CREATE INDEX idx_findings_pillar ON findings(pillar);

-- Finding Feedback
CREATE INDEX idx_finding_feedback_finding_id ON finding_feedback(finding_id);
CREATE INDEX idx_finding_feedback_tenant_id ON finding_feedback(tenant_id, feedback_at DESC);

-- Billing
CREATE INDEX idx_billing_events_tenant_id ON billing_events(tenant_id);
CREATE INDEX idx_billing_events_created_at ON billing_events(created_at DESC);

-- Cost Events
CREATE INDEX ix_cost_events_job_id ON cost_events(job_id);
CREATE INDEX ix_cost_events_tenant_id ON cost_events(tenant_id);

-- Tags (legacy team system)
CREATE INDEX ix_tags_tenant_id ON tags(tenant_id);

-- Teams
CREATE INDEX ix_teams_tenant_id ON teams(tenant_id);

-- Team Memberships
CREATE INDEX ix_team_memberships_user_id ON team_memberships(user_id);
CREATE INDEX ix_team_memberships_tenant_id ON team_memberships(tenant_id);
CREATE INDEX ix_team_memberships_team_id ON team_memberships(team_id);

-- Repository Tags (legacy team system)
CREATE INDEX ix_repository_tags_tag_id ON repository_tags(tag_id);

-- Tenant Memberships
CREATE INDEX ix_tenant_memberships_tenant_id ON tenant_memberships(tenant_id);
CREATE INDEX ix_tenant_memberships_user_id ON tenant_memberships(user_id);
CREATE INDEX ix_tenant_invites_tenant_email ON tenant_invites(tenant_id, lower(email));

-- Tag Definitions
CREATE INDEX idx_tag_definitions_tenant ON tag_definitions(tenant_id);

-- Repo Tags (metadata tag system)
CREATE INDEX idx_repo_tags_repo ON repo_tags(repo_id);
CREATE INDEX idx_repo_tags_tenant ON repo_tags(tenant_id);
CREATE INDEX idx_repo_tags_key_val ON repo_tags(key, value);

-- Analysis Tags
CREATE INDEX idx_analysis_tags_job ON analysis_tags(job_id);
CREATE INDEX idx_analysis_tags_tenant ON analysis_tags(tenant_id);
CREATE INDEX idx_analysis_tags_kv ON analysis_tags(key, value);

-- ═══════════════════════════════════════════════════════════════════════════
-- ROW LEVEL SECURITY
-- ═══════════════════════════════════════════════════════════════════════════

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
ALTER TABLE tag_definitions ENABLE ROW LEVEL SECURITY;
ALTER TABLE repo_tags ENABLE ROW LEVEL SECURITY;
ALTER TABLE analysis_tags ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON tenants
  USING (id = current_setting('app.tenant_id', TRUE)::UUID);

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

CREATE POLICY tenant_isolation ON tag_definitions
  USING (tenant_id = current_setting('app.tenant_id', TRUE)::UUID);

CREATE POLICY tenant_isolation ON repo_tags
  USING (tenant_id = current_setting('app.tenant_id', TRUE)::UUID);

CREATE POLICY tenant_isolation ON analysis_tags
  USING (tenant_id = current_setting('app.tenant_id', TRUE)::UUID);

-- ═══════════════════════════════════════════════════════════════════════════
-- TRIGGERS
-- ═══════════════════════════════════════════════════════════════════════════

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

# Lumis — Illuminate what's invisible in your code

AI-powered SRE platform with specialized agents that analyze source code, IaC, and architecture blueprints to predict observability gaps and suggest instrumentation.

## Quick Start

```bash
# 1. Clone and enter the project
cd lumis

# 2. Copy and configure environment
cp .env.local.example .env.local
# Required: ANTHROPIC_API_KEY, SECRET_KEY
# Optional: STRIPE_SECRET_KEY (for billing), GITHUB_APP_* (for SCM)

# 3. Create Stripe products (if using billing)
make stripe-fixture

# 4. Start everything
make dev-up
```

Services after `make dev-up`:
| Service | URL |
|---------|-----|
| Frontend | http://localhost:3000 |
| API | http://localhost:8000 |
| API Docs | http://localhost:8000/docs |
| Flower | http://localhost:5555 |
| MinIO Console | http://localhost:9001 |

Demo credentials: `owner@acme.com` / `demo1234`

## Architecture

```
lumis/
├── apps/
│   ├── web/      # Next.js 14 — Dashboard, analyses, billing
│   ├── api/      # FastAPI — REST API, webhooks, billing
│   ├── agent/    # LangGraph — 9-node observability analysis graph
│   └── worker/   # Celery — Async task processing
├── packages/
│   ├── ast-utils/      # tree-sitter AST parsing
│   ├── dd-client/      # Datadog API client
│   └── otel-snippets/  # OTel instrumentation templates
├── infra/
│   ├── db/       # PostgreSQL schema + migrations
│   ├── k8s/      # Kubernetes manifests
│   └── helm/     # Helm chart (local/staging/production)
└── scripts/      # Dev tooling
```

## Common Commands

```bash
make dev-up          # Full local setup
make migrate         # Run DB migrations
make migration name="add_feature"  # Create new migration
make seed            # Populate demo data
make test            # Run all tests
make analyze repo=https://github.com/opentelemetry/opentelemetry-demo

# Stripe development
make stripe-listen   # Forward webhooks to local API
make stripe-fixture  # Create products/prices in test mode

# Kubernetes
make k8s-deploy env=staging
```

## Billing Model

| Plan | Credits/month | Price | Overage |
|------|--------------|-------|---------|
| Free | 50 | $0 | No overage |
| Starter | 300 | $49/mo | $0.35/credit |
| Growth | 1,000 | $149/mo | $0.25/credit |
| Scale | 5,000 | $449/mo | $0.15/credit |

Analysis costs: quick (< 10 files) = 1 credit, full (10-50 files) = 3 credits, repository = 15 credits.

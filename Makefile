.PHONY: dev-up up down build logs logs-api logs-agent logs-worker \
        shell-api shell-db migrate migration seed test test-api test-agent \
        analyze k8s-deploy k8s-logs clean stripe-listen stripe-fixture

# Celery worker container count (horizontal scale). Example: `make up WORKER_REPLICAS=3`
WORKER_REPLICAS ?= 1

# ── Development ─────────────────────────────────────────────────────────────

dev-up: build up wait-healthy migrate seed
	@echo "✓ Stack is running"
	@echo "  API:     http://localhost:8000"
	@echo "  Docs:    http://localhost:8000/docs"
	@echo "  Flower:  http://localhost:5555"
	@echo "  MinIO:   http://localhost:9001  (minioadmin / minioadmin)"
	@echo "  Frontend: horion-frontend repo (Vercel)"

up:
	docker compose up -d --scale worker=$(WORKER_REPLICAS)

down:
	docker compose down

build:
	docker compose build

logs:
	docker compose logs -f

logs-api:
	docker compose logs -f api

logs-agent:
	docker compose logs -f agent

logs-worker:
	docker compose logs -f worker

shell-api:
	docker compose exec api bash

shell-db:
	docker compose exec postgres psql -U sre -d lumis

# ── Database ─────────────────────────────────────────────────────────────────

migrate:
	docker compose exec api alembic -c apps/api/alembic.ini upgrade head

migration:
	@if [ -z "$(name)" ]; then echo "Usage: make migration name=<description>"; exit 1; fi
	docker compose exec api alembic -c apps/api/alembic.ini revision --autogenerate -m "$(name)"

seed:
	docker compose exec api python scripts/seed.py

# ── Wait for services to be healthy ─────────────────────────────────────────

wait-healthy:
	@echo "Waiting for services to be healthy..."
	@timeout 120 bash -c 'until docker compose ps | grep -E "(api|postgres|redis)" | grep -v "unhealthy\|starting" | grep "healthy" | wc -l | grep -q "^3$$"; do sleep 2; done' || (echo "Services failed to start"; docker compose logs; exit 1)

# ── Testing ──────────────────────────────────────────────────────────────────

test: test-api test-agent
	@echo "All tests passed!"

test-api:
	docker compose exec api pytest apps/api/tests -v --tb=short

test-agent:
	docker compose exec agent pytest apps/agent/tests -v --tb=short

# ── Analysis CLI ─────────────────────────────────────────────────────────────

analyze:
	@if [ -z "$(repo)" ]; then echo "Usage: make analyze repo=<url>"; exit 1; fi
	docker compose exec api python scripts/analyze_repo.py --repo $(repo)

# ── Stripe ───────────────────────────────────────────────────────────────────

stripe-listen:
	@echo "Forwarding Stripe webhooks to localhost:8000/webhooks/stripe"
	@echo "Copy the webhook secret to STRIPE_WEBHOOK_SECRET in .env.local"
	stripe listen --forward-to localhost:8000/webhooks/stripe

stripe-fixture:
	@echo "Creating Stripe products, prices, and meter..."
	python scripts/stripe_setup.py
	@echo "Copy the printed values into your .env.local"

# ── Kubernetes ───────────────────────────────────────────────────────────────

k8s-deploy:
	@if [ -z "$(env)" ]; then echo "Usage: make k8s-deploy env=staging|production"; exit 1; fi
	helm upgrade --install lumis infra/helm/lumis \
		-f infra/helm/lumis/values.yaml \
		-f infra/helm/lumis/values.$(env).yaml \
		--namespace lumis --create-namespace

k8s-logs:
	@if [ -z "$(svc)" ]; then echo "Usage: make k8s-logs svc=api|worker|agent|web|beat|flower"; exit 1; fi
	kubectl logs -n lumis -l app.kubernetes.io/component=$(svc) -f

# ── Cleanup ──────────────────────────────────────────────────────────────────

clean:
	docker compose down -v --remove-orphans
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true

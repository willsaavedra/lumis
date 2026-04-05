#!/usr/bin/env bash
set -euo pipefail

echo "╔══════════════════════════════════════════════════╗"
echo "║  Lumis — Local Development Setup                ║"
echo "╚══════════════════════════════════════════════════╝"

# Check prerequisites
command -v docker &>/dev/null || { echo "Docker is required"; exit 1; }
command -v docker compose &>/dev/null || { echo "Docker Compose is required"; exit 1; }

# Copy env file if it doesn't exist
if [ ! -f .env.local ]; then
    cp .env.local.example .env.local
    echo "✓ Created .env.local from example"
    echo "  Please edit .env.local and add your ANTHROPIC_API_KEY"
    echo "  Then re-run this script."
    exit 0
fi

# Build images
echo ""
echo "→ Building Docker images..."
docker compose build

# Start services
echo ""
echo "→ Starting services..."
docker compose up -d

# Wait for health
echo ""
echo "→ Waiting for services to be healthy..."
timeout 120 bash -c '
    until docker compose ps --format json | python3 -c "
import json, sys
data = sys.stdin.read()
services = [json.loads(l) for l in data.strip().split(\"\\n\") if l]
healthy = [s for s in services if s.get(\"Health\") == \"healthy\" or s.get(\"State\") == \"running\"]
print(f\"Healthy: {len(healthy)}/{len(services)}\")
sys.exit(0 if len(healthy) >= 4 else 1)
"; do
        sleep 3
    done
' || { echo "Services failed to start"; docker compose logs; exit 1; }

# Run migrations
echo ""
echo "→ Running database migrations..."
docker compose exec -T api alembic upgrade head

# Seed demo data
echo ""
echo "→ Seeding demo data..."
docker compose exec -T api python scripts/seed.py

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║  Lumis is ready!                                 ║"
echo "╠══════════════════════════════════════════════════╣"
echo "║  Frontend:  http://localhost:3000                ║"
echo "║  API:       http://localhost:8000                ║"
echo "║  API Docs:  http://localhost:8000/docs           ║"
echo "║  Flower:    http://localhost:5555                ║"
echo "║  MinIO:     http://localhost:9001                ║"
echo "╠══════════════════════════════════════════════════╣"
echo "║  Login:     owner@acme.com / demo1234            ║"
echo "╚══════════════════════════════════════════════════╝"

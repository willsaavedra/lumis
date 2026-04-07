FROM python:3.12-slim AS base
WORKDIR /workspace
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl git && rm -rf /var/lib/apt/lists/*

# Agent runs LangGraph + imports `apps.api` (DB, models, billing). Install API stack
# first, then agent-only extras (tree-sitter, etc.).
FROM base AS deps
COPY apps/api/requirements.txt ./api-requirements.txt
COPY apps/agent/requirements.txt ./agent-requirements.txt
RUN pip install --no-cache-dir -r api-requirements.txt -r agent-requirements.txt

FROM deps AS dev
COPY . .
ENV PYTHONPATH=/workspace
CMD ["python", "-m", "uvicorn", "apps.agent.server:app", "--host", "0.0.0.0", "--port", "8001", "--reload"]

FROM deps AS prod
COPY . .
ENV PYTHONPATH=/workspace
CMD ["python", "-m", "uvicorn", "apps.agent.server:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "2"]

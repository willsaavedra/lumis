FROM python:3.12-slim AS base
WORKDIR /workspace
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl git && rm -rf /var/lib/apt/lists/*

FROM base AS deps
COPY apps/agent/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM deps AS dev
COPY . .
ENV PYTHONPATH=/workspace
CMD ["python", "-m", "uvicorn", "apps.agent.server:app", "--host", "0.0.0.0", "--port", "8001", "--reload"]

FROM deps AS prod
COPY . .
ENV PYTHONPATH=/workspace
CMD ["python", "-m", "uvicorn", "apps.agent.server:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "2"]

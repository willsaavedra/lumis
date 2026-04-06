# Python Observability Analysis

## Core checks

### Q1: Existing instrumentation
- OTel Python SDK (opentelemetry-*)
- Structured logging (structlog, python-json-logger)
- Framework middleware (FastAPI, Django, Flask)

### Q2: Missing coverage
- Bare except without error recording
- Celery tasks without trace context
- asyncio tasks losing span context
- ORM queries without tracing (SQLAlchemy, Django ORM)

### Q3: Anti-patterns
- print() in production
- f-string interpolation with PII
- Logging at wrong levels
- Missing correlation IDs

### Q4: Production impact
- Celery task failures invisible
- Async debugging blind spots
- Database query performance unknown

# TypeScript/JavaScript Observability Analysis

## Core checks (Q1-Q4 framework)

### Q1: Existing instrumentation
- OpenTelemetry SDK imports (@opentelemetry/*)
- Express/Fastify/NestJS middleware for tracing
- Structured logger usage (pino, winston, bunyan)
- Custom metrics (Prometheus client, StatsD)

### Q2: Missing coverage
- Async/await chains without error spans
- HTTP client calls (fetch, axios) without distributed tracing
- Database queries without query tracing
- Queue consumers/producers without context propagation
- Event loop blocking without metrics

### Q3: Anti-patterns
- console.log/console.error instead of structured logging
- String interpolation with PII in logs
- High-cardinality span attributes (user IDs, request paths)
- Missing try/catch on awaited promises

### Q4: Production impact
- Blind spots in error debugging
- Missing correlation between services
- Cost waste from noisy/redundant telemetry
- Alert gaps on critical paths

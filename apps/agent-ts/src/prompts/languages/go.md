# Go Observability Analysis

## Core checks

### Q1: Existing instrumentation
- OTel Go SDK (go.opentelemetry.io/otel)
- Structured logging (zerolog, zap, slog)
- Prometheus metrics
- context.Context propagation

### Q2: Missing coverage
- Error paths without span.RecordError()
- Goroutine spawns losing trace context
- HTTP handlers without middleware tracing
- gRPC interceptors missing
- Database drivers without otel instrumentation

### Q3: Anti-patterns
- fmt.Printf / log.Printf in production code
- Missing defer span.End()
- Context not passed through function chains
- Error swallowing (_ = err)

### Q4: Production impact
- Goroutine leaks invisible without metrics
- Lost trace context across service boundaries
- Error debugging blind spots

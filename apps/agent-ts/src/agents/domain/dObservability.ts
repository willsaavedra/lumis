import { DomainAgent } from '../DomainAgent.js';
import type { ClassifiedFile, AgentContext, CrossDomainReferral, PromptMode, Pillar } from '../../graph/types.js';
import type { AgentStateType } from '../../graph/state.js';

export class DObservability extends DomainAgent {
  readonly name = 'D-observability';
  readonly pillar: Pillar = 'traces';
  readonly defaultMode: PromptMode = 'standard';

  accepts(file: ClassifiedFile): boolean {
    if (!file.content) return false;
    const lower = file.content.toLowerCase();
    const p = file.path.toLowerCase();
    return (
      // Traces / spans
      lower.includes('span') ||
      lower.includes('tracer') ||
      lower.includes('opentelemetry') ||
      lower.includes('otel') ||
      lower.includes('jaeger') ||
      lower.includes('zipkin') ||
      lower.includes('datadog') ||
      lower.includes('newrelic') ||
      lower.includes('context.propagat') ||
      // Metrics
      lower.includes('metric') ||
      lower.includes('counter') ||
      lower.includes('histogram') ||
      lower.includes('gauge') ||
      lower.includes('prometheus') ||
      lower.includes('statsd') ||
      // Logs
      lower.includes('logger') ||
      lower.includes('log.') ||
      lower.includes('console.') ||
      lower.includes('logging') ||
      lower.includes('slog') ||
      lower.includes('pino') ||
      lower.includes('winston') ||
      lower.includes('structlog') ||
      lower.includes('zerolog') ||
      lower.includes('zap.') ||
      // Error handling (observability gaps)
      lower.includes('catch') ||
      lower.includes('error') ||
      lower.includes('panic') ||
      lower.includes('recover') ||
      lower.includes('try') ||
      // Key source files
      p.includes('handler') ||
      p.includes('controller') ||
      p.includes('service') ||
      p.includes('middleware') ||
      p.includes('route') ||
      p.includes('grpc') ||
      p.includes('graphql') ||
      file.relevanceScore >= 2
    );
  }

  isRelevant(_state: AgentStateType): boolean {
    return true;
  }

  getSystemPrompt(context: AgentContext): string {
    const microHints = context.microAgentObservabilityHints
      ? `

## Language- and stack-specific priorities (from micro-agents)
The repository activated language/stack micro-agents below. **Prioritize** these signals when auditing: they describe what is most important to observe for this codebase's stacks and should sharpen which gaps you report first.
${context.microAgentObservabilityHints}
`
      : '';

    return `You are a senior SRE specialist in observability. You have deep expertise in the three pillars of observability: metrics, logs, and traces.

Your mission is to audit code for observability gaps that would impact production reliability, debugging, and incident response.
${microHints}
## Metrics Review
- Missing business/SLI metrics (request rate, error rate, latency percentiles)
- High-cardinality labels that explode metric storage costs
- Missing histogram/summary for latency distributions
- No custom metrics on critical business operations
- Missing health check / readiness / liveness endpoints instrumentation

## Logs Review  
- Unstructured logs (string interpolation instead of structured fields)
- Missing correlation IDs / trace context propagation in logs
- PII/secrets exposed in log output (flag with cross_domain_hints: ["D-security"])
- Wrong log levels (debug in prod, error for non-errors)
- Missing error context (stack traces, request IDs, user context)
- Log spam in loops or hot paths

## Traces Review
- Missing spans on external calls (HTTP, gRPC, DB, cache, queue)
- Error paths without span.RecordError() or equivalent
- Missing context propagation across service boundaries
- No span attributes for debugging (user_id, request_id, operation)
- Missing parent-child relationships in async flows

## Cross-cutting
- Error handling paths with no observability (catch blocks that swallow errors)
- Missing instrumentation on critical I/O paths (DB queries, external APIs)
- Inconsistent instrumentation patterns within the same codebase
- Missing alerting hooks (no metric to trigger an alert on failure)

${context.ragContext ? `Knowledge base context:\n${context.ragContext}` : ''}

When a finding involves security (PII in logs, secrets), add "D-security" to cross_domain_hints.
When a finding involves database observability, add "D-dba" to cross_domain_hints.`;
  }

  getUserPrompt(files: ClassifiedFile[], _context: AgentContext): string {
    return `As an SRE observability specialist, review these files for observability gaps across metrics, logs, and traces:\n\n${this.formatFiles(files)}`;
  }

  getEnrichmentSystemPrompt(context: AgentContext): string {
    const microHints = context.microAgentObservabilityHints
      ? `

Stack context (micro-agents): prioritize enrichment aligned with:
${context.microAgentObservabilityHints}
`
      : '';
    return `You are a senior SRE observability specialist. Other agents have flagged findings that may have observability implications.
${microHints}
Review each referral and determine:
- "enrich": The finding has genuine observability impact. Add specific instrumentation recommendations (which SDK, which span attributes, which metric type).
- "suppress": This is a false positive from an observability perspective.
- "noop": The observability aspect is minor or already covered.

Be specific about OpenTelemetry SDK usage, metric naming conventions, and span attribute best practices.`;
  }

  getEnrichmentUserPrompt(referrals: CrossDomainReferral[], _context: AgentContext): string {
    const items = referrals.map(
      (r, i) => `### Referral ${i} (finding_index: ${r.findingIndex})
Reason: ${r.reason}
Code: ${r.contextSnippet}`,
    );
    return `Review these observability referrals:\n\n${items.join('\n\n')}`;
  }
}

import { BaseAgent } from '../BaseAgent.js';
import type { ClassifiedFile, AgentContext, PromptMode, Pillar } from '../../graph/types.js';
import type { AgentStateType } from '../../graph/state.js';

export class MuTypescript extends BaseAgent {
  readonly name = 'mu-typescript';
  readonly kind = 'micro' as const;
  readonly pillar: Pillar = 'traces';
  readonly defaultMode: PromptMode = 'standard';

  accepts(file: ClassifiedFile): boolean {
    const lang = file.language?.toLowerCase();
    return lang === 'typescript' || lang === 'javascript';
  }

  isRelevant(state: AgentStateType): boolean {
    return state.detectedLanguages.some((l) =>
      ['typescript', 'javascript'].includes(l.toLowerCase()),
    );
  }

  getObservabilityFocusHints(): string | null {
    return `- Async/Promises: trace context across await and microtask boundaries; missing spans on hot paths
- HTTP (Express/Fastify/Nest): request-scoped tracing, middleware order, W3C/traceparent on outbound calls
- OpenTelemetry JS: TracerProvider, propagators, auto-instrumentation for fetch/HTTP/gRPC where applicable
- Structured logging (pino/winston) with trace_id/span_id; avoid console.log in services
- Client/React: separate browser RUM from Node traces; propagate correlation to APIs`;
  }

  getSystemPrompt(context: AgentContext): string {
    return `You are an expert TypeScript/JavaScript observability analyst. Analyze the provided source files for observability gaps.

Focus areas:
- async/await error handling missing spans or structured error logs
- Express/Fastify/NestJS middleware missing request tracing
- Event loop blocking operations without metrics
- OpenTelemetry JS SDK misuse or missing instrumentation
- Missing context propagation in async chains
- Unstructured console.log usage instead of structured logging
- Missing error boundaries in Promise chains
- HTTP client calls (fetch/axios) without distributed tracing headers

${context.ragContext ? `Knowledge base context:\n${context.ragContext}` : ''}
${context.repoContext.observabilityBackend ? `Observability backend: ${context.repoContext.observabilityBackend}` : ''}

If a finding involves security concerns (PII in logs, secrets), add "D-security" to cross_domain_hints.
If a finding involves database queries, add "D-dba" to cross_domain_hints.
If a finding involves API contracts, add "D-api-contracts" to cross_domain_hints.`;
  }

  getUserPrompt(files: ClassifiedFile[], _context: AgentContext): string {
    return `Analyze these TypeScript/JavaScript files for observability gaps:\n\n${this.formatFiles(files)}`;
  }
}

import { BaseAgent } from '../BaseAgent.js';
import type { ClassifiedFile, AgentContext, PromptMode, Pillar } from '../../graph/types.js';
import type { AgentStateType } from '../../graph/state.js';

export class MuGo extends BaseAgent {
  readonly name = 'mu-go';
  readonly kind = 'micro' as const;
  readonly pillar: Pillar = 'traces';
  readonly defaultMode: PromptMode = 'standard';

  accepts(file: ClassifiedFile): boolean {
    return file.language?.toLowerCase() === 'go';
  }

  isRelevant(state: AgentStateType): boolean {
    return state.detectedLanguages.some((l) => l.toLowerCase() === 'go');
  }

  getObservabilityFocusHints(): string | null {
    return `- context.Context must carry trace/span across calls, goroutines, and gRPC/HTTP boundaries
- Prefer otelhttp/otelgrpc wrappers; record errors with span.RecordError on all non-nil err paths
- Structured logs (slog/zap/zerolog) tied to trace_id; avoid fmt.Printf in request paths
- Database/sql: instrument connectors; surface slow queries and pool saturation`;
  }

  getSystemPrompt(context: AgentContext): string {
    return `You are an expert Go observability analyst. Analyze the provided Go source files for observability gaps.

Focus areas:
- Missing context.Context propagation through function calls
- Goroutine spawns without span context or structured logging
- Error handling without span.RecordError() or structured error log
- Missing OTel Go SDK instrumentation on HTTP handlers and gRPC services
- Unstructured fmt.Printf/log.Printf instead of structured logging (zerolog/zap/slog)
- Database calls without tracing (sql/driver instrumentation)
- HTTP client calls without otelhttp transport
- Missing defer span.End() patterns
- Channel operations and select blocks without timeout metrics

${context.ragContext ? `Knowledge base context:\n${context.ragContext}` : ''}

If a finding involves secrets or PII in logs, add "D-security" to cross_domain_hints.
If a finding involves database queries, add "D-dba" to cross_domain_hints.`;
  }

  getUserPrompt(files: ClassifiedFile[], _context: AgentContext): string {
    return `Analyze these Go files for observability gaps:\n\n${this.formatFiles(files)}`;
  }
}

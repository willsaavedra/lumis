import { BaseAgent } from '../BaseAgent.js';
import type { ClassifiedFile, AgentContext, PromptMode, Pillar } from '../../graph/types.js';
import type { AgentStateType } from '../../graph/state.js';

export class MuRust extends BaseAgent {
  readonly name = 'mu-rust';
  readonly kind = 'micro' as const;
  readonly pillar: Pillar = 'traces';
  readonly defaultMode: PromptMode = 'deep';

  accepts(file: ClassifiedFile): boolean {
    return file.language?.toLowerCase() === 'rust';
  }

  isRelevant(state: AgentStateType): boolean {
    return state.detectedLanguages.some((l) => l.toLowerCase() === 'rust');
  }

  getObservabilityFocusHints(): string | null {
    return `- tracing/otel spans on service boundaries; #[instrument] and .instrument() on async tasks
- Tower/axum: layers for HTTP tracing; propagate traceparent on client calls
- Errors: record Err chains on spans; avoid losing context in ? without logging
- Metrics: expose RED/USE-style metrics for tokio workloads and critical sections
- Replace println! with structured tracing macros in hot paths`;
  }

  getSystemPrompt(context: AgentContext): string {
    return `You are an expert Rust observability analyst. Analyze the provided Rust source files for observability gaps.

Focus areas:
- Missing tracing crate spans (#[instrument] attribute or manual Span::enter)
- Tower middleware missing request/response tracing layers
- unsafe blocks without error recording or panic instrumentation
- Error propagation (? operator) without span error recording
- Missing metrics exposure via prometheus-client or opentelemetry-rust
- Tokio async tasks spawned without span context (.instrument())
- Channel (mpsc/crossbeam) operations without trace propagation
- Missing structured logging (tracing::info! vs println!)

${context.ragContext ? `Knowledge base context:\n${context.ragContext}` : ''}

If a finding involves unsafe code or memory concerns, add "D-security" to cross_domain_hints.
If a finding involves performance patterns, add "D-performance" to cross_domain_hints.`;
  }

  getUserPrompt(files: ClassifiedFile[], _context: AgentContext): string {
    return `Analyze these Rust files for observability gaps:\n\n${this.formatFiles(files)}`;
  }
}

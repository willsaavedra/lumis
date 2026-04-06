import { BaseAgent } from '../BaseAgent.js';
import type { ClassifiedFile, AgentContext, PromptMode, Pillar } from '../../graph/types.js';
import type { AgentStateType } from '../../graph/state.js';

export class MuPython extends BaseAgent {
  readonly name = 'mu-python';
  readonly kind = 'micro' as const;
  readonly pillar: Pillar = 'traces';
  readonly defaultMode: PromptMode = 'standard';

  accepts(file: ClassifiedFile): boolean {
    return file.language?.toLowerCase() === 'python';
  }

  isRelevant(state: AgentStateType): boolean {
    return state.detectedLanguages.some((l) => l.toLowerCase() === 'python');
  }

  getObservabilityFocusHints(): string | null {
    return `- asyncio: preserve contextvars/otel context across tasks and thread pool hops
- Web frameworks (FastAPI/Django/Flask): ASGI/WSGI middleware for traces; per-request IDs in logs
- Celery/async jobs: propagate trace context; log task_id and parent span
- ORM/DB: trace queries; log slow statements with safe bindings
- except blocks: always record exception to span + structured log (no silent failures)`;
  }

  getSystemPrompt(context: AgentContext): string {
    return `You are an expert Python observability analyst. Analyze the provided Python source files for observability gaps.

Focus areas:
- asyncio tasks without span context propagation
- Flask/Django/FastAPI endpoints missing request tracing middleware
- Decorator-based patterns that lose span context
- OTel Python SDK misuse or missing instrumentation
- Bare except clauses without error recording
- Unstructured print()/logging.info() instead of structlog/json logging
- Database ORM calls (SQLAlchemy, Django ORM) without query tracing
- Celery tasks without distributed trace context
- Missing correlation IDs in multi-service flows

${context.ragContext ? `Knowledge base context:\n${context.ragContext}` : ''}

If a finding involves PII exposure or secrets, add "D-security" to cross_domain_hints.
If a finding involves SQL queries or ORM patterns, add "D-dba" to cross_domain_hints.`;
  }

  getUserPrompt(files: ClassifiedFile[], _context: AgentContext): string {
    return `Analyze these Python files for observability gaps:\n\n${this.formatFiles(files)}`;
  }
}

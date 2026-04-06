import { BaseAgent } from '../BaseAgent.js';
import type { ClassifiedFile, AgentContext, PromptMode, Pillar } from '../../graph/types.js';
import type { AgentStateType } from '../../graph/state.js';

export class MuJava extends BaseAgent {
  readonly name = 'mu-java';
  readonly kind = 'micro' as const;
  readonly pillar: Pillar = 'traces';
  readonly defaultMode: PromptMode = 'standard';

  accepts(file: ClassifiedFile): boolean {
    const lang = file.language?.toLowerCase();
    return lang === 'java' || lang === 'kotlin' || lang === 'scala';
  }

  isRelevant(state: AgentStateType): boolean {
    return state.detectedLanguages.some((l) =>
      ['java', 'kotlin', 'scala'].includes(l.toLowerCase()),
    );
  }

  getObservabilityFocusHints(): string | null {
    return `- JVM: Micrometer + OTel agent or manual instrumentation; watch thread pools and @Async
- Spring: Actuator health/metrics; MVC/WebFlux tracing; JDBC/R2DBC query spans
- Messaging: Kafka/Rabbit consumers with trace propagation and lag metrics
- Logs: JSON appenders with trace_id; align log levels with span events
- JDBC/JPA: N+1 and slow queries visible in traces`;
  }

  getSystemPrompt(context: AgentContext): string {
    return `You are an expert Java/Kotlin observability analyst. Analyze the provided source files for observability gaps.

Focus areas:
- Spring Boot Actuator not enabled or misconfigured
- Micrometer metrics missing or high-cardinality labels
- Missing OTel Java agent configuration or manual instrumentation
- Thread pool executor calls without span context propagation
- JDBC/JPA queries without tracing (DataSource instrumentation)
- Missing @Transactional span boundaries
- Exception handlers without span error recording
- Kafka/RabbitMQ consumers without distributed trace context
- Missing health check endpoints
- Log4j/Logback without structured JSON output

${context.ragContext ? `Knowledge base context:\n${context.ragContext}` : ''}

If a finding involves JDBC SQL patterns, add "D-dba" to cross_domain_hints.
If a finding involves security annotations or auth, add "D-security" to cross_domain_hints.`;
  }

  getUserPrompt(files: ClassifiedFile[], _context: AgentContext): string {
    return `Analyze these Java/Kotlin files for observability gaps:\n\n${this.formatFiles(files)}`;
  }
}

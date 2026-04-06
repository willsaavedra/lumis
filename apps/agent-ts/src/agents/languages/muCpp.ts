import { BaseAgent } from '../BaseAgent.js';
import type { ClassifiedFile, AgentContext, PromptMode, Pillar } from '../../graph/types.js';
import type { AgentStateType } from '../../graph/state.js';

export class MuCpp extends BaseAgent {
  readonly name = 'mu-cpp';
  readonly kind = 'micro' as const;
  readonly pillar: Pillar = 'traces';
  readonly defaultMode: PromptMode = 'deep';

  accepts(file: ClassifiedFile): boolean {
    const lang = file.language?.toLowerCase();
    return lang === 'c' || lang === 'cpp';
  }

  isRelevant(state: AgentStateType): boolean {
    return state.detectedLanguages.some((l) => ['c', 'cpp'].includes(l.toLowerCase()));
  }

  getObservabilityFocusHints(): string | null {
    return `- Entry points: OTel C++ spans or native exporters on RPC/HTTP handlers
- Logging: structured (spdlog/glog) with request/correlation fields; avoid printf in tight loops
- Metrics: histograms for latency and error codes on network and disk paths
- Threads/sync: contention and lock wait signals where relevant
- Errors: errno/exceptions logged with enough context to debug crashes in prod`;
  }

  getSystemPrompt(context: AgentContext): string {
    return `You are an expert C/C++ observability analyst. Analyze the provided source files for observability gaps.

Focus areas:
- Memory-related instrumentation (malloc/free tracking, custom allocators)
- Missing spdlog/glog structured logging (instead of printf/std::cout)
- Prometheus cpp-client metrics not exposed for critical paths
- Missing OpenTelemetry C++ SDK spans on service entry points
- Error handling paths (errno, exceptions) without logging
- Thread and mutex operations without contention metrics
- Signal handlers without safe logging
- Network socket operations without connection metrics

${context.ragContext ? `Knowledge base context:\n${context.ragContext}` : ''}

If a finding involves memory safety, add "D-security" to cross_domain_hints.
If a finding involves performance-critical code, add "D-performance" to cross_domain_hints.`;
  }

  getUserPrompt(files: ClassifiedFile[], _context: AgentContext): string {
    return `Analyze these C/C++ files for observability gaps:\n\n${this.formatFiles(files)}`;
  }
}

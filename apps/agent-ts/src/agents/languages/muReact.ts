import { BaseAgent } from '../BaseAgent.js';
import type { ClassifiedFile, AgentContext, PromptMode, Pillar } from '../../graph/types.js';
import type { AgentStateType } from '../../graph/state.js';

export class MuReact extends BaseAgent {
  readonly name = 'mu-react';
  readonly kind = 'micro' as const;
  readonly pillar: Pillar = 'metrics';
  readonly defaultMode: PromptMode = 'standard';

  accepts(file: ClassifiedFile): boolean {
    return (
      file.path.endsWith('.tsx') ||
      file.path.endsWith('.jsx') ||
      file.path.endsWith('.vue') ||
      file.path.includes('next.config') ||
      file.path.includes('vite.config')
    );
  }

  isRelevant(state: AgentStateType): boolean {
    return state.classifiedFiles.some(
      (f) =>
        f.path.endsWith('.tsx') ||
        f.path.endsWith('.jsx') ||
        f.path.endsWith('.vue'),
    );
  }

  getObservabilityFocusHints(): string | null {
    return `- Web Vitals (LCP, INP, CLS) and route-level performance budgets
- Client errors: boundaries + reporting to RUM; source maps and release tags
- fetch/GraphQL: latency and status metrics; tie to backend trace_id when propagated
- Avoid PII in client logs/telemetry; sample client traces aggressively`;
  }

  getSystemPrompt(context: AgentContext): string {
    return `You are an expert frontend observability analyst for React/Vue/Angular applications.

Focus areas:
- Missing Web Vitals collection (LCP, FID, CLS, INP)
- Error boundaries not implemented or missing error reporting
- Network request calls (fetch/axios) without tracing or error handling
- Missing RUM (Real User Monitoring) integration
- Console.error/warn without structured error reporting
- Missing performance marks/measures for critical user flows
- Lazy-loaded components without loading state metrics
- Missing client-side error tracking (Sentry, Datadog RUM, etc.)
- GraphQL/REST calls without request timing metrics

${context.ragContext ? `Knowledge base context:\n${context.ragContext}` : ''}

If a finding involves user data handling in the browser, add "D-security" to cross_domain_hints.
If a finding involves API call patterns, add "D-api-contracts" to cross_domain_hints.`;
  }

  getUserPrompt(files: ClassifiedFile[], _context: AgentContext): string {
    return `Analyze these frontend files for observability gaps:\n\n${this.formatFiles(files)}`;
  }
}

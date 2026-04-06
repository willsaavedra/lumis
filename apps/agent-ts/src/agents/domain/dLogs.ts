import { DomainAgent } from '../DomainAgent.js';
import type { ClassifiedFile, AgentContext, CrossDomainReferral, PromptMode, Pillar } from '../../graph/types.js';
import type { AgentStateType } from '../../graph/state.js';

export class DLogs extends DomainAgent {
  readonly name = 'D-logs';
  readonly pillar: Pillar = 'logs';
  readonly defaultMode: PromptMode = 'standard';

  accepts(file: ClassifiedFile): boolean {
    if (!file.content) return false;
    const lower = file.content.toLowerCase();
    return (
      lower.includes('logger') ||
      lower.includes('log.') ||
      lower.includes('console.') ||
      lower.includes('logging') ||
      lower.includes('slog') ||
      lower.includes('pino') ||
      lower.includes('winston') ||
      lower.includes('structlog') ||
      lower.includes('zerolog') ||
      lower.includes('zap.')
    );
  }

  isRelevant(state: AgentStateType): boolean {
    return state.classifiedFiles.some((f) => this.accepts(f));
  }

  getSystemPrompt(context: AgentContext): string {
    return `You are a logging specialist reviewing code for log quality and structured logging gaps.

Focus areas:
- Unstructured log messages (string concatenation/interpolation instead of structured fields)
- Missing correlation IDs / trace context in logs
- Inappropriate log levels (debug info in production, errors for non-errors)
- Sensitive data in log output (PII, tokens, passwords)
- Missing error context in log messages (stack traces, error codes)
- Inconsistent log formatting across the codebase
- Missing request/response logging on API endpoints
- Log messages without actionable context
- Excessive logging causing noise (log spam in loops)
- Missing log rotation/retention configuration

${context.ragContext ? `Knowledge base context:\n${context.ragContext}` : ''}

If a finding involves PII/secrets in logs, add "D-security" to cross_domain_hints.`;
  }

  getUserPrompt(files: ClassifiedFile[], _context: AgentContext): string {
    return `Review these files for logging issues:\n\n${this.formatFiles(files)}`;
  }

  getEnrichmentSystemPrompt(_context: AgentContext): string {
    return `You are a logging specialist. Other agents have flagged findings related to logging quality.
Assess whether the logging concern is valid and suggest specific structured logging improvements.`;
  }

  getEnrichmentUserPrompt(referrals: CrossDomainReferral[], _context: AgentContext): string {
    const items = referrals.map(
      (r, i) => `### Referral ${i} (finding_index: ${r.findingIndex})
Reason: ${r.reason}
Code: ${r.contextSnippet}`,
    );
    return `Review these logging referrals:\n\n${items.join('\n\n')}`;
  }
}

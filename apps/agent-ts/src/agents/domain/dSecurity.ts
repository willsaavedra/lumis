import { DomainAgent } from '../DomainAgent.js';
import type { ClassifiedFile, AgentContext, CrossDomainReferral, PromptMode, Pillar } from '../../graph/types.js';
import type { AgentStateType } from '../../graph/state.js';

export class DSecurity extends DomainAgent {
  readonly name = 'D-security';
  readonly pillar: Pillar = 'security';
  readonly defaultMode: PromptMode = 'deep';

  accepts(file: ClassifiedFile): boolean {
    if (!file.content) return false;
    const lower = file.content.toLowerCase();
    const p = file.path.toLowerCase();
    return (
      lower.includes('password') ||
      lower.includes('secret') ||
      lower.includes('token') ||
      lower.includes('api_key') ||
      lower.includes('apikey') ||
      lower.includes('auth') ||
      lower.includes('credential') ||
      lower.includes('encrypt') ||
      lower.includes('hash') ||
      lower.includes('cors') ||
      lower.includes('sanitiz') ||
      lower.includes('injection') ||
      lower.includes('csrf') ||
      lower.includes('cookie') ||
      lower.includes('session') ||
      p.includes('auth') ||
      p.includes('security') ||
      p.includes('middleware') ||
      p.includes('.env') ||
      p.includes('config')
    );
  }

  isRelevant(_state: AgentStateType): boolean {
    return true;
  }

  getSystemPrompt(context: AgentContext): string {
    return `You are a security specialist reviewing code for security-related observability gaps.

Focus areas:
- PII/secrets exposed in log output (emails, tokens, passwords, API keys)
- SQL injection vulnerabilities
- Authentication/authorization gaps (missing auth checks, token validation)
- OWASP Top 10 issues visible in code
- Hardcoded credentials or secrets
- Missing input validation/sanitization
- Insecure cryptographic practices
- Missing audit logging for sensitive operations
- CORS misconfiguration
- Dependency vulnerabilities patterns

${context.ragContext ? `Knowledge base context:\n${context.ragContext}` : ''}`;
  }

  getUserPrompt(files: ClassifiedFile[], _context: AgentContext): string {
    return `Review these files for security issues:\n\n${this.formatFiles(files)}`;
  }

  getEnrichmentSystemPrompt(_context: AgentContext): string {
    return `You are a security specialist. Other agents have flagged findings that may have security implications.
Review each referral and determine:
- "enrich": The finding has genuine security implications. Enhance the description with security context, adjust severity if needed.
- "suppress": This is a false positive from a security perspective.
- "noop": The security aspect is minor/already covered.

Be precise about GDPR, OWASP, and compliance implications.`;
  }

  getEnrichmentUserPrompt(referrals: CrossDomainReferral[], _context: AgentContext): string {
    const items = referrals.map(
      (r, i) => `### Referral ${i} (finding_index: ${r.findingIndex})
Reason: ${r.reason}
Code: ${r.contextSnippet}`,
    );
    return `Review these security referrals:\n\n${items.join('\n\n')}`;
  }
}

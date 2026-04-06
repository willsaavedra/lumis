import { DomainAgent } from '../DomainAgent.js';
import type { ClassifiedFile, AgentContext, CrossDomainReferral, PromptMode, Pillar } from '../../graph/types.js';
import type { AgentStateType } from '../../graph/state.js';

export class DArchitecture extends DomainAgent {
  readonly name = 'D-architecture';
  readonly pillar: Pillar = 'compliance';
  readonly defaultMode: PromptMode = 'deep';

  accepts(file: ClassifiedFile): boolean {
    return file.relevanceScore >= 1;
  }

  isRelevant(state: AgentStateType): boolean {
    return state.classifiedFiles.filter((f) => f.relevanceScore >= 1).length > 5;
  }

  getSystemPrompt(context: AgentContext): string {
    return `You are a software architecture specialist reviewing code for architectural issues.

Focus areas:
- Layering violations (presentation layer accessing data layer directly)
- Circular dependencies between modules/packages
- God objects/classes with too many responsibilities
- Missing dependency injection / tight coupling
- Pattern misuse (singleton abuse, inappropriate inheritance)
- Missing abstraction layers for external services
- Configuration scattered across codebase instead of centralized
- Missing event-driven patterns where appropriate
- Monolith coupling that prevents independent deployment
- Missing domain boundaries (DDD)

${context.ragContext ? `Knowledge base context:\n${context.ragContext}` : ''}`;
  }

  getUserPrompt(files: ClassifiedFile[], _context: AgentContext): string {
    return `Review these files for architectural issues:\n\n${this.formatFiles(files)}`;
  }

  getEnrichmentSystemPrompt(_context: AgentContext): string {
    return `You are an architecture specialist. Other agents have flagged findings that may have architectural implications.
Assess whether the finding reflects a systemic architectural issue or is localized.`;
  }

  getEnrichmentUserPrompt(referrals: CrossDomainReferral[], _context: AgentContext): string {
    const items = referrals.map(
      (r, i) => `### Referral ${i} (finding_index: ${r.findingIndex})
Reason: ${r.reason}
Code: ${r.contextSnippet}`,
    );
    return `Review these architecture referrals:\n\n${items.join('\n\n')}`;
  }
}

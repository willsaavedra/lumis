import { DomainAgent } from '../DomainAgent.js';
import type { ClassifiedFile, AgentContext, CrossDomainReferral, PromptMode, Pillar } from '../../graph/types.js';
import type { AgentStateType } from '../../graph/state.js';

export class DDba extends DomainAgent {
  readonly name = 'D-dba';
  readonly pillar: Pillar = 'efficiency';
  readonly defaultMode: PromptMode = 'deep';

  accepts(file: ClassifiedFile): boolean {
    const p = file.path.toLowerCase();
    return (
      p.endsWith('.sql') ||
      p.includes('migration') ||
      p.includes('model') ||
      p.includes('repository') ||
      p.includes('dao') ||
      (file.content?.includes('SELECT') ?? false) ||
      (file.content?.includes('query') ?? false)
    );
  }

  isRelevant(state: AgentStateType): boolean {
    return state.classifiedFiles.some(
      (f) =>
        f.path.endsWith('.sql') ||
        f.path.includes('migration') ||
        f.detectedArtifacts?.includes('database') ||
        (f.content?.match(/\b(SELECT|INSERT|UPDATE|DELETE|CREATE TABLE)\b/i) !== null),
    );
  }

  getSystemPrompt(context: AgentContext): string {
    return `You are a database specialist reviewing code for database-related issues.

Focus areas:
- N+1 query patterns (ORM lazy loading in loops)
- Missing database connection pooling configuration
- Migrations without rollback/down functions
- Missing indexes on frequently queried columns
- Raw SQL without parameterized queries (SQL injection risk)
- Missing transaction boundaries for multi-step operations
- Connection leak patterns (open without close/defer)
- Missing query timeout configuration
- Large result sets without pagination/LIMIT
- Missing database-level instrumentation (query tracing)

${context.ragContext ? `Knowledge base context:\n${context.ragContext}` : ''}`;
  }

  getUserPrompt(files: ClassifiedFile[], _context: AgentContext): string {
    return `Review these files for database issues:\n\n${this.formatFiles(files)}`;
  }

  getEnrichmentSystemPrompt(_context: AgentContext): string {
    return `You are a DBA specialist. Other agents have flagged findings with database implications.
Review each referral and determine if it has real database performance/correctness impact.
For enrichment, add specifics about query optimization, indexing, or connection management.`;
  }

  getEnrichmentUserPrompt(referrals: CrossDomainReferral[], _context: AgentContext): string {
    const items = referrals.map(
      (r, i) => `### Referral ${i} (finding_index: ${r.findingIndex})
Reason: ${r.reason}
Code: ${r.contextSnippet}`,
    );
    return `Review these database referrals:\n\n${items.join('\n\n')}`;
  }
}

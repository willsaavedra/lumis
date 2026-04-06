import { DomainAgent } from '../DomainAgent.js';
import type { ClassifiedFile, AgentContext, CrossDomainReferral, PromptMode, Pillar } from '../../graph/types.js';
import type { AgentStateType } from '../../graph/state.js';

export class DApiContracts extends DomainAgent {
  readonly name = 'D-api-contracts';
  readonly pillar: Pillar = 'compliance';
  readonly defaultMode: PromptMode = 'standard';

  accepts(file: ClassifiedFile): boolean {
    const p = file.path.toLowerCase();
    return (
      p.includes('route') ||
      p.includes('controller') ||
      p.includes('handler') ||
      p.includes('endpoint') ||
      p.endsWith('.proto') ||
      p.includes('openapi') ||
      p.includes('swagger') ||
      p.includes('schema') ||
      (file.content?.includes('router') ?? false)
    );
  }

  isRelevant(state: AgentStateType): boolean {
    return state.classifiedFiles.some(
      (f) =>
        f.detectedArtifacts?.includes('openapi') ||
        f.detectedArtifacts?.includes('protobuf') ||
        f.path.includes('route') ||
        f.path.includes('controller') ||
        f.path.includes('handler'),
    );
  }

  getSystemPrompt(context: AgentContext): string {
    return `You are an API contracts specialist reviewing code for API design and contract issues.

Focus areas:
- Breaking API changes (removed fields, changed types) without versioning
- Missing request/response validation (zod, joi, pydantic, protobuf)
- Inconsistent error response formats across endpoints
- Missing OpenAPI/Swagger documentation drift from implementation
- API endpoints without rate limiting
- Missing content-type negotiation
- Inconsistent naming conventions (camelCase vs snake_case)
- Missing pagination on list endpoints
- GraphQL N+1 resolver patterns
- Missing deprecation notices on old endpoints

${context.ragContext ? `Knowledge base context:\n${context.ragContext}` : ''}`;
  }

  getUserPrompt(files: ClassifiedFile[], _context: AgentContext): string {
    return `Review these files for API contract issues:\n\n${this.formatFiles(files)}`;
  }

  getEnrichmentSystemPrompt(_context: AgentContext): string {
    return `You are an API contracts specialist. Other agents have flagged findings with API contract implications.
Review each referral for breaking changes, validation gaps, or versioning issues.`;
  }

  getEnrichmentUserPrompt(referrals: CrossDomainReferral[], _context: AgentContext): string {
    const items = referrals.map(
      (r, i) => `### Referral ${i} (finding_index: ${r.findingIndex})
Reason: ${r.reason}
Code: ${r.contextSnippet}`,
    );
    return `Review these API contract referrals:\n\n${items.join('\n\n')}`;
  }
}

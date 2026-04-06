import { DomainAgent } from '../DomainAgent.js';
import type { ClassifiedFile, AgentContext, CrossDomainReferral, PromptMode, Pillar } from '../../graph/types.js';
import type { AgentStateType } from '../../graph/state.js';

export class DTesting extends DomainAgent {
  readonly name = 'D-testing';
  readonly pillar: Pillar = 'metrics';
  readonly defaultMode: PromptMode = 'standard';

  accepts(file: ClassifiedFile): boolean {
    const p = file.path.toLowerCase();
    return (
      p.includes('test') ||
      p.includes('spec') ||
      p.includes('__tests__') ||
      p.includes('fixture') ||
      p.includes('mock') ||
      p.includes('jest.config') ||
      p.includes('vitest') ||
      p.includes('pytest') ||
      p.includes('_test.go')
    );
  }

  isRelevant(state: AgentStateType): boolean {
    return state.detectedArtifacts.includes('testing') ||
      state.classifiedFiles.some((f) =>
        f.path.includes('test') || f.path.includes('spec'),
      );
  }

  getSystemPrompt(context: AgentContext): string {
    return `You are a testing specialist reviewing code for test quality and coverage issues.

Focus areas:
- Critical paths without corresponding test coverage
- Flaky test indicators (timing dependencies, shared state, network calls)
- Mocking anti-patterns (too many mocks, testing implementation not behavior)
- Missing integration/e2e tests for API endpoints
- Test assertions that are too broad or meaningless
- Missing error case testing (unhappy paths)
- Test fixtures with hardcoded/stale data
- Missing performance/load test configurations
- Tests that bypass important middleware or validation

${context.ragContext ? `Knowledge base context:\n${context.ragContext}` : ''}`;
  }

  getUserPrompt(files: ClassifiedFile[], _context: AgentContext): string {
    return `Review these files for testing issues:\n\n${this.formatFiles(files)}`;
  }

  getEnrichmentSystemPrompt(_context: AgentContext): string {
    return `You are a testing specialist. Other agents have flagged findings that may relate to test coverage gaps.
Review each referral and assess whether the flagged code path has adequate test coverage.`;
  }

  getEnrichmentUserPrompt(referrals: CrossDomainReferral[], _context: AgentContext): string {
    const items = referrals.map(
      (r, i) => `### Referral ${i} (finding_index: ${r.findingIndex})
Reason: ${r.reason}
Code: ${r.contextSnippet}`,
    );
    return `Review these testing referrals:\n\n${items.join('\n\n')}`;
  }
}

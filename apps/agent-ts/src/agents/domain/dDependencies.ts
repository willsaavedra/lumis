import { DomainAgent } from '../DomainAgent.js';
import type { ClassifiedFile, AgentContext, CrossDomainReferral, PromptMode, Pillar } from '../../graph/types.js';
import type { AgentStateType } from '../../graph/state.js';

export class DDependencies extends DomainAgent {
  readonly name = 'D-dependencies';
  readonly pillar: Pillar = 'security';
  readonly defaultMode: PromptMode = 'fast';

  accepts(file: ClassifiedFile): boolean {
    const p = file.path.toLowerCase();
    return (
      p.includes('package.json') ||
      p.includes('package-lock.json') ||
      p.includes('go.mod') ||
      p.includes('go.sum') ||
      p.includes('requirements.txt') ||
      p.includes('pyproject.toml') ||
      p.includes('cargo.toml') ||
      p.includes('pom.xml') ||
      p.includes('build.gradle') ||
      p.includes('gemfile') ||
      p.includes('composer.json')
    );
  }

  isRelevant(state: AgentStateType): boolean {
    return state.classifiedFiles.some((f) => this.accepts(f));
  }

  getSystemPrompt(context: AgentContext): string {
    return `You are a dependency management specialist reviewing dependency files for risks.

Focus areas:
- Known CVE patterns in common packages (based on your training data)
- Significantly outdated major versions of critical dependencies
- License compatibility risks (GPL in MIT projects, etc.)
- Phantom dependencies (used but not declared)
- Overly broad version ranges that may pull breaking changes
- Duplicate dependencies at different versions
- Dev dependencies shipped in production builds
- Missing lockfile
- Unnecessary large dependencies where lighter alternatives exist

${context.ragContext ? `Knowledge base context:\n${context.ragContext}` : ''}

Note: You cannot check live CVE databases. Flag patterns you recognize from training data and suggest the user verify with tools like npm audit, govulncheck, etc.`;
  }

  getUserPrompt(files: ClassifiedFile[], _context: AgentContext): string {
    return `Review these dependency files for risks:\n\n${this.formatFiles(files)}`;
  }

  getEnrichmentSystemPrompt(_context: AgentContext): string {
    return `You are a dependency specialist. Other agents have flagged findings related to dependencies.
Assess whether the dependency concern is valid and suggest specific remediation.`;
  }

  getEnrichmentUserPrompt(referrals: CrossDomainReferral[], _context: AgentContext): string {
    const items = referrals.map(
      (r, i) => `### Referral ${i} (finding_index: ${r.findingIndex})
Reason: ${r.reason}
Code: ${r.contextSnippet}`,
    );
    return `Review these dependency referrals:\n\n${items.join('\n\n')}`;
  }
}

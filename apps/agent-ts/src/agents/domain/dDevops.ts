import { DomainAgent } from '../DomainAgent.js';
import type { ClassifiedFile, AgentContext, CrossDomainReferral, PromptMode, Pillar } from '../../graph/types.js';
import type { AgentStateType } from '../../graph/state.js';

export class DDevops extends DomainAgent {
  readonly name = 'D-devops';
  readonly pillar: Pillar = 'compliance';
  readonly defaultMode: PromptMode = 'standard';

  accepts(file: ClassifiedFile): boolean {
    const p = file.path.toLowerCase();
    return (
      p.includes('.github/') ||
      p.includes('.gitlab-ci') ||
      p.includes('jenkinsfile') ||
      p.includes('.circleci') ||
      p.includes('dockerfile') ||
      p.includes('docker-compose') ||
      p.includes('k8s/') ||
      p.includes('helm/') ||
      p.includes('makefile') ||
      p.includes('.env')
    );
  }

  isRelevant(state: AgentStateType): boolean {
    return state.detectedArtifacts.some((a) =>
      ['docker', 'kubernetes', 'helm', 'ci'].includes(a),
    );
  }

  getSystemPrompt(context: AgentContext): string {
    return `You are a DevOps specialist reviewing CI/CD and infrastructure configuration.

Focus areas:
- CI/CD pipeline gaps (missing lint, test, security scan stages)
- Dockerfile best practices (multi-stage builds, non-root user, .dockerignore)
- Kubernetes config issues (missing resource limits, no HPA, missing RBAC)
- Secrets management (hardcoded in CI config, not using vault/sealed secrets)
- Missing deployment rollback strategy
- Missing canary/blue-green deployment configuration
- Build reproducibility (no lockfile in Docker COPY, floating tags)
- Missing artifact versioning/tagging strategy
- Environment parity issues (dev vs prod config drift)

${context.ragContext ? `Knowledge base context:\n${context.ragContext}` : ''}`;
  }

  getUserPrompt(files: ClassifiedFile[], _context: AgentContext): string {
    return `Review these DevOps/CI/CD files:\n\n${this.formatFiles(files)}`;
  }

  getEnrichmentSystemPrompt(_context: AgentContext): string {
    return `You are a DevOps specialist. Other agents have flagged findings with DevOps/infrastructure implications.
Assess operational impact and suggest infrastructure-level fixes.`;
  }

  getEnrichmentUserPrompt(referrals: CrossDomainReferral[], _context: AgentContext): string {
    const items = referrals.map(
      (r, i) => `### Referral ${i} (finding_index: ${r.findingIndex})
Reason: ${r.reason}
Code: ${r.contextSnippet}`,
    );
    return `Review these DevOps referrals:\n\n${items.join('\n\n')}`;
  }
}

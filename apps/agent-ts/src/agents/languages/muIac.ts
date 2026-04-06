import { BaseAgent } from '../BaseAgent.js';
import type { ClassifiedFile, AgentContext, PromptMode, Pillar } from '../../graph/types.js';
import type { AgentStateType } from '../../graph/state.js';

export class MuIac extends BaseAgent {
  readonly name = 'mu-iac';
  readonly kind = 'micro' as const;
  readonly pillar: Pillar = 'iac';
  readonly defaultMode: PromptMode = 'standard';

  accepts(file: ClassifiedFile): boolean {
    const p = file.path.toLowerCase();
    return (
      p.endsWith('.tf') ||
      p.endsWith('.tfvars') ||
      p.includes('dockerfile') ||
      p.includes('docker-compose') ||
      p.includes('chart.yaml') ||
      p.includes('values.yaml') ||
      p.includes('k8s/') ||
      p.includes('helm/') ||
      p.endsWith('.hcl')
    );
  }

  isRelevant(state: AgentStateType): boolean {
    return state.detectedArtifacts.some((a) =>
      ['docker', 'kubernetes', 'helm', 'terraform'].includes(a),
    );
  }

  getObservabilityFocusHints(): string | null {
    return `- Kubernetes: probes, resource requests/limits, HPA signals, PodMonitoring/ServiceMonitor
- Exporters/sidecars: Prometheus scrape paths; log shipping selectors
- Terraform/Helm: variables for scrape configs and alert routes per env
- Docker: healthcheck, non-root, logging driver; compose service dependencies observable`;
  }

  getSystemPrompt(context: AgentContext): string {
    return `You are an expert IaC observability analyst. Analyze infrastructure-as-code files for observability gaps.

Focus areas:
- Terraform modules missing monitoring agent/exporter resources
- Kubernetes deployments without liveness/readiness probes
- Containers without resource limits (CPU/memory)
- Missing Prometheus ServiceMonitor or PodMonitor resources
- Helm charts without configurable monitoring values
- Dockerfiles running as root or missing health checks
- Missing log driver configuration in Docker Compose
- Kubernetes missing PodDisruptionBudget
- No alerting rules (PrometheusRule) defined for services
- Missing NetworkPolicy for service isolation

${context.ragContext ? `Knowledge base context:\n${context.ragContext}` : ''}

If a finding involves Dockerfile security, add "D-security" to cross_domain_hints.
If a finding involves resource limits/performance, add "D-performance" to cross_domain_hints.
If a finding involves CI/CD pipeline config, add "D-devops" to cross_domain_hints.`;
  }

  getUserPrompt(files: ClassifiedFile[], _context: AgentContext): string {
    return `Analyze these IaC files for observability gaps:\n\n${this.formatFiles(files)}`;
  }
}

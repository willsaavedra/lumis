import type { AgentStateType } from '../graph/state.js';
import { agentRegistry } from '../agents/registry.js';
import { publishProgress } from '../utils/progress.js';
import { logger } from '../utils/logger.js';

const LANG_TO_AGENT: Record<string, string> = {
  typescript: 'mu-typescript',
  javascript: 'mu-typescript',
  go: 'mu-go',
  python: 'mu-python',
  rust: 'mu-rust',
  java: 'mu-java',
  kotlin: 'mu-java',
  scala: 'mu-java',
  c: 'mu-cpp',
  cpp: 'mu-cpp',
};

function hasReactOrFrontend(files: AgentStateType['classifiedFiles']): boolean {
  return files.some(
    (f) =>
      f.path.endsWith('.tsx') ||
      f.path.endsWith('.jsx') ||
      f.path.includes('next.config') ||
      f.path.includes('vite.config'),
  );
}

function hasIacFiles(files: AgentStateType['classifiedFiles']): boolean {
  return files.some(
    (f) =>
      f.path.endsWith('.tf') ||
      f.path.includes('Dockerfile') ||
      f.path.includes('docker-compose') ||
      f.path.includes('Chart.yaml') ||
      f.path.includes('k8s/'),
  );
}

// Only the observability domain agent is active for now.
// Other domain agents (security, dba, performance, etc.) are available
// in the codebase but disabled to keep analysis fast and cost-effective.
// Micro-agents (mu-*) supply language/stack observability priorities that are aggregated
// into `microAgentObservabilityHints` for D-observability (see `buildMicroAgentObservabilityHints`).
const ACTIVE_DOMAIN_AGENTS = ['D-observability'];

export function dispatcherNode(
  state: AgentStateType,
): Partial<AgentStateType> {
  const { request, classifiedFiles, detectedLanguages } = state;
  const log = logger.child({ jobId: request.jobId, node: 'dispatcher' });
  const start = Date.now();
  log.info({ event: 'node_started', node: 'dispatcher' });

  const activeAgents = new Set<string>();

  // ── Micro-agents desativados ──────────────────────────────────────────
  // Os hints de observabilidade por linguagem continuam disponíveis via
  // `getObservabilityFocusHints()` e são agregados em
  // `buildMicroAgentObservabilityHints` no parallelPass, mesmo sem os
  // micro-agents rodarem análise própria.  Quando reativar, descomentar:
  //
  // for (const lang of detectedLanguages) {
  //   const agentName = LANG_TO_AGENT[lang.toLowerCase()];
  //   if (agentName) activeAgents.add(agentName);
  // }
  // if (hasReactOrFrontend(classifiedFiles)) activeAgents.add('mu-react');
  // if (hasIacFiles(classifiedFiles)) activeAgents.add('mu-iac');
  // ─────────────────────────────────────────────────────────────────────

  // Activate domain agents
  for (const domainName of ACTIVE_DOMAIN_AGENTS) {
    const agent = agentRegistry.get(domainName);
    if (agent?.isRelevant(state)) {
      activeAgents.add(domainName);
    }
  }

  const agents = [...activeAgents];
  const durationMs = Date.now() - start;
  log.info({
    event: 'node_completed',
    node: 'dispatcher',
    durationMs,
    activeAgents: agents,
    activeCount: agents.length,
  });

  publishProgress(
    request.jobId, 'dispatching', 25,
    `Activated ${agents.length} agents: ${agents.join(', ')}`,
  );

  return {
    activeAgents: agents,
    stage: 'dispatching',
    progressPct: 25,
  };
}

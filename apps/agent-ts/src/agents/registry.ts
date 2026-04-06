import type { BaseAgent } from './BaseAgent.js';

import { MuTypescript } from './languages/muTypescript.js';
import { MuGo } from './languages/muGo.js';
import { MuPython } from './languages/muPython.js';
import { MuRust } from './languages/muRust.js';
import { MuJava } from './languages/muJava.js';
import { MuCpp } from './languages/muCpp.js';
import { MuReact } from './languages/muReact.js';
import { MuIac } from './languages/muIac.js';

import { DObservability } from './domain/dObservability.js';

export const agentRegistry = new Map<string, BaseAgent>();

const microAgents: BaseAgent[] = [
  new MuTypescript(),
  new MuGo(),
  new MuPython(),
  new MuRust(),
  new MuJava(),
  new MuCpp(),
  new MuReact(),
  new MuIac(),
];

const domainAgents: BaseAgent[] = [
  new DObservability(),
];

for (const agent of [...microAgents, ...domainAgents]) {
  agentRegistry.set(agent.name, agent);
}

export function getMicroAgents(): BaseAgent[] {
  return microAgents;
}

export function getDomainAgents(): BaseAgent[] {
  return domainAgents;
}

/**
 * Junta os focos de observabilidade dos micro-agents **relevantes** para as linguagens
 * e artifacts detectados — independente de estarem em `activeAgents`.
 */
export function buildMicroAgentObservabilityHints(
  detectedLanguages: string[],
  detectedArtifacts: string[],
  files: { path: string }[],
): string | null {
  const candidateNames = new Set<string>();

  const LANG_MAP: Record<string, string> = {
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

  for (const lang of detectedLanguages) {
    const name = LANG_MAP[lang.toLowerCase()];
    if (name) candidateNames.add(name);
  }

  if (files.some((f) => /\.(tsx|jsx)$/.test(f.path) || /next\.config|vite\.config/.test(f.path))) {
    candidateNames.add('mu-react');
  }

  if (detectedArtifacts.some((a) => ['docker', 'kubernetes', 'helm', 'terraform'].includes(a))) {
    candidateNames.add('mu-iac');
  }

  const parts: string[] = [];
  for (const name of candidateNames) {
    const agent = agentRegistry.get(name);
    if (!agent || agent.kind !== 'micro') continue;
    const h = agent.getObservabilityFocusHints();
    if (h?.trim()) parts.push(`### ${agent.name}\n${h.trim()}`);
  }
  return parts.length > 0 ? parts.join('\n\n') : null;
}

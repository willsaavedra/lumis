import { v4 as uuidv4 } from 'uuid';
import type { AgentStateType } from '../graph/state.js';
import type { Finding } from '../graph/types.js';
import { publishProgress } from '../utils/progress.js';
import { logger } from '../utils/logger.js';

const EFFICIENCY_PATTERNS = [
  {
    pattern: /log\.(?:info|debug|warn)\(.*\+.*\)/gi,
    title: 'String concatenation in log call',
    pillar: 'logs' as const,
    dimension: 'snr' as const,
    severity: 'warning' as const,
    description: 'Using string concatenation in log calls may cause unnecessary allocation even when log level is disabled.',
    costHint: 'Reduces CPU overhead by avoiding unnecessary string operations.',
  },
  {
    pattern: /\.setAttributes?\(\{[^}]*\b(user_?id|email|ip[_.]?addr|name)\b/gi,
    title: 'High-cardinality span attribute',
    pillar: 'traces' as const,
    dimension: 'cost' as const,
    severity: 'warning' as const,
    description: 'Setting user-specific attributes on spans creates high-cardinality time series, increasing storage/query costs.',
    costHint: 'Can increase trace storage costs by 10x or more at scale.',
  },
  {
    pattern: /counter\.add\(1,\s*\{[^}]*\b(path|url|endpoint|route)\b/gi,
    title: 'High-cardinality metric label',
    pillar: 'metrics' as const,
    dimension: 'cost' as const,
    severity: 'warning' as const,
    description: 'Using request path or URL as metric label creates unbounded time series.',
    costHint: 'Each unique label value creates a new time series; can cause metric explosion.',
  },
];

export async function analyzeEfficiencyNode(
  state: AgentStateType,
): Promise<Partial<AgentStateType>> {
  const { request, classifiedFiles, findings } = state;
  const log = logger.child({ jobId: request.jobId, node: 'analyzeEfficiency' });
  const start = Date.now();
  log.info({ event: 'node_started', node: 'analyzeEfficiency' });

  await publishProgress(request.jobId, 'efficiency', 82, 'Analyzing efficiency patterns...');

  const newFindings: Finding[] = [];

  for (const file of classifiedFiles) {
    if (!file.content || file.relevanceScore < 1) continue;

    for (const check of EFFICIENCY_PATTERNS) {
      const matches = file.content.match(check.pattern);
      if (matches) {
        newFindings.push({
          id: uuidv4(),
          pillar: check.pillar,
          severity: check.severity,
          dimension: check.dimension,
          title: check.title,
          description: check.description,
          filePath: file.path,
          estimatedMonthlyCostImpact: 0,
          sourceAgent: 'analyzeEfficiency',
          confidence: 0.6,
        });
      }
    }
  }

  const durationMs = Date.now() - start;
  log.info({
    event: 'node_completed',
    node: 'analyzeEfficiency',
    durationMs,
    patternMatches: newFindings.length,
  });

  return { findings: newFindings };
}

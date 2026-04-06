import type { AgentStateType } from '../graph/state.js';
import { publishProgress } from '../utils/progress.js';
import { logger } from '../utils/logger.js';

function fingerprint(f: { title: string; filePath?: string; lineStart?: number }): string {
  return `${f.title}::${f.filePath ?? ''}::${f.lineStart ?? 0}`;
}

export async function deduplicateNode(
  state: AgentStateType,
): Promise<Partial<AgentStateType>> {
  const { request, findings, suppressed } = state;
  const log = logger.child({ jobId: request.jobId, node: 'deduplicate' });
  const start = Date.now();
  log.info({ event: 'node_started', node: 'deduplicate', inputCount: findings.length });

  await publishProgress(request.jobId, 'deduplicating', 85, 'Removing duplicates...');

  const suppressedPaths = new Set(suppressed.map((s) => s.filePath));

  // Filter: lumis-ignore suppression
  let filtered = findings.filter((f) => {
    if (f.filePath && suppressedPaths.has(f.filePath)) {
      log.info({ event: 'finding_suppressed', reason: 'lumis_ignore', filePath: f.filePath, title: f.title });
      return false;
    }
    return true;
  });

  // Filter: confidence threshold
  filtered = filtered.filter((f) => f.confidence >= 0.3);

  // Deduplicate by fingerprint, keeping highest confidence
  const seen = new Map<string, number>();
  const deduplicated = [];

  for (const finding of filtered) {
    const fp = fingerprint(finding);
    const existingIdx = seen.get(fp);
    if (existingIdx !== undefined) {
      if (finding.confidence > (deduplicated[existingIdx].confidence ?? 0)) {
        deduplicated[existingIdx] = finding;
      }
    } else {
      seen.set(fp, deduplicated.length);
      deduplicated.push(finding);
    }
  }

  const durationMs = Date.now() - start;
  log.info({
    event: 'node_completed',
    node: 'deduplicate',
    durationMs,
    inputCount: findings.length,
    outputCount: deduplicated.length,
    removedDuplicates: findings.length - deduplicated.length,
  });

  return {
    findings: deduplicated,
    stage: 'deduplicating',
    progressPct: 87,
  };
}

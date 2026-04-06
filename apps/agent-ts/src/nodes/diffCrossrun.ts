import type { AgentStateType } from '../graph/state.js';
import type { CrossrunSummary } from '../graph/types.js';
import { getPool } from '../knowledge/db.js';
import { publishProgress } from '../utils/progress.js';
import { logger } from '../utils/logger.js';

export async function diffCrossrunNode(
  state: AgentStateType,
): Promise<Partial<AgentStateType>> {
  const { request, findings } = state;
  const log = logger.child({ jobId: request.jobId, node: 'diffCrossrun' });
  const start = Date.now();
  log.info({ event: 'node_started', node: 'diffCrossrun' });

  await publishProgress(request.jobId, 'crossrun', 88, 'Comparing with previous analysis...');

  let previousFindings: Set<string> = new Set();
  let previousJobId: string | null = null;

  try {
    const pool = getPool();
    const prevJob = await pool.query(
      `SELECT id FROM analysis_jobs
       WHERE repo_id = $1 AND status = 'completed' AND id != $2
       ORDER BY completed_at DESC LIMIT 1`,
      [request.repoId, request.jobId],
    );

    if (prevJob.rows.length > 0) {
      previousJobId = prevJob.rows[0].id;
      const prevResult = await pool.query(
        `SELECT findings FROM analysis_results WHERE job_id = $1`,
        [previousJobId],
      );

      if (prevResult.rows.length > 0 && prevResult.rows[0].findings) {
        const prev = prevResult.rows[0].findings;
        if (Array.isArray(prev)) {
          previousFindings = new Set(prev.map((f: { title: string }) => f.title));
        }
      }
    }
  } catch (err) {
    log.warn({ event: 'crossrun_query_failed', error: (err as Error).message });
  }

  const resolvedFindings: string[] = [];

  for (const finding of findings) {
    if (previousFindings.has(finding.title)) {
      finding.crossrunStatus = 'persisting';
      finding.isNew = false;
    } else {
      finding.crossrunStatus = 'new';
      finding.isNew = true;
    }
  }

  const currentTitles = new Set(findings.map((f) => f.title));
  for (const prevTitle of previousFindings) {
    if (!currentTitles.has(prevTitle)) {
      resolvedFindings.push(prevTitle);
    }
  }

  const crossrunSummary: CrossrunSummary = {
    newCount: findings.filter((f) => f.crossrunStatus === 'new').length,
    persistingCount: findings.filter((f) => f.crossrunStatus === 'persisting').length,
    resolvedCount: resolvedFindings.length,
    resolvedFindings,
    previousJobId: previousJobId ?? undefined,
  };

  const durationMs = Date.now() - start;
  log.info({
    event: 'node_completed',
    node: 'diffCrossrun',
    durationMs,
    ...crossrunSummary,
  });

  return {
    crossrunSummary,
    previousJobId,
    stage: 'crossrun',
    progressPct: 90,
  };
}

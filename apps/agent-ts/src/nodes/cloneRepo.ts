import type { AgentStateType } from '../graph/state.js';
import { cloneRepository } from '../utils/git.js';
import { publishProgress } from '../utils/progress.js';
import { logger } from '../utils/logger.js';

export async function cloneRepoNode(
  state: AgentStateType,
): Promise<Partial<AgentStateType>> {
  const { request } = state;
  const log = logger.child({ jobId: request.jobId, node: 'cloneRepo' });
  const start = Date.now();
  log.info({ event: 'node_started', node: 'cloneRepo' });

  await publishProgress(request.jobId, 'cloning', 5, 'Cloning repository...');

  const repoPath = await cloneRepository(
    request.cloneUrl,
    request.ref,
  );

  const durationMs = Date.now() - start;
  log.info({ event: 'node_completed', node: 'cloneRepo', durationMs, repoPath });

  return { repoPath, stage: 'cloning', progressPct: 10 };
}

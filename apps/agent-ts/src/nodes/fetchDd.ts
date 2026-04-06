import type { AgentStateType } from '../graph/state.js';
import { logger } from '../utils/logger.js';

export async function fetchDdNode(
  state: AgentStateType,
): Promise<Partial<AgentStateType>> {
  const { request } = state;
  const log = logger.child({ jobId: request.jobId, node: 'fetchDd' });
  const start = Date.now();
  log.info({ event: 'node_started', node: 'fetchDd' });

  // Datadog API integration — graceful skip if not configured
  // Future: fetch metrics, monitors, APM services from Datadog API
  const durationMs = Date.now() - start;
  log.info({ event: 'node_completed', node: 'fetchDd', durationMs, skipped: true });

  return { ddCoverage: null };
}

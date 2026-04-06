import type { AgentStateType } from '../graph/state.js';
import { publishProgress } from '../utils/progress.js';
import { logger } from '../utils/logger.js';

export async function consolidateNode(
  state: AgentStateType,
): Promise<Partial<AgentStateType>> {
  const { request, findings, ragContext } = state;
  const log = logger.child({ jobId: request.jobId, node: 'consolidate' });
  const start = Date.now();
  log.info({ event: 'node_started', node: 'consolidate', findingsCount: findings.length });

  await publishProgress(request.jobId, 'consolidating', 75, 'Consolidating findings...');

  const consolidated = findings.filter((f) => f.confidence > 0);

  const hasNoInstrumentation = consolidated.length === 0 && state.classifiedFiles.length > 0;
  if (hasNoInstrumentation) {
    const relevantCount = state.classifiedFiles.filter((f) => f.relevanceScore >= 1).length;
    if (relevantCount > 0) {
      consolidated.push({
        pillar: 'traces',
        severity: 'warning',
        dimension: 'coverage',
        title: 'No observability instrumentation detected',
        description: `Analyzed ${relevantCount} source files but found no existing observability instrumentation (spans, structured logging, or metrics). Consider adding OpenTelemetry SDK or equivalent.`,
        estimatedMonthlyCostImpact: 0,
        sourceAgent: 'consolidate',
        confidence: 0.9,
        verified: true,
      });
    }
  }

  // Mark findings that went through cross-domain enrichment as verified
  for (const finding of consolidated) {
    if (finding.enrichedBy && finding.enrichedBy.length > 0) {
      finding.verified = true;
    }
  }

  const durationMs = Date.now() - start;
  log.info({
    event: 'node_completed',
    node: 'consolidate',
    durationMs,
    inputFindings: findings.length,
    outputFindings: consolidated.length,
    suppressedByConfidence: findings.length - consolidated.length,
  });

  return {
    findings: consolidated,
    stage: 'consolidating',
    progressPct: 80,
  };
}

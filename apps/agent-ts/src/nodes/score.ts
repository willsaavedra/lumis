import type { AgentStateType } from '../graph/state.js';
import type { Scores, Finding } from '../graph/types.js';
import { publishProgress } from '../utils/progress.js';
import { logger } from '../utils/logger.js';

function computePillarScore(findings: Finding[], pillar: string): number {
  const pillarFindings = findings.filter((f) => f.pillar === pillar);
  if (pillarFindings.length === 0) return 100;

  let deductions = 0;
  for (const f of pillarFindings) {
    switch (f.severity) {
      case 'critical':
        deductions += 20;
        break;
      case 'warning':
        deductions += 10;
        break;
      case 'info':
        deductions += 3;
        break;
    }
  }
  return Math.max(0, 100 - deductions);
}

function computeDimensionScore(findings: Finding[], dimension: string): number {
  const dimFindings = findings.filter((f) => f.dimension === dimension);
  if (dimFindings.length === 0) return 100;

  let deductions = 0;
  for (const f of dimFindings) {
    switch (f.severity) {
      case 'critical':
        deductions += 15;
        break;
      case 'warning':
        deductions += 8;
        break;
      case 'info':
        deductions += 2;
        break;
    }
  }
  return Math.max(0, 100 - deductions);
}

export async function scoreNode(
  state: AgentStateType,
): Promise<Partial<AgentStateType>> {
  const { request, findings } = state;
  const log = logger.child({ jobId: request.jobId, node: 'score' });
  const start = Date.now();
  log.info({ event: 'node_started', node: 'score', findingsCount: findings.length });

  await publishProgress(request.jobId, 'scoring', 92, 'Computing scores...');

  const metricsScore = computePillarScore(findings, 'metrics');
  const logsScore = computePillarScore(findings, 'logs');
  const tracesScore = computePillarScore(findings, 'traces');
  const costScore = computeDimensionScore(findings, 'cost');
  const snrScore = computeDimensionScore(findings, 'snr');
  const pipelineScore = computeDimensionScore(findings, 'pipeline');
  const complianceScore = computeDimensionScore(findings, 'compliance');
  const securityScore = computePillarScore(findings, 'security');
  const efficiencyScore = computePillarScore(findings, 'efficiency');

  const global = Math.round(
    (metricsScore + logsScore + tracesScore + costScore + snrScore + pipelineScore + complianceScore) / 7,
  );

  const scores: Scores = {
    global,
    metrics: metricsScore,
    logs: logsScore,
    traces: tracesScore,
    cost: costScore,
    snr: snrScore,
    pipeline: pipelineScore,
    compliance: complianceScore,
    security: securityScore,
    efficiency: efficiencyScore,
  };

  const durationMs = Date.now() - start;
  log.info({ event: 'node_completed', node: 'score', durationMs, scores });

  return { scores, stage: 'scoring', progressPct: 95 };
}

import type { AgentStateType } from '../graph/state.js';
import type { AgentContext, CrossDomainReferral, Finding, TokenUsage } from '../graph/types.js';
import { agentRegistry } from '../agents/registry.js';
import { DomainAgent } from '../agents/DomainAgent.js';
import { publishProgress } from '../utils/progress.js';
import { logger } from '../utils/logger.js';

function groupBy<T>(arr: T[], key: (item: T) => string): Record<string, T[]> {
  const result: Record<string, T[]> = {};
  for (const item of arr) {
    const k = key(item);
    (result[k] ??= []).push(item);
  }
  return result;
}

export async function collaborationNode(
  state: AgentStateType,
): Promise<Partial<AgentStateType>> {
  const {
    request,
    referrals,
    findings,
    classifiedFiles,
    ragContext,
    microAgentObservabilityHints,
    callGraph,
    ddCoverage,
  } = state;
  const log = logger.child({ jobId: request.jobId, node: 'collaboration' });
  const start = Date.now();
  log.info({ event: 'node_started', node: 'collaboration', referralCount: referrals.length });

  if (referrals.length === 0) {
    log.info({ event: 'node_completed', node: 'collaboration', durationMs: Date.now() - start, enrichments: 0 });
    return { stage: 'collaboration', progressPct: 70 };
  }

  await publishProgress(request.jobId, 'collaboration', 65, `Cross-domain review: ${referrals.length} referrals...`);

  const context: AgentContext = {
    files: classifiedFiles,
    ragContext,
    microAgentObservabilityHints: microAgentObservabilityHints ?? null,
    llmProvider: request.llmProvider,
    analysisType: request.analysisType,
    callGraph,
    repoContext: request.repoContext,
    ddCoverage,
  };

  const grouped = groupBy(referrals, (r) => r.targetDomain);
  const enrichedFindings = [...findings];
  let totalUsage: TokenUsage = { promptTokens: 0, completionTokens: 0, totalTokens: 0, costUsd: 0, llmCalls: 0 };

  // Sequential enrichment to avoid rate-limiting
  for (const [domainName, refs] of Object.entries(grouped)) {
    const agent = agentRegistry.get(domainName);
    if (!agent || !(agent instanceof DomainAgent)) {
      log.warn({ event: 'enrichment_agent_not_found', domainName });
      continue;
    }

    log.info({ event: 'enrichment_batch_started', domainAgent: domainName, referralCount: refs.length });

    try {
      const { results, usage } = await agent.enrich(refs, context);

      totalUsage = {
        promptTokens: totalUsage.promptTokens + usage.promptTokens,
        completionTokens: totalUsage.completionTokens + usage.completionTokens,
        totalTokens: totalUsage.totalTokens + usage.totalTokens,
        costUsd: totalUsage.costUsd + usage.costUsd,
        llmCalls: totalUsage.llmCalls + usage.llmCalls,
      };

      for (const enrichment of results) {
        const finding = enrichedFindings[enrichment.findingIndex];
        if (!finding) continue;

        if (enrichment.action === 'enrich') {
          if (enrichment.enrichedDescription) finding.description = enrichment.enrichedDescription;
          if (enrichment.severity) finding.severity = enrichment.severity;
          if (enrichment.suggestion) finding.suggestion = enrichment.suggestion;
          finding.enrichedBy = [...(finding.enrichedBy ?? []), domainName];
          finding.verified = true;
          log.info({
            event: 'finding_enriched',
            findingIndex: enrichment.findingIndex,
            domainAgent: domainName,
            newSeverity: enrichment.severity,
          });
        } else if (enrichment.action === 'suppress') {
          finding.confidence = 0;
          log.info({
            event: 'finding_suppressed',
            findingIndex: enrichment.findingIndex,
            domainAgent: domainName,
            reason: enrichment.reasoning,
          });
        }
      }

      log.info({ event: 'enrichment_batch_completed', domainAgent: domainName, resultsCount: results.length });
    } catch (err) {
      log.error({ event: 'enrichment_batch_failed', domainAgent: domainName, error: (err as Error).message });
    }
  }

  const durationMs = Date.now() - start;
  const enrichedCount = enrichedFindings.filter((f) => f.enrichedBy && f.enrichedBy.length > 0).length;
  const suppressedCount = enrichedFindings.filter((f) => f.confidence === 0).length;

  log.info({
    event: 'node_completed',
    node: 'collaboration',
    durationMs,
    enrichedCount,
    suppressedCount,
  });

  return {
    findings: enrichedFindings,
    tokenUsage: totalUsage,
    stage: 'collaboration',
    progressPct: 70,
  };
}

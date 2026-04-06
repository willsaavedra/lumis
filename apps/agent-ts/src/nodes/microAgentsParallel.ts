import type { AgentStateType } from '../graph/state.js';
import type { Finding, AgentContext, TokenUsage, AgentStats, CrossDomainReferral } from '../graph/types.js';
import { agentRegistry, buildMicroAgentObservabilityHints } from '../agents/registry.js';
import type { BaseAgent } from '../agents/BaseAgent.js';
import { publishProgress, type AgentStatus } from '../utils/progress.js';
import { logger } from '../utils/logger.js';

const MAX_FILES_PER_AGENT = 30;
const LLM_CONCURRENCY = 3;

async function runWithConcurrency<T>(
  tasks: (() => Promise<T>)[],
  concurrency: number,
  onTaskComplete?: (index: number, result: PromiseSettledResult<T>) => void,
): Promise<PromiseSettledResult<T>[]> {
  const results: PromiseSettledResult<T>[] = new Array(tasks.length);
  let idx = 0;

  async function worker() {
    while (idx < tasks.length) {
      const i = idx++;
      try {
        const value = await tasks[i]();
        results[i] = { status: 'fulfilled', value };
      } catch (reason) {
        results[i] = { status: 'rejected', reason };
      }
      onTaskComplete?.(i, results[i]);
    }
  }

  await Promise.all(Array.from({ length: Math.min(concurrency, tasks.length) }, () => worker()));
  return results;
}

export async function microAgentsParallelNode(
  state: AgentStateType,
): Promise<Partial<AgentStateType>> {
  const { request, classifiedFiles, activeAgents, ragContext, callGraph, ddCoverage } = state;
  const log = logger.child({ jobId: request.jobId, node: 'microAgentsParallel' });
  const start = Date.now();
  log.info({ event: 'node_started', node: 'microAgentsParallel', agentCount: activeAgents.length });

  const microAgentObservabilityHints = buildMicroAgentObservabilityHints(
    state.detectedLanguages,
    state.detectedArtifacts,
    classifiedFiles,
  );

  const context: AgentContext & { jobId: string } = {
    files: classifiedFiles,
    ragContext,
    microAgentObservabilityHints,
    llmProvider: request.llmProvider,
    analysisType: request.analysisType,
    callGraph,
    repoContext: request.repoContext,
    ddCoverage,
    jobId: request.jobId,
  };

  const relevantFiles = classifiedFiles.filter((f) => f.relevanceScore >= 1);

  const agents = activeAgents
    .map((name) => agentRegistry.get(name))
    .filter((a): a is BaseAgent => !!a);

  // Build initial agent roster
  const agentRoster: Map<string, AgentStatus> = new Map();
  agents.forEach((a) => {
    const accepted = relevantFiles.filter((f) => a.accepts(f));
    agentRoster.set(a.name, {
      name: a.name,
      status: accepted.length > 0 ? 'queued' : 'completed',
      filesCount: Math.min(accepted.length, MAX_FILES_PER_AGENT),
      findingsCount: 0,
    });
  });

  // Publish initial roster
  await publishProgress(
    request.jobId, 'analyzing', 30,
    `Running ${agents.length} agents (concurrency=${LLM_CONCURRENCY})...`,
    { agents: Array.from(agentRoster.values()) },
  );

  const agentTasks = agents.map((agent, agentIdx) => () => {
    const accepted = relevantFiles.filter((f) => agent.accepts(f));

    if (accepted.length === 0) {
      return Promise.resolve({
        findings: [] as Finding[],
        usage: { promptTokens: 0, completionTokens: 0, totalTokens: 0, costUsd: 0, llmCalls: 0 } as TokenUsage,
        stats: { agentName: agent.name, findingsCount: 0, tokensUsed: 0, durationMs: 0, promptMode: 'fast' as const } as AgentStats,
      });
    }

    const capped = accepted
      .sort((a, b) => b.relevanceScore - a.relevanceScore)
      .slice(0, MAX_FILES_PER_AGENT);

    // Mark as running
    agentRoster.set(agent.name, { ...agentRoster.get(agent.name)!, status: 'running' });
    publishProgress(
      request.jobId, 'analyzing',
      30 + Math.round((agentIdx / agents.length) * 25),
      `${agent.name} analyzing ${capped.length} files...`,
      { agents: Array.from(agentRoster.values()), active_agent: agent.name },
    );

    log.info({
      event: 'agent_dispatch',
      agent: agent.name,
      totalAccepted: accepted.length,
      filesSent: capped.length,
    });

    return agent.analyze(capped, context);
  });

  let completedCount = 0;
  const results = await runWithConcurrency(agentTasks, LLM_CONCURRENCY, (index, result) => {
    completedCount++;
    const agentName = agents[index]?.name ?? 'unknown';

    if (result.status === 'fulfilled') {
      const { findings, stats } = result.value;
      agentRoster.set(agentName, {
        name: agentName,
        status: 'completed',
        findingsCount: findings.length,
        tokensUsed: stats?.tokensUsed ?? 0,
        durationMs: stats?.durationMs ?? 0,
      });
    } else {
      agentRoster.set(agentName, {
        name: agentName,
        status: 'failed',
        error: String(result.reason),
      });
    }

    const pct = 30 + Math.round((completedCount / agents.length) * 30);
    publishProgress(
      request.jobId, 'analyzing', pct,
      `${completedCount}/${agents.length} agents completed (${agentName} finished)`,
      { agents: Array.from(agentRoster.values()) },
    );
  });

  const allFindings: Finding[] = [];
  let totalUsage: TokenUsage = { promptTokens: 0, completionTokens: 0, totalTokens: 0, costUsd: 0, llmCalls: 0 };
  const breakdown: Record<string, AgentStats> = {};

  for (const result of results) {
    if (result.status === 'fulfilled') {
      const { findings, usage, stats } = result.value;
      allFindings.push(...findings);
      if (usage) {
        totalUsage = {
          promptTokens: totalUsage.promptTokens + usage.promptTokens,
          completionTokens: totalUsage.completionTokens + usage.completionTokens,
          totalTokens: totalUsage.totalTokens + usage.totalTokens,
          costUsd: totalUsage.costUsd + usage.costUsd,
          llmCalls: totalUsage.llmCalls + usage.llmCalls,
        };
      }
      if (stats) {
        breakdown[stats.agentName] = stats;
      }
    } else {
      log.error({ event: 'agent_task_rejected', error: result.reason });
    }
  }

  const referrals: CrossDomainReferral[] = [];
  for (let i = 0; i < allFindings.length; i++) {
    const finding = allFindings[i];
    if (finding.crossDomainHints && finding.crossDomainHints.length > 0) {
      for (const target of finding.crossDomainHints) {
        referrals.push({
          findingIndex: i,
          targetDomain: target,
          reason: finding.reasoning ?? finding.title,
          contextSnippet: finding.codeBefore ?? finding.suggestion ?? finding.description,
        });
      }
    }
  }

  const durationMs = Date.now() - start;
  log.info({
    event: 'node_completed',
    node: 'microAgentsParallel',
    durationMs,
    totalFindings: allFindings.length,
    referralsCount: referrals.length,
    agentsRun: Object.keys(breakdown).length,
  });

  return {
    findings: allFindings,
    referrals,
    tokenUsage: totalUsage,
    agentBreakdown: breakdown,
    microAgentObservabilityHints,
    stage: 'analyzing',
    progressPct: 60,
  };
}

import { StateGraph, END, START } from '@langchain/langgraph';
import { AgentState, type AgentStateType } from './state.js';
import type { AnalysisRequest, AnalysisResponse } from './types.js';
import { logger } from '../utils/logger.js';
import { publishProgress, setProgressTenantId } from '../utils/progress.js';
import { cleanupRepo } from '../utils/git.js';

import { cloneRepoNode } from '../nodes/cloneRepo.js';
import { preTriageNode } from '../nodes/preTriage.js';
import { contextDiscoveryNode } from '../nodes/contextDiscovery.js';
import { dispatcherNode } from '../nodes/dispatcher.js';
import { microAgentsParallelNode } from '../nodes/microAgentsParallel.js';
import { collaborationNode } from '../nodes/collaboration.js';
import { consolidateNode } from '../nodes/consolidate.js';
import { retrieveContextNode } from '../nodes/retrieveContext.js';
import { fetchDdNode } from '../nodes/fetchDd.js';
import { analyzeEfficiencyNode } from '../nodes/analyzeEfficiency.js';
import { deduplicateNode } from '../nodes/deduplicate.js';
import { diffCrossrunNode } from '../nodes/diffCrossrun.js';
import { scoreNode } from '../nodes/score.js';
import { generateSuggestionsNode } from '../nodes/generateSuggestions.js';

function routeAfterClone(state: AgentStateType): string {
  return state.request.analysisType === 'context' ? 'contextDiscovery' : 'preTriage';
}

function routeAfterConsolidate(state: AgentStateType): string {
  return state.request.analysisType === 'quick' ? 'deduplicate' : 'analyzeEfficiency';
}

function buildGraph() {
  const graph = new StateGraph(AgentState)
    .addNode('cloneRepo', cloneRepoNode)
    .addNode('contextDiscovery', contextDiscoveryNode)
    .addNode('preTriage', preTriageNode)
    .addNode('dispatcher', dispatcherNode)
    .addNode('parallelPass1', microAgentsParallelNode)
    .addNode('retrieveContext', retrieveContextNode)
    .addNode('fetchDd', fetchDdNode)
    .addNode('collaboration', collaborationNode)
    .addNode('consolidate', consolidateNode)
    .addNode('analyzeEfficiency', analyzeEfficiencyNode)
    .addNode('deduplicate', deduplicateNode)
    .addNode('diffCrossrun', diffCrossrunNode)
    .addNode('score', scoreNode)
    .addNode('generateSuggestions', generateSuggestionsNode)

    .addEdge(START, 'cloneRepo')
    .addConditionalEdges('cloneRepo', routeAfterClone, {
      contextDiscovery: 'contextDiscovery',
      preTriage: 'preTriage',
    })
    .addEdge('contextDiscovery', END)

    .addEdge('preTriage', 'dispatcher')
    .addEdge('dispatcher', 'parallelPass1')
    .addEdge('dispatcher', 'retrieveContext')
    .addEdge('dispatcher', 'fetchDd')

    .addEdge('parallelPass1', 'collaboration')
    .addEdge('retrieveContext', 'collaboration')
    .addEdge('fetchDd', 'collaboration')

    .addEdge('collaboration', 'consolidate')
    .addConditionalEdges('consolidate', routeAfterConsolidate, {
      analyzeEfficiency: 'analyzeEfficiency',
      deduplicate: 'deduplicate',
    })

    .addEdge('analyzeEfficiency', 'deduplicate')
    .addEdge('deduplicate', 'diffCrossrun')
    .addEdge('diffCrossrun', 'score')
    .addEdge('score', 'generateSuggestions')
    .addEdge('generateSuggestions', END);

  return graph.compile();
}

export async function runAnalysis(request: AnalysisRequest): Promise<AnalysisResponse> {
  const log = logger.child({ jobId: request.jobId, tenantId: request.tenantId });
  const startTime = Date.now();

  setProgressTenantId(request.tenantId);
  await publishProgress(request.jobId, 'starting', 0, 'Analysis started');

  const compiled = buildGraph();

  const initialState: Partial<AgentStateType> = {
    request,
    stage: 'starting',
    progressPct: 0,
  };

  let finalState: AgentStateType;
  try {
    finalState = await compiled.invoke(initialState) as AgentStateType;
  } catch (err) {
    const durationMs = Date.now() - startTime;
    log.error({ event: 'graph_failed', durationMs, error: (err as Error).message });
    await publishProgress(request.jobId, 'failed', 0, `Analysis failed: ${(err as Error).message}`);
    throw err;
  }

  if (finalState.repoPath) {
    await cleanupRepo(finalState.repoPath);
  }

  const durationMs = Date.now() - startTime;
  log.info({ event: 'graph_completed', durationMs, findingsCount: finalState.findings.length });

  await publishProgress(request.jobId, 'done', 100, 'Analysis completed');

  return {
    findings: finalState.findings,
    scores: finalState.scores ?? {
      global: 0, metrics: 0, logs: 0, traces: 0,
      cost: 0, snr: 0, pipeline: 0, compliance: 0,
    },
    suggestions: finalState.suggestions,
    tokenUsage: finalState.tokenUsage,
    agentBreakdown: finalState.agentBreakdown,
    crossrunSummary: finalState.crossrunSummary ?? undefined,
    contextSummary: finalState.contextSummary ?? undefined,
  };
}

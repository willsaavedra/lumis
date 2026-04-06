import type { AgentStateType } from '../graph/state.js';
import { chatComplete } from '../llm/client.js';
import { getModel, estimateTokens, computeMaxOutputTokens } from '../llm/config.js';
import { safeParseJson, contextSummarySchema } from '../llm/parsers.js';
import { publishProgress } from '../utils/progress.js';
import { logger } from '../utils/logger.js';

export async function contextDiscoveryNode(
  state: AgentStateType,
): Promise<Partial<AgentStateType>> {
  const { request, classifiedFiles } = state;
  const log = logger.child({ jobId: request.jobId, node: 'contextDiscovery' });
  const start = Date.now();
  log.info({ event: 'node_started', node: 'contextDiscovery' });

  await publishProgress(request.jobId, 'context_discovery', 30, 'Analyzing repository context...');

  const keyFiles = classifiedFiles
    .filter((f) => f.relevanceScore >= 1)
    .slice(0, 20)
    .map((f) => `- ${f.path} (${f.language ?? 'unknown'})`)
    .join('\n');

  const system = `You are a repository analysis expert. Analyze the repo structure and key files to produce a context summary.
Respond with a JSON object: { "repo_type", "primary_language", "observability_backend" (optional), "summary", "key_files" }`;

  const user = `Repository: ${request.repoFullName}
Key files:
${keyFiles}

${request.repoContext ? `Known context: ${JSON.stringify(request.repoContext)}` : ''}`;

  const ctxModel = getModel(request.llmProvider, 'triage');
  const ctxInputTokens = estimateTokens(system) + estimateTokens(user);
  const ctxMaxTokens = computeMaxOutputTokens(ctxModel, ctxInputTokens, 1024);

  try {
    const resp = await chatComplete({
      system,
      user,
      provider: request.llmProvider,
      model: ctxModel,
      maxTokens: ctxMaxTokens,
      temperature: 0.2,
    });

    const parsed = safeParseJson(resp.text, contextSummarySchema);
    const durationMs = Date.now() - start;
    log.info({ event: 'node_completed', node: 'contextDiscovery', durationMs });

    return {
      contextSummary: parsed?.summary ?? 'Unable to generate context summary.',
      tokenUsage: resp.usage,
      stage: 'context_discovery',
      progressPct: 100,
    };
  } catch (err) {
    log.error({ event: 'node_failed', node: 'contextDiscovery', error: (err as Error).message });
    return { contextSummary: 'Context discovery failed.', stage: 'context_discovery', progressPct: 100 };
  }
}

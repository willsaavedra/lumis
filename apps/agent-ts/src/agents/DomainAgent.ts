import { BaseAgent } from './BaseAgent.js';
import { chatComplete } from '../llm/client.js';
import { PROMPT_MODES, getModel, estimateTokens, computeMaxOutputTokens } from '../llm/config.js';
import { safeParseJson, enrichmentBatchSchema } from '../llm/parsers.js';
import { logger } from '../utils/logger.js';
import type {
  CrossDomainReferral,
  EnrichmentResult,
  AgentContext,
  TokenUsage,
} from '../graph/types.js';

export abstract class DomainAgent extends BaseAgent {
  readonly kind = 'domain' as const;

  abstract getEnrichmentSystemPrompt(context: AgentContext): string;

  abstract getEnrichmentUserPrompt(
    referrals: CrossDomainReferral[],
    context: AgentContext,
  ): string;

  async enrich(
    referrals: CrossDomainReferral[],
    context: AgentContext,
  ): Promise<{ results: EnrichmentResult[]; usage: TokenUsage }> {
    if (referrals.length === 0) {
      return {
        results: [],
        usage: { promptTokens: 0, completionTokens: 0, totalTokens: 0, costUsd: 0, llmCalls: 0 },
      };
    }

    const log = logger.child({ agent: this.name, referralCount: referrals.length });
    log.info({ event: 'agent_enrich_started' });

    const mode = 'verify' as const;
    const modeConfig = PROMPT_MODES[mode];
    const model = getModel(context.llmProvider, 'primary');

    const systemPrompt = [
      this.getEnrichmentSystemPrompt(context),
      '',
      'Respond ONLY with a JSON object: { "results": [...] }',
      'Each result must have: finding_index, action ("enrich"|"suppress"|"noop"), and optionally severity ("critical"|"warning"|"info"), enriched_description, suggestion, reasoning.',
    ].join('\n');

    const userPrompt = this.getEnrichmentUserPrompt(referrals, context);
    const inputTokens = estimateTokens(systemPrompt) + estimateTokens(userPrompt);
    const maxTokens = computeMaxOutputTokens(model, inputTokens, modeConfig.maxTokens);

    try {
      const resp = await chatComplete({
        system: systemPrompt,
        user: userPrompt,
        provider: context.llmProvider,
        model,
        maxTokens,
        temperature: modeConfig.temperature,
        topP: modeConfig.topP,
      });

      const parsed = safeParseJson(resp.text, enrichmentBatchSchema);
      const results: EnrichmentResult[] = (parsed?.results ?? []).map((r) => ({
        findingIndex: r.finding_index,
        action: r.action,
        severity: r.severity as EnrichmentResult['severity'],
        enrichedDescription: r.enriched_description,
        suggestion: r.suggestion,
        reasoning: r.reasoning,
      }));

      log.info({ event: 'agent_enrich_completed', resultsCount: results.length });
      return { results, usage: resp.usage };
    } catch (err) {
      log.error({ event: 'agent_enrich_failed', error: (err as Error).message });
      return {
        results: [],
        usage: { promptTokens: 0, completionTokens: 0, totalTokens: 0, costUsd: 0, llmCalls: 0 },
      };
    }
  }
}

import { v4 as uuidv4 } from 'uuid';
import { chatCompleteStream, type LLMResponse } from '../llm/client.js';
import { PROMPT_MODES, getModel, getContextWindow, estimateTokens, computeMaxOutputTokens } from '../llm/config.js';
import { safeParseJson, analysisOutputSchema } from '../llm/parsers.js';
import { selectPromptMode, REASONING_FRAMEWORK, NEGATIVE_EXAMPLES } from '../prompts/modes.js';
import { publishProgress, type AgentStatus } from '../utils/progress.js';
import { logger } from '../utils/logger.js';
import type {
  Finding,
  ClassifiedFile,
  AgentContext,
  PromptMode,
  AgentStats,
  Pillar,
  Severity,
  TokenUsage,
} from '../graph/types.js';
import type { AgentStateType } from '../graph/state.js';

const MAX_FILE_CHARS = 8_000;

const JSON_SCHEMA_INSTRUCTION = `
Respond ONLY with a valid JSON object following this EXACT schema:
{
  "findings": [
    {
      "pillar": "metrics" | "logs" | "traces" | "security" | "efficiency" | "compliance",
      "severity": "critical" | "warning" | "info",
      "dimension": "coverage" | "cost" | "snr" | "pipeline" | "compliance",
      "title": "<short title>",
      "description": "<detailed description>",
      "file_path": "<path/to/file>" or null,
      "line_start": <number> or null,
      "line_end": <number> or null,
      "suggestion": "<actionable fix>" or null,
      "code_before": "<existing code snippet>" or null,
      "code_after": "<improved code snippet>" or null,
      "estimated_monthly_cost_impact": <number, default 0>,
      "reasoning": "<which Q1-Q4 triggered this and why>",
      "cross_domain_hints": ["security", "dba", ...] or [],
      "confidence": <0.0 to 1.0>
    }
  ]
}

IMPORTANT:
- severity MUST be one of: "critical", "warning", "info" (NOT "high", "medium", "low")
- pillar MUST be one of: "metrics", "logs", "traces", "security", "efficiency", "compliance"
- dimension MUST be one of: "coverage", "cost", "snr", "pipeline", "compliance"
- file_path must use the exact path from the provided file list
- Do NOT wrap the JSON in markdown code fences
- Return an empty findings array if nothing noteworthy is found
`.trim();

export abstract class BaseAgent {
  abstract readonly name: string;
  abstract readonly kind: 'micro' | 'domain';
  abstract readonly pillar: Pillar;
  abstract readonly defaultMode: PromptMode;

  abstract getSystemPrompt(context: AgentContext): string;
  abstract getUserPrompt(files: ClassifiedFile[], context: AgentContext): string;
  abstract isRelevant(state: AgentStateType): boolean;
  abstract accepts(file: ClassifiedFile): boolean;

  /**
   * Micro-agents: prioridades de observabilidade para o agente de domínio D-observability.
   * Domínios retornam null.
   */
  getObservabilityFocusHints(): string | null {
    return null;
  }

  protected selectMode(files: ClassifiedFile[], context: AgentContext): PromptMode {
    return selectPromptMode(context.analysisType, files.length);
  }

  async analyze(
    files: ClassifiedFile[],
    context: AgentContext,
  ): Promise<{ findings: Finding[]; usage: TokenUsage; stats: AgentStats }> {
    const start = Date.now();
    const mode = this.selectMode(files, context);
    const modeConfig = PROMPT_MODES[mode];
    const model = getModel(context.llmProvider, 'primary');
    const contextWindow = getContextWindow(model);

    const log = logger.child({ agent: this.name, mode, filesCount: files.length });
    log.info({ event: 'agent_analyze_started' });

    const systemPrompt = this.buildSystemPrompt(context);
    const systemTokens = estimateTokens(systemPrompt);
    const desiredOutput = modeConfig.maxTokens;
    const fileBudgetTokens = contextWindow - systemTokens - desiredOutput - 200;

    const batches = this.splitIntoBatches(files, fileBudgetTokens);
    log.info({
      event: 'agent_prompt_budget',
      contextWindow,
      systemTokens,
      fileBudgetTokens,
      filesTotal: files.length,
      batches: batches.length,
    });

    const allFindings: Finding[] = [];
    let totalUsage: TokenUsage = { promptTokens: 0, completionTokens: 0, totalTokens: 0, costUsd: 0, llmCalls: 0 };

    const jobId = (context as unknown as { jobId?: string }).jobId ?? '';

    for (let batchIdx = 0; batchIdx < batches.length; batchIdx++) {
      const batchFiles = batches[batchIdx];

      const batchFilePaths = batchFiles.map((f) => f.path);

      await this.publishAgentStatus(jobId, {
        name: this.name,
        status: 'streaming',
        filesCount: batchFiles.length,
        currentBatch: batchIdx + 1,
        totalBatches: batches.length,
      }, { current_files: batchFilePaths });

      const userPrompt = this.getUserPrompt(batchFiles, context);
      const totalInputTokens = systemTokens + estimateTokens(userPrompt);
      const maxTokens = computeMaxOutputTokens(model, totalInputTokens, desiredOutput);

      log.info({
        event: 'agent_batch_started',
        batch: batchIdx + 1,
        totalBatches: batches.length,
        filesInBatch: batchFiles.length,
        estimatedInputTokens: totalInputTokens,
        maxOutputTokens: maxTokens,
      });

      let lastPublishMs = 0;
      const STREAM_THROTTLE_MS = 300;

      let resp: LLMResponse;
      try {
        resp = await chatCompleteStream({
          system: systemPrompt,
          user: userPrompt,
          provider: context.llmProvider,
          model,
          maxTokens,
          temperature: modeConfig.temperature,
          topP: modeConfig.topP,
          onToken: (_delta, accumulated) => {
            const now = Date.now();
            if (now - lastPublishMs < STREAM_THROTTLE_MS) return;
            lastPublishMs = now;
            this.publishAgentStatus(jobId, {
              name: this.name,
              status: 'streaming',
              filesCount: batchFiles.length,
              currentBatch: batchIdx + 1,
              totalBatches: batches.length,
            }, {
              current_files: batchFilePaths,
              llm_streaming: true,
              llm_text: accumulated.slice(-1500),
            });
          },
        });
      } catch (err) {
        log.error({ event: 'agent_batch_failed', batch: batchIdx + 1, error: (err as Error).message });
        await this.publishAgentStatus(jobId, {
          name: this.name,
          status: 'failed',
          error: (err as Error).message,
          currentBatch: batchIdx + 1,
          totalBatches: batches.length,
        });
        continue;
      }

      totalUsage = addUsage(totalUsage, resp.usage);

      const parsed = safeParseJson(resp.text, analysisOutputSchema);
      const batchFindings = this.mapFindings(parsed?.findings ?? [], mode);

      allFindings.push(...batchFindings);

      log.info({
        event: 'agent_batch_completed',
        batch: batchIdx + 1,
        findingsInBatch: batchFindings.length,
        totalFindingsSoFar: allFindings.length,
      });
    }

    const durationMs = Date.now() - start;

    await this.publishAgentStatus(jobId, {
      name: this.name,
      status: 'completed',
      findingsCount: allFindings.length,
      tokensUsed: totalUsage.totalTokens,
      durationMs,
    });

    log.info({ event: 'agent_analyze_completed', findingsCount: allFindings.length, durationMs, batches: batches.length });

    return {
      findings: allFindings,
      usage: totalUsage,
      stats: {
        agentName: this.name,
        findingsCount: allFindings.length,
        tokensUsed: totalUsage.totalTokens,
        durationMs,
        promptMode: mode,
      },
    };
  }

  private buildSystemPrompt(context: AgentContext): string {
    return [
      this.getSystemPrompt(context),
      '',
      REASONING_FRAMEWORK,
      '',
      NEGATIVE_EXAMPLES,
      '',
      JSON_SCHEMA_INSTRUCTION,
    ].join('\n');
  }

  private mapFindings(rawFindings: Array<Record<string, unknown>>, mode: PromptMode): Finding[] {
    return rawFindings.map((f: Record<string, unknown>) => ({
      id: uuidv4(),
      pillar: (f.pillar as Pillar) || this.pillar,
      severity: (f.severity ?? 'info') as Severity,
      dimension: (f.dimension as Finding['dimension']) || 'coverage',
      title: f.title as string,
      description: f.description as string,
      filePath: (f.file_path as string) ?? undefined,
      lineStart: (f.line_start as number) ?? undefined,
      lineEnd: (f.line_end as number) ?? undefined,
      suggestion: (f.suggestion as string) ?? undefined,
      codeBefore: (f.code_before as string) ?? undefined,
      codeAfter: (f.code_after as string) ?? undefined,
      estimatedMonthlyCostImpact: (f.estimated_monthly_cost_impact as number) ?? 0,
      reasoning: f.reasoning as string | undefined,
      sourceAgent: this.name,
      crossDomainHints: f.cross_domain_hints as string[] | undefined,
      confidence: (f.confidence as number) ?? 0.7,
      promptMode: mode,
      verified: false,
    }));
  }

  /**
   * Split files into batches that each fit within the token budget.
   * Ensures zero coverage loss — every file goes into exactly one batch.
   */
  protected splitIntoBatches(files: ClassifiedFile[], tokenBudget: number): ClassifiedFile[][] {
    if (tokenBudget <= 0) {
      return files.length > 0 ? [files.slice(0, 1)] : [[]];
    }

    const batches: ClassifiedFile[][] = [];
    let currentBatch: ClassifiedFile[] = [];
    let currentTokens = 0;

    for (const f of files) {
      if (!f.content) continue;
      const content = f.content.length > MAX_FILE_CHARS
        ? f.content.slice(0, MAX_FILE_CHARS)
        : f.content;
      const tokens = estimateTokens(content) + 30;

      if (currentTokens + tokens > tokenBudget && currentBatch.length > 0) {
        batches.push(currentBatch);
        currentBatch = [];
        currentTokens = 0;
      }

      currentBatch.push(f);
      currentTokens += tokens;
    }

    if (currentBatch.length > 0) {
      batches.push(currentBatch);
    }

    return batches.length > 0 ? batches : [[]];
  }

  protected formatFiles(files: ClassifiedFile[]): string {
    return files
      .filter((f) => f.content)
      .map((f) => {
        const content = f.content!.length > MAX_FILE_CHARS
          ? f.content!.slice(0, MAX_FILE_CHARS) + '\n... [truncated]'
          : f.content!;
        return `### File: ${f.path} (${f.language ?? 'unknown'})\n\`\`\`\n${content}\n\`\`\``;
      })
      .join('\n\n');
  }

  protected formatRagContext(rag: string | null): string {
    if (!rag) return '';
    return `\n## Knowledge Base Context\n${rag}\n`;
  }

  private async publishAgentStatus(
    jobId: string,
    agentStatus: AgentStatus,
    extra?: { current_files?: string[]; llm_streaming?: boolean; llm_text?: string },
  ): Promise<void> {
    if (!jobId) return;
    try {
      await publishProgress(jobId, 'analyzing', -1, `Agent ${agentStatus.name}: ${agentStatus.status}`, {
        agents: [agentStatus],
        active_agent: agentStatus.name,
        llm_streaming: extra?.llm_streaming ?? (agentStatus.status === 'streaming'),
        current_files: extra?.current_files,
        llm_text: extra?.llm_text,
      });
    } catch {
      // non-critical
    }
  }
}

function addUsage(a: TokenUsage, b: TokenUsage): TokenUsage {
  return {
    promptTokens: a.promptTokens + b.promptTokens,
    completionTokens: a.completionTokens + b.completionTokens,
    totalTokens: a.totalTokens + b.totalTokens,
    costUsd: a.costUsd + b.costUsd,
    llmCalls: a.llmCalls + b.llmCalls,
  };
}

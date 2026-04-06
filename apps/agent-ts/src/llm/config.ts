import type { LlmProvider, PromptMode } from '../graph/types.js';
import { config } from '../config.js';

export interface PromptModeConfig {
  temperature: number;
  topP: number;
  maxTokens: number;
}

export const PROMPT_MODES: Record<PromptMode, PromptModeConfig> = {
  fast: { temperature: 0.2, topP: 0.85, maxTokens: 2048 },
  standard: { temperature: 0.3, topP: 0.9, maxTokens: 4096 },
  deep: { temperature: 0.4, topP: 0.95, maxTokens: 8192 },
  verify: { temperature: 0.1, topP: 0.8, maxTokens: 2048 },
};

const MODEL_CONTEXT_WINDOWS: Record<string, number> = {
  'claude-sonnet-4-20250514': 200_000,
  'claude-haiku-4-5-20251001': 200_000,
  'Qwen/Qwen3.5-35B-A3B-FP8': 20_000,
};

const DEFAULT_CONTEXT_WINDOW = 20_000;
const MIN_OUTPUT_TOKENS = 1024;
const OUTPUT_RESERVE_RATIO = 0.25;
const CHARS_PER_TOKEN = 3.5;

export function getModel(provider: LlmProvider, tier: 'primary' | 'triage' = 'primary'): string {
  if (provider === 'anthropic') {
    return tier === 'triage' ? config.anthropicModelTriage : config.anthropicModelPrimary;
  }
  return config.cerebraAiModel;
}

export function getContextWindow(model: string): number {
  return MODEL_CONTEXT_WINDOWS[model] ?? DEFAULT_CONTEXT_WINDOW;
}

export function estimateTokens(text: string): number {
  return Math.ceil(text.length / CHARS_PER_TOKEN);
}

/**
 * Given the model's context window and the input prompt size,
 * compute the safest maxTokens for output.
 */
export function computeMaxOutputTokens(model: string, inputTokens: number, desiredMaxTokens: number): number {
  const contextWindow = getContextWindow(model);
  const available = contextWindow - inputTokens;
  const capped = Math.min(desiredMaxTokens, Math.max(MIN_OUTPUT_TOKENS, available));
  return Math.max(MIN_OUTPUT_TOKENS, capped);
}

/**
 * Truncate a file list so the total formatted text stays within a token budget.
 * Returns the subset of files that fits.
 */
export function fitFilesToBudget(
  formattedFiles: string[],
  tokenBudget: number,
): string[] {
  const result: string[] = [];
  let usedTokens = 0;

  for (const f of formattedFiles) {
    const tokens = estimateTokens(f);
    if (usedTokens + tokens > tokenBudget) break;
    result.push(f);
    usedTokens += tokens;
  }

  return result;
}

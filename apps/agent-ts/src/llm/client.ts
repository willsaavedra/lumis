import Anthropic from '@anthropic-ai/sdk';
import OpenAI from 'openai';
import { config } from '../config.js';
import { logger } from '../utils/logger.js';
import type { LlmProvider, TokenUsage } from '../graph/types.js';

export interface LLMResponse {
  text: string;
  usage: TokenUsage;
  model: string;
  durationMs: number;
}

export interface ChatCompleteOptions {
  system: string;
  user: string;
  provider: LlmProvider;
  model?: string;
  maxTokens?: number;
  temperature?: number;
  topP?: number;
  timeout?: number;
  jsonMode?: boolean;
}

const MAX_RETRIES = 3;
const BASE_DELAY_MS = 5_000;

const anthropicClient = new Anthropic({ apiKey: config.anthropicApiKey });

function getCerebraClient(): OpenAI {
  return new OpenAI({
    apiKey: config.cerebraAiApiKey || 'no-key',
    baseURL: config.cerebraAiBaseUrl,
  });
}

function resolveModel(provider: LlmProvider, model?: string): string {
  if (model) return model;
  return provider === 'anthropic'
    ? config.anthropicModelPrimary
    : config.cerebraAiModel;
}

function isRetryable(err: unknown): boolean {
  if (err instanceof Anthropic.RateLimitError) return true;
  if (err instanceof OpenAI.RateLimitError) return true;
  const status = (err as { status?: number })?.status;
  return status === 429 || status === 529;
}

function retryAfterMs(err: unknown): number | null {
  const headers = (err as { headers?: Record<string, string> })?.headers;
  const retryAfter = headers?.['retry-after'];
  if (retryAfter) {
    const secs = parseFloat(retryAfter);
    if (!isNaN(secs)) return secs * 1000;
  }
  return null;
}

async function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export interface StreamChatCompleteOptions extends ChatCompleteOptions {
  onToken?: (delta: string, accumulated: string) => void;
}

export async function chatCompleteStream(opts: StreamChatCompleteOptions): Promise<LLMResponse> {
  const model = resolveModel(opts.provider, opts.model);
  const maxTokens = opts.maxTokens ?? 4096;
  const temperature = opts.temperature ?? 0.3;
  const topP = opts.topP ?? 0.9;

  const log = logger.child({ provider: opts.provider, model });

  for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
    const start = Date.now();
    try {
      if (opts.provider === 'anthropic') {
        let accumulated = '';
        let inputTokens = 0;
        let outputTokens = 0;

        const stream = anthropicClient.messages.stream({
          model,
          max_tokens: maxTokens,
          temperature,
          top_p: topP,
          system: opts.system,
          messages: [{ role: 'user', content: opts.user }],
        });

        for await (const event of stream) {
          if (event.type === 'content_block_delta' && event.delta.type === 'text_delta') {
            accumulated += event.delta.text;
            opts.onToken?.(event.delta.text, accumulated);
          }
          if (event.type === 'message_delta' && event.usage) {
            outputTokens = event.usage.output_tokens;
          }
        }

        const finalMessage = await stream.finalMessage();
        inputTokens = finalMessage.usage.input_tokens;
        outputTokens = finalMessage.usage.output_tokens;

        const durationMs = Date.now() - start;
        const usage: TokenUsage = {
          promptTokens: inputTokens,
          completionTokens: outputTokens,
          totalTokens: inputTokens + outputTokens,
          costUsd: estimateCost('anthropic', model, inputTokens, outputTokens),
          llmCalls: 1,
        };

        log.info({ event: 'llm_stream_completed', durationMs, inputTokens, outputTokens, costUsd: usage.costUsd, attempt });
        return { text: accumulated, usage, model, durationMs };
      }

      // CerebraAI / OpenAI-compatible streaming
      const openai = getCerebraClient();
      const stream = await openai.chat.completions.create({
        model,
        messages: [
          { role: 'system', content: opts.system },
          { role: 'user', content: opts.user },
        ],
        max_tokens: maxTokens,
        temperature,
        top_p: topP,
        stream: true,
        ...(opts.jsonMode ? { response_format: { type: 'json_object' } } : {}),
      });

      let accumulated = '';
      let promptTokens = 0;
      let completionTokens = 0;

      for await (const chunk of stream) {
        const delta = chunk.choices[0]?.delta?.content;
        if (delta) {
          accumulated += delta;
          opts.onToken?.(delta, accumulated);
        }
        if (chunk.usage) {
          promptTokens = chunk.usage.prompt_tokens ?? 0;
          completionTokens = chunk.usage.completion_tokens ?? 0;
        }
      }

      const durationMs = Date.now() - start;
      const usage: TokenUsage = {
        promptTokens,
        completionTokens,
        totalTokens: promptTokens + completionTokens,
        costUsd: 0,
        llmCalls: 1,
      };

      log.info({ event: 'llm_stream_completed', durationMs, inputTokens: promptTokens, outputTokens: completionTokens, attempt });
      return { text: accumulated, usage, model, durationMs };
    } catch (err) {
      if (isRetryable(err) && attempt < MAX_RETRIES) {
        const delayMs = retryAfterMs(err) ?? BASE_DELAY_MS * Math.pow(2, attempt);
        log.warn({ event: 'llm_call_rate_limited', attempt, retryInMs: delayMs, error: (err as Error).message });
        await sleep(delayMs);
        continue;
      }
      throw err;
    }
  }
  throw new Error('Unreachable: max retries exceeded');
}

export async function chatComplete(opts: ChatCompleteOptions): Promise<LLMResponse> {
  const model = resolveModel(opts.provider, opts.model);
  const maxTokens = opts.maxTokens ?? 4096;
  const temperature = opts.temperature ?? 0.3;
  const topP = opts.topP ?? 0.9;

  const log = logger.child({ provider: opts.provider, model });

  for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
    const start = Date.now();
    try {
      if (opts.provider === 'anthropic') {
        const response = await anthropicClient.messages.create({
          model,
          max_tokens: maxTokens,
          temperature,
          top_p: topP,
          system: opts.system,
          messages: [{ role: 'user', content: opts.user }],
        });

        const durationMs = Date.now() - start;
        const text = response.content
          .filter((b): b is Anthropic.TextBlock => b.type === 'text')
          .map((b) => b.text)
          .join('');

        const usage: TokenUsage = {
          promptTokens: response.usage.input_tokens,
          completionTokens: response.usage.output_tokens,
          totalTokens: response.usage.input_tokens + response.usage.output_tokens,
          costUsd: estimateCost('anthropic', model, response.usage.input_tokens, response.usage.output_tokens),
          llmCalls: 1,
        };

        log.info({
          event: 'llm_call_completed',
          durationMs,
          inputTokens: usage.promptTokens,
          outputTokens: usage.completionTokens,
          costUsd: usage.costUsd,
          attempt,
        });

        return { text, usage, model, durationMs };
      }

      // CerebraAI / OpenAI-compatible
      const openai = getCerebraClient();
      const messages: OpenAI.Chat.Completions.ChatCompletionMessageParam[] = [
        { role: 'system', content: opts.system },
        { role: 'user', content: opts.user },
      ];

      const response = await openai.chat.completions.create({
        model,
        messages,
        max_tokens: maxTokens,
        temperature,
        top_p: topP,
        ...(opts.jsonMode ? { response_format: { type: 'json_object' } } : {}),
      });

      const durationMs = Date.now() - start;
      const text = response.choices[0]?.message?.content ?? '';
      const promptTokens = response.usage?.prompt_tokens ?? 0;
      const completionTokens = response.usage?.completion_tokens ?? 0;

      const usage: TokenUsage = {
        promptTokens,
        completionTokens,
        totalTokens: promptTokens + completionTokens,
        costUsd: 0,
        llmCalls: 1,
      };

      log.info({
        event: 'llm_call_completed',
        durationMs,
        inputTokens: usage.promptTokens,
        outputTokens: usage.completionTokens,
        attempt,
      });

      return { text, usage, model, durationMs };
    } catch (err) {
      if (isRetryable(err) && attempt < MAX_RETRIES) {
        const delayMs = retryAfterMs(err) ?? BASE_DELAY_MS * Math.pow(2, attempt);
        log.warn({
          event: 'llm_call_rate_limited',
          attempt,
          retryInMs: delayMs,
          error: (err as Error).message,
        });
        await sleep(delayMs);
        continue;
      }
      throw err;
    }
  }

  throw new Error('Unreachable: max retries exceeded');
}

function estimateCost(provider: string, model: string, inputTokens: number, outputTokens: number): number {
  if (provider === 'cerebra_ai') return 0;

  const rates: Record<string, { input: number; output: number }> = {
    'claude-sonnet-4-20250514': { input: 3.0, output: 15.0 },
    'claude-haiku-4-5-20251001': { input: 0.8, output: 4.0 },
  };

  const rate = rates[model] ?? { input: 3.0, output: 15.0 };
  return (inputTokens * rate.input + outputTokens * rate.output) / 1_000_000;
}

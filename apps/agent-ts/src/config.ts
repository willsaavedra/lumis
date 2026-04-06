import dotenv from 'dotenv';
dotenv.config();

function env(key: string, fallback = ''): string {
  return process.env[key] ?? fallback;
}

export const config = {
  port: parseInt(env('PORT', '3000'), 10),
  nodeEnv: env('NODE_ENV', 'development'),
  logLevel: env('LOG_LEVEL', 'info'),

  anthropicApiKey: env('ANTHROPIC_API_KEY'),
  anthropicModelPrimary: env('ANTHROPIC_MODEL_PRIMARY', 'claude-sonnet-4-20250514'),
  anthropicModelTriage: env('ANTHROPIC_MODEL_TRIAGE', 'claude-haiku-4-5-20251001'),

  cerebraAiBaseUrl: env('CEREBRA_AI_BASE_URL', 'http://52.86.35.131:8001/v1'),
  cerebraAiApiKey: env('CEREBRA_AI_API_KEY'),
  cerebraAiModel: env('CEREBRA_AI_MODEL', 'Qwen/Qwen3.5-35B-A3B-FP8'),

  openaiApiKey: env('OPENAI_API_KEY'),
  /** Alinhar com ingestão RAG Python (`openai_embedding_model`). */
  openaiEmbeddingModel: env('OPENAI_EMBEDDING_MODEL', 'text-embedding-3-small'),

  databaseUrl: env('DATABASE_URL', 'postgresql://sre:local_only@postgres:5432/lumis'),
  redisUrl: env('REDIS_URL', 'redis://redis:6379/0'),

  get isProduction() {
    return this.nodeEnv === 'production';
  },
} as const;

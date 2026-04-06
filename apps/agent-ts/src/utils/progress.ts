import { Redis } from 'ioredis';
import { config } from '../config.js';
import { logger } from './logger.js';

let redis: Redis | null = null;

function getRedis(): Redis {
  if (!redis) {
    redis = new Redis(config.redisUrl, { maxRetriesPerRequest: 3 });
  }
  return redis;
}

export interface AgentStatus {
  name: string;
  status: 'queued' | 'running' | 'streaming' | 'completed' | 'failed';
  findingsCount?: number;
  tokensUsed?: number;
  durationMs?: number;
  filesCount?: number;
  currentBatch?: number;
  totalBatches?: number;
  error?: string;
}

export interface ProgressPayload {
  stage: string;
  progress_pct: number;
  message: string;
  timestamp: string;
  agents?: AgentStatus[];
  active_agent?: string;
  llm_streaming?: boolean;
  token_preview?: string;
  /** Arquivos que o agente ativo está processando neste momento. */
  current_files?: string[];
  /** Texto parcial (reasoning) do LLM em tempo real. */
  llm_text?: string;
}

function channel(tenantId: string, jobId: string): string {
  return `t:${tenantId}:analysis:${jobId}:progress`;
}

export async function publishProgress(
  jobId: string,
  stage: string,
  pct: number,
  message: string,
  extra?: Partial<ProgressPayload>,
): Promise<void> {
  const tenantId = publishProgress._tenantId ?? '';
  const ch = tenantId ? channel(tenantId, jobId) : `analysis:${jobId}:progress`;

  const payload: ProgressPayload = {
    stage,
    progress_pct: pct,
    message,
    timestamp: new Date().toISOString(),
    ...extra,
  };

  try {
    await getRedis().publish(ch, JSON.stringify(payload));
  } catch (err) {
    logger.warn({ event: 'progress_publish_failed', jobId, error: (err as Error).message });
  }
}

publishProgress._tenantId = '' as string;

export function setProgressTenantId(tenantId: string): void {
  publishProgress._tenantId = tenantId;
}

export async function closeRedis(): Promise<void> {
  if (redis) {
    await redis.quit();
    redis = null;
  }
}

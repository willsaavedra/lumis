import { z } from 'zod';
import { logger } from '../utils/logger.js';

const SEVERITY_MAP: Record<string, string> = {
  critical: 'critical', high: 'critical',
  warning: 'warning', medium: 'warning',
  info: 'info', low: 'info',
};

const severityTransform = z.string().transform((v) => {
  const mapped = SEVERITY_MAP[v.toLowerCase()];
  if (mapped === 'critical' || mapped === 'warning' || mapped === 'info') return mapped;
  return 'info' as const;
});

export const findingSchema = z.object({
  pillar: z.string().optional(),
  severity: severityTransform,
  dimension: z.string().optional(),
  title: z.string(),
  description: z.string(),
  file_path: z.string().nullable().optional(),
  file: z.string().nullable().optional(),
  line_start: z.number().nullable().optional(),
  line: z.number().nullable().optional(),
  line_end: z.number().nullable().optional(),
  suggestion: z.string().nullable().optional(),
  recommendation: z.string().nullable().optional(),
  code_before: z.string().nullable().optional(),
  code_after: z.string().nullable().optional(),
  estimated_monthly_cost_impact: z.number().default(0),
  reasoning: z.string().optional(),
  cross_domain_hints: z.array(z.string()).optional(),
  confidence: z.number().min(0).max(1).default(0.7),
}).transform((f) => ({
  ...f,
  file_path: f.file_path ?? f.file ?? null,
  line_start: f.line_start ?? f.line ?? null,
  suggestion: f.suggestion ?? f.recommendation ?? null,
  pillar: f.pillar ?? 'traces',
  dimension: f.dimension ?? 'coverage',
}));

export const analysisOutputSchema = z.object({
  findings: z.array(findingSchema),
});

export const enrichmentResultSchema = z.object({
  finding_index: z.number(),
  action: z.enum(['enrich', 'suppress', 'noop']),
  severity: z.enum(['critical', 'warning', 'info']).optional(),
  enriched_description: z.string().optional(),
  suggestion: z.string().optional(),
  reasoning: z.string().optional(),
});

export const enrichmentBatchSchema = z.object({
  results: z.array(enrichmentResultSchema),
});

export const contextSummarySchema = z.object({
  repo_type: z.string(),
  primary_language: z.string(),
  observability_backend: z.string().optional(),
  summary: z.string(),
  key_files: z.array(z.string()).optional(),
});

export const triageFileSchema = z.object({
  path: z.string(),
  language: z.string().nullable(),
  relevance_score: z.number().min(0).max(2),
  detected_artifacts: z.array(z.string()).optional(),
});

export const triageOutputSchema = z.object({
  files: z.array(triageFileSchema),
});

export function safeParseJson<T>(text: string, schema: z.ZodType<T>): T | null {
  const jsonMatch = text.match(/```json\s*([\s\S]*?)```/) || text.match(/(\{[\s\S]*\})/);
  if (!jsonMatch) return null;

  try {
    const parsed = JSON.parse(jsonMatch[1]);
    const result = schema.safeParse(parsed);
    if (result.success) return result.data;

    logger.warn({
      event: 'json_parse_validation_failed',
      errors: result.error.issues.slice(0, 3),
    });
    return null;
  } catch {
    return null;
  }
}

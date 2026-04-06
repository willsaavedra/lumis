import type { AgentStateType } from '../graph/state.js';
import type { RepoContext } from '../graph/types.js';
import { MAX_RAG_QUERIES, RAG_TOP_K_PER_QUERY } from '../knowledge/ingestCatalog.js';
import { formatKnowledgeContext, retrieveRagChunks } from '../knowledge/retriever.js';
import { publishProgress } from '../utils/progress.js';
import { logger } from '../utils/logger.js';

/** Primeiro idioma útil vindo de `repoContext.language` (string ou array). */
function normalizeRepoLanguage(
  lang: RepoContext['language'],
): string | null {
  if (lang == null) return null;
  if (typeof lang === 'string') {
    const t = lang.trim();
    return t ? t.toLowerCase() : null;
  }
  if (Array.isArray(lang)) {
    for (const item of lang) {
      if (typeof item === 'string' && item.trim()) return item.trim().toLowerCase();
    }
  }
  return null;
}

function instrumentationKind(
  backend: string | undefined,
): 'otel' | 'datadog' | 'mixed' | null {
  if (!backend?.trim()) return null;
  const b = backend.toLowerCase();
  const hasOtel = b.includes('otel') || b.includes('opentelemetry');
  const hasDd = b.includes('datadog') || /\bdd\b/.test(b);
  if (hasOtel && hasDd) return 'mixed';
  if (hasOtel) return 'otel';
  if (hasDd) return 'datadog';
  return null;
}

function primaryLanguage(state: AgentStateType): string | null {
  const rc = state.request.repoContext;
  const fromRepo = normalizeRepoLanguage(rc.language);
  if (fromRepo) return fromRepo;

  if (state.detectedLanguages.length > 0) {
    return state.detectedLanguages[0].toLowerCase();
  }

  const relevant = state.classifiedFiles.filter(
    (f) => f.relevanceScore >= 1 && f.language,
  );
  if (relevant.length === 0) return null;

  const byLang = new Map<string, number>();
  for (const f of relevant) {
    const lang = f.language!.toLowerCase();
    byLang.set(lang, (byLang.get(lang) ?? 0) + 1);
  }
  let best: string | null = null;
  let bestCount = 0;
  for (const [lang, n] of byLang) {
    if (n > bestCount) {
      bestCount = n;
      best = lang;
    }
  }
  return best;
}

/**
 * Paridade com `_build_queries` em `apps/agent/nodes/retrieve_context.py`.
 */
function buildRagQueries(state: AgentStateType): string[] {
  const queries: string[] = [];
  const lang = primaryLanguage(state);
  const tenantId = state.request.tenantId;
  const repoId = state.request.repoId;
  const inst = instrumentationKind(state.request.repoContext.observabilityBackend);

  if (lang) {
    queries.push(`${lang} observability instrumentation best practices`);
    queries.push(`${lang} error handling span record error observability`);
    queries.push(`${lang} context propagation trace distributed tracing`);
    if (inst === 'otel' || inst === 'mixed') {
      queries.push(`opentelemetry ${lang} span trace context propagation`);
    }
    if (inst === 'datadog' || inst === 'mixed') {
      queries.push(`datadog apm ${lang} tracing instrumentation`);
    }
  }

  if (tenantId) {
    queries.push('naming convention metrics required tags tenant standards');
    queries.push('approved sdk version log library required log fields');
  }

  const highRelevance = state.classifiedFiles
    .filter((f) => f.relevanceScore >= 2)
    .slice(0, 3);
  for (const f of highRelevance) {
    if (f.path && repoId) {
      queries.push(`previous findings ${repoId} ${f.path}`);
    }
  }

  if (!lang) {
    const langs = state.detectedLanguages.join(', ');
    if (langs) {
      queries.push(`observability best practices for ${langs} applications`);
    }
    if (state.detectedArtifacts.includes('kubernetes') || state.detectedArtifacts.includes('helm')) {
      queries.push('Kubernetes observability monitoring probes exporters');
    }
    if (state.detectedArtifacts.includes('terraform')) {
      queries.push('Terraform IaC observability monitoring modules');
    }
  }

  return queries.slice(0, MAX_RAG_QUERIES);
}

export async function retrieveContextNode(
  state: AgentStateType,
): Promise<Partial<AgentStateType>> {
  const { request } = state;
  const log = logger.child({ jobId: request.jobId, node: 'retrieveContext' });
  const start = Date.now();
  log.info({ event: 'node_started', node: 'retrieveContext' });

  await publishProgress(request.jobId, 'retrieving_context', 30, 'Querying knowledge base...');

  const queries = buildRagQueries(state);
  const lang = primaryLanguage(state);

  const chunks =
    queries.length > 0
      ? await retrieveRagChunks({
          queries,
          language: lang,
          tenantId: request.tenantId,
          topKPerQuery: RAG_TOP_K_PER_QUERY,
        })
      : [];

  const ragContext = formatKnowledgeContext(chunks);

  const durationMs = Date.now() - start;
  log.info({
    event: 'node_completed',
    node: 'retrieveContext',
    durationMs,
    queryCount: queries.length,
    chunksRetrieved: chunks.length,
  });

  return { ragContext };
}

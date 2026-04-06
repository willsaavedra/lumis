/**
 * Catálogo de ingestão RAG global — espelha o contrato do agente Python.
 *
 * Fonte de verdade (ingestão + URLs): `apps/agent/tasks/ingest_global_docs.py`
 * e `apps/agent/tasks/static_observability_fe_mobile.py`.
 *
 * O agente TS não executa o Celery de ingestão; este módulo evita drift de
 * `source_type`, listas de URLs e constantes de retrieval vs. Python.
 */

/** TTL em dias para documentos buscados por URL (refresh semanal no worker). */
export const DOC_EXPIRES_DAYS = 30;

/** Multiplicador usado no Python para chunks estáticos (ex.: `_ingest_static`). */
export const STATIC_EXPIRES_MULTIPLIER = 4;

/** Alinhado a `rag_shared.EMBEDDING_DIMS` / coluna pgvector. */
export const EMBEDDING_DIMS = 1536;

/** Modelo padrão — alinhar com `OPENAI_EMBEDDING_MODEL` na API/worker Python. */
export const DEFAULT_EMBEDDING_MODEL = 'text-embedding-3-small';

export type DocSourceEntry = {
  readonly url: string;
  readonly languageHint: string | null;
  readonly pillar: string;
};

/** `source_type` persistido em `knowledge_chunks` para conteúdo buscado (OTel/Prometheus/FE mobile). */
export const GLOBAL_FETCH_SOURCE_TYPE_OTEL = 'otel_docs' as const;

/** Datadog docs. */
export const GLOBAL_FETCH_SOURCE_TYPE_DD = 'dd_docs' as const;

/** Blocos estáticos grandes (`_STATIC_KNOWLEDGE`, FE/mobile static). */
export const SOURCE_TYPE_STATIC_KNOWLEDGE = 'static_knowledge' as const;

/** Conhecimento por tenant (não listado aqui — vem de outros pipelines). */
export const TENANT_SOURCE_TYPES = [
  'tenant_standards',
  'analysis_history',
  'cross_repo_pattern',
] as const;

/** Boost de rerank (mesmo valor que `retrieve_context._rerank` no Python). */
export const TENANT_KNOWLEDGE_SIMILARITY_BOOST = 0.05;

// --- URLs OTel SDK (language_hint, pillar) — _OTEL_SDK_DOCS ---
export const OTEL_SDK_DOCS: readonly DocSourceEntry[] = [
  { url: 'https://opentelemetry.io/docs/languages/go/instrumentation/', languageHint: 'go', pillar: 'traces' },
  { url: 'https://opentelemetry.io/docs/languages/python/instrumentation/', languageHint: 'python', pillar: 'traces' },
  { url: 'https://opentelemetry.io/docs/languages/java/instrumentation/', languageHint: 'java', pillar: 'traces' },
  { url: 'https://opentelemetry.io/docs/languages/js/instrumentation/', languageHint: 'node', pillar: 'traces' },
  { url: 'https://opentelemetry.io/docs/concepts/signals/metrics/', languageHint: null, pillar: 'metrics' },
  { url: 'https://opentelemetry.io/docs/concepts/signals/logs/', languageHint: null, pillar: 'logs' },
  { url: 'https://opentelemetry.io/docs/concepts/context-propagation/', languageHint: null, pillar: 'traces' },
];

// --- Datadog — _DD_DOCS ---
export const DD_DOCS: readonly DocSourceEntry[] = [
  {
    url: 'https://docs.datadoghq.com/tracing/trace_collection/automatic_instrumentation/',
    languageHint: null,
    pillar: 'traces',
  },
  { url: 'https://docs.datadoghq.com/logs/log_collection/', languageHint: null, pillar: 'logs' },
  { url: 'https://docs.datadoghq.com/metrics/', languageHint: null, pillar: 'metrics' },
  {
    url: 'https://docs.datadoghq.com/tracing/guide/add_span_md_and_graph_its_requests/',
    languageHint: null,
    pillar: 'traces',
  },
  {
    url: 'https://docs.datadoghq.com/containers/kubernetes/installation/?tab=datadogoperator',
    languageHint: null,
    pillar: 'metrics',
  },
  { url: 'https://docs.datadoghq.com/containers/datadog_operator', languageHint: null, pillar: 'metrics' },
];

// --- Prometheus — armazenados como `otel_docs` no ingest Python — _PROMETHEUS_DOCS ---
export const PROMETHEUS_DOCS: readonly DocSourceEntry[] = [
  { url: 'https://prometheus.io/docs/prometheus/latest/installation/', languageHint: null, pillar: 'metrics' },
  { url: 'https://prometheus.io/docs/practices/naming/', languageHint: null, pillar: 'metrics' },
  { url: 'https://prometheus.io/docs/practices/instrumentation/', languageHint: null, pillar: 'metrics' },
  {
    url: 'https://raw.githubusercontent.com/prometheus-operator/kube-prometheus/main/README.md',
    languageHint: null,
    pillar: 'metrics',
  },
];

export const OTEL_SEMCONV_URL =
  'https://raw.githubusercontent.com/open-telemetry/semantic-conventions/main/docs/general/attributes.md';

// --- FE / mobile — FE_MOBILE_DOC_URLS (ingest como `otel_docs`) ---
export const FE_MOBILE_DOC_URLS: readonly DocSourceEntry[] = [
  {
    url: 'https://opentelemetry.io/docs/languages/js/getting-started/browser/',
    languageHint: 'javascript',
    pillar: 'traces',
  },
  {
    url: 'https://opentelemetry.io/docs/languages/js/instrumentation/',
    languageHint: 'javascript',
    pillar: 'traces',
  },
  { url: 'https://web.dev/vitals/', languageHint: null, pillar: 'metrics' },
];

/**
 * IDs de `metadata.source_id` / ingest estático (sem colar o markdown aqui).
 * Ver `_STATIC_KNOWLEDGE` e `STATIC_OBSERVABILITY_FE_MOBILE` no Python.
 */
export const STATIC_KNOWLEDGE_SOURCE_IDS = [
  'terraform-iac-best-practices',
  'kubernetes-infra-monitoring-best-practices',
  'datadog-kubernetes-operator-best-practices',
  'otel-workshop-intro-observability',
  'otel-workshop-signals-best-practices',
] as const;

export const STATIC_FE_MOBILE_SOURCE_IDS = [
  'observability-browser-rum-otel',
  'observability-mobile-native',
] as const;

/** Agrupamento no prompt — espelha `retrieve_context._SOURCE_TO_SECTION` (Python). */
export const SOURCE_TYPE_TO_SECTION: Readonly<Record<string, string>> = {
  otel_docs: 'OTel Reference (global)',
  dd_docs: 'Datadog Reference (global)',
  tenant_standards: 'Tenant Standards',
  analysis_history: 'Previous Findings (confirmed)',
  cross_repo_pattern: 'Cross-repo Patterns',
};

/** Mesmos limites que `apps/agent/nodes/retrieve_context.py`. */
export const RAG_TOP_K_PER_QUERY = 5;
export const RAG_MIN_SIMILARITY = 0.3;
const RAG_MAX_TOKENS = 3000;
const CHARS_PER_TOKEN = 4;
export const RAG_MAX_CHARS = RAG_MAX_TOKENS * CHARS_PER_TOKEN;

export const MAX_RAG_QUERIES = 10;

/** Ordem de seções no prompt (igual ao dict em `retrieve_context._format_rag_context`). */
export const RAG_SECTION_DISPLAY_ORDER: readonly string[] = [
  'OTel Reference (global)',
  'Datadog Reference (global)',
  'Tenant Standards',
  'Previous Findings (confirmed)',
  'Cross-repo Patterns',
];

import { getPool } from './db.js';
import { embedText, embedTexts } from './embedder.js';
import { logger } from '../utils/logger.js';
import {
  RAG_MAX_CHARS,
  RAG_MIN_SIMILARITY,
  RAG_SECTION_DISPLAY_ORDER,
  RAG_TOP_K_PER_QUERY,
  SOURCE_TYPE_TO_SECTION,
  TENANT_KNOWLEDGE_SIMILARITY_BOOST,
} from './ingestCatalog.js';

export interface KnowledgeChunk {
  id: string;
  sourceType: string;
  content: string;
  language: string | null;
  pillar: string | null;
  similarity: number;
}

export interface RagRetrievalOptions {
  queries: string[];
  /** Filtro único por coluna `language` (paridade com Python `_primary_language`). */
  language?: string | null;
  tenantId?: string | null;
  topKPerQuery?: number;
  minSimilarity?: number;
}

function mapRow(row: Record<string, unknown>): KnowledgeChunk {
  return {
    id: row.id as string,
    sourceType: row.source_type as string,
    content: row.content as string,
    language: row.language as string | null,
    pillar: row.pillar as string | null,
    similarity: parseFloat(String(row.similarity)),
  };
}

/** Busca global: apenas `tenant_id IS NULL` (chunks compartilhados). */
async function searchGlobal(
  embeddingStr: string,
  language: string | null,
  topK: number,
): Promise<KnowledgeChunk[]> {
  const pool = getPool();
  const params: unknown[] = [embeddingStr];
  let p = 2;
  const langFilter = language ? `AND language = $${p++}` : '';
  if (language) params.push(language);
  params.push(topK);
  const limitIdx = p;

  const sql = `
    SELECT id, source_type, content, language, pillar,
           1 - (embedding <=> $1::vector) AS similarity
    FROM knowledge_chunks
    WHERE (expires_at IS NULL OR expires_at > now())
      AND tenant_id IS NULL
      ${langFilter}
    ORDER BY embedding <=> $1::vector
    LIMIT $${limitIdx}
  `;

  const result = await pool.query(sql, params);
  return result.rows.map((row: Record<string, unknown>) => mapRow(row));
}

/** Global + chunks do tenant (paridade com `_search_index` quando `tenant_id` está setado). */
async function searchGlobalOrTenant(
  embeddingStr: string,
  tenantId: string,
  language: string | null,
  topK: number,
): Promise<KnowledgeChunk[]> {
  const pool = getPool();
  const params: unknown[] = [embeddingStr];
  let p = 2;
  const langFilter = language ? `AND language = $${p++}` : '';
  if (language) params.push(language);
  params.push(tenantId);
  const tenantIdx = p++;
  params.push(topK);
  const limitIdx = p;

  const sql = `
    SELECT id, source_type, content, language, pillar,
           1 - (embedding <=> $1::vector) AS similarity
    FROM knowledge_chunks
    WHERE (expires_at IS NULL OR expires_at > now())
      AND (tenant_id IS NULL OR tenant_id = $${tenantIdx}::uuid)
      ${langFilter}
    ORDER BY embedding <=> $1::vector
    LIMIT $${limitIdx}
  `;

  const result = await pool.query(sql, params);
  return result.rows.map((row: Record<string, unknown>) => mapRow(row));
}

function dedupeChunks(chunks: KnowledgeChunk[]): KnowledgeChunk[] {
  const seen = new Set<string>();
  const out: KnowledgeChunk[] = [];
  for (const c of chunks) {
    const key = c.content.slice(0, 100);
    if (!seen.has(key)) {
      seen.add(key);
      out.push(c);
    }
  }
  return out;
}

function rerankChunks(chunks: KnowledgeChunk[]): KnowledgeChunk[] {
  const scored = chunks.map((c) => {
    let sim = c.similarity;
    if (
      c.sourceType === 'tenant_standards' ||
      c.sourceType === 'analysis_history' ||
      c.sourceType === 'cross_repo_pattern'
    ) {
      sim += TENANT_KNOWLEDGE_SIMILARITY_BOOST;
    }
    return { ...c, similarity: sim };
  });
  return scored.sort((a, b) => b.similarity - a.similarity);
}

/**
 * Pipeline dual global + tenant, alinhado a `apps/agent/nodes/retrieve_context.py`.
 */
export async function retrieveRagChunks(options: RagRetrievalOptions): Promise<KnowledgeChunk[]> {
  const log = logger.child({ module: 'retriever' });
  const queries = options.queries.filter((q) => q.trim().length > 0);
  if (queries.length === 0) return [];

  const topK = options.topKPerQuery ?? RAG_TOP_K_PER_QUERY;
  const minSim = options.minSimilarity ?? RAG_MIN_SIMILARITY;
  const language = options.language ?? null;
  const tenantId = options.tenantId ?? null;

  try {
    const embeddings = await embedTexts(queries);
    const collected: KnowledgeChunk[] = [];

    for (let i = 0; i < queries.length; i++) {
      const embeddingStr = `[${embeddings[i].join(',')}]`;

      const globalRows = await searchGlobal(embeddingStr, language, topK);
      for (const row of globalRows) {
        if (row.similarity >= minSim) collected.push(row);
      }

      if (tenantId) {
        const tenantRows = await searchGlobalOrTenant(embeddingStr, tenantId, language, topK);
        for (const row of tenantRows) {
          if (row.similarity >= minSim) collected.push(row);
        }
      }
    }

    const deduped = dedupeChunks(collected);
    return rerankChunks(deduped);
  } catch (err) {
    log.error({ event: 'knowledge_retrieval_failed', error: (err as Error).message });
    return [];
  }
}

/**
 * Busca simples (um embedding, índice global). Mantido para chamadas pontuais.
 * Se `languages` tiver um único item, aplica filtro; caso contrário sem filtro de idioma.
 */
export async function retrieveKnowledge(
  query: string,
  languages?: string[],
  topK = RAG_TOP_K_PER_QUERY,
): Promise<KnowledgeChunk[]> {
  const log = logger.child({ module: 'retriever' });
  try {
    const embedding = await embedText(query);
    const embeddingStr = `[${embedding.join(',')}]`;
    const lang = languages?.length === 1 ? languages[0] : null;
    const rows = await searchGlobal(embeddingStr, lang, topK);
    const filtered = rows.filter((r) => r.similarity >= RAG_MIN_SIMILARITY);
    log.info({ event: 'knowledge_retrieved', count: filtered.length, query: query.slice(0, 100) });
    return filtered;
  } catch (err) {
    log.error({ event: 'knowledge_retrieval_failed', error: (err as Error).message });
    return [];
  }
}

/**
 * Formata contexto para o prompt — paridade com `_format_rag_context` (Python),
 * com limite de caracteres `RAG_MAX_CHARS`.
 */
export function formatKnowledgeContext(chunks: KnowledgeChunk[], maxChars = RAG_MAX_CHARS): string {
  if (chunks.length === 0) return '';

  const sections: Record<string, string[]> = {};

  let totalChars = 0;
  for (const chunk of chunks) {
    if (totalChars >= maxChars) break;
    const sectionTitle =
      SOURCE_TYPE_TO_SECTION[chunk.sourceType] ?? 'OTel Reference (global)';
    const content = chunk.content.trim();
    if (!sections[sectionTitle]) sections[sectionTitle] = [];
    if (totalChars + content.length <= maxChars) {
      sections[sectionTitle].push(content);
      totalChars += content.length;
    }
  }

  const lines: string[] = ['### CONTEXT FROM KNOWLEDGE BASE\n'];
  const seen = new Set<string>();
  for (const title of RAG_SECTION_DISPLAY_ORDER) {
    const contents = sections[title];
    if (!contents?.length) continue;
    seen.add(title);
    lines.push(`## ${title}`);
    for (const c of contents) {
      lines.push(c);
    }
    lines.push('');
  }
  for (const [title, contents] of Object.entries(sections)) {
    if (seen.has(title) || !contents.length) continue;
    lines.push(`## ${title}`);
    for (const c of contents) {
      lines.push(c);
    }
    lines.push('');
  }

  if (lines.length <= 2) return '';
  return lines.join('\n');
}

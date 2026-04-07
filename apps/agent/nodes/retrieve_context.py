"""
Node: retrieve_context

Runs between fetch_dd_coverage and analyze_coverage.
Implements the dual retrieval pipeline:
  1. Query Builder — extracts semantic queries from changed files and call graph
  2. Dual Retrieval — searches global index + tenant index in parallel
  3. Re-ranker — de-duplicates and scores by relevance
  4. Injects the top-K chunks into state as `rag_context` for analyze_coverage
"""
from __future__ import annotations

import asyncio

import structlog

from apps.agent.nodes.base import publish_progress, publish_thought
from apps.agent.schemas import AgentState

log = structlog.get_logger(__name__)

# Max tokens to inject into the LLM prompt
_MAX_RAG_TOKENS = 3000
_CHARS_PER_TOKEN = 4
_MAX_RAG_CHARS = _MAX_RAG_TOKENS * _CHARS_PER_TOKEN

# Number of results per query per index
_TOP_K = 5

# Minimum cosine similarity to include a chunk (0.0–1.0)
_MIN_SIMILARITY = 0.30


async def retrieve_context_node(state: AgentState) -> dict:
    """
    Build semantic queries from the current analysis context, retrieve relevant
    knowledge chunks from the global + tenant indexes, and store them in state.
    """
    await publish_progress(state, "retrieving", 38, "Retrieving knowledge base context...", stage_index=4)

    from apps.api.core.config import settings

    # Skip retrieval if OpenAI key is not set (graceful degradation)
    if not settings.openai_api_key:
        log.warning("retrieve_context_skipped_no_openai_key")
        return {"rag_context": None}

    try:
        rag_context = await _retrieve(state)
    except Exception as e:
        log.warning("retrieve_context_failed", error=str(e))
        rag_context = None

    if rag_context:
        log.info(
            "rag_context_retrieved",
            chars=len(rag_context),
            job_id=state.get("job_id"),
        )
        await publish_thought(state, "retrieve_context", f"Retrieved {len(rag_context)} chars of knowledge base context", status="done")
    else:
        await publish_thought(state, "retrieve_context", "No relevant knowledge base context found", status="done")
    await publish_progress(state, "retrieving", 42, "Knowledge context ready.", stage_index=4)
    return {"rag_context": rag_context}


async def _retrieve(state: AgentState) -> str | None:
    queries = _build_queries(state)
    if not queries:
        return None

    tenant_id = state.get("tenant_id")

    # Embed all queries at once
    from apps.agent.tasks.rag_shared import embed_texts

    embeddings = await embed_texts(queries)
    query_embeddings = list(zip(queries, embeddings))

    # Dual retrieval: global (tenant_id=NULL) + tenant-specific in parallel
    global_task = asyncio.create_task(
        _search_index(query_embeddings, tenant_id=None, language=_primary_language(state))
    )
    tenant_task = asyncio.create_task(
        _search_index(query_embeddings, tenant_id=tenant_id, language=_primary_language(state))
    ) if tenant_id else asyncio.create_task(asyncio.coroutine(lambda: [])())

    global_chunks, tenant_chunks = await asyncio.gather(global_task, tenant_task)

    all_chunks = global_chunks + tenant_chunks

    if not all_chunks:
        return None

    # Re-rank: de-duplicate by content prefix, sort by similarity
    reranked = _rerank(all_chunks)

    return _format_rag_context(reranked, state)


def _build_queries(state: AgentState) -> list[str]:
    """
    Build semantic queries from the analysis context.
    Query types: language+pattern, tenant standards, file triage (when files in scope),
    file-specific history.
    """
    queries: list[str] = []
    lang = _primary_language(state)
    request = state.get("request", {})
    repo_id = request.get("repo_id", "")
    tenant_id = state.get("tenant_id", "")
    repo_context = state.get("repo_context") or {}
    instrumentation = repo_context.get("instrumentation")

    # 1. Language + observability pattern queries
    if lang:
        queries.append(f"{lang} observability instrumentation best practices")
        queries.append(f"{lang} error handling span record error observability")
        queries.append(f"{lang} context propagation trace distributed tracing")
        if instrumentation in ("otel", "mixed"):
            queries.append(f"opentelemetry {lang} span trace context propagation")
        if instrumentation in ("datadog", "mixed"):
            queries.append(f"datadog apm {lang} tracing instrumentation")

    # 2. Tenant internal standards
    if tenant_id:
        queries.append(f"naming convention metrics required tags tenant standards")
        queries.append(f"approved sdk version log library required log fields")

    # 3. File triage / relevance (matches global chunks from file_triage_guide.md)
    changed_files = state.get("changed_files", [])
    if changed_files:
        queries.append(
            "file relevance triage observability analysis which source files to prioritize "
            "application code vs tests vs configuration"
        )

    # 4. File-specific history for changed files
    high_relevance = [f for f in changed_files if f.get("relevance_score", 0) >= 2][:3]
    for f in high_relevance:
        file_path = f.get("path", "")
        if file_path and repo_id:
            queries.append(f"previous findings {repo_id} {file_path}")

    return queries[:10]  # cap at 10 queries


async def _search_index(
    query_embeddings: list[tuple[str, list[float]]],
    *,
    tenant_id: str | None,
    language: str | None,
) -> list[dict]:
    """
    Search knowledge_chunks for each query embedding, returning unique chunks above threshold.
    """
    from sqlalchemy import text
    from apps.api.core.database import AsyncSessionFactory

    results: list[dict] = []
    seen_content: set[str] = set()

    async with AsyncSessionFactory() as session:
        # Set RLS tenant context if tenant_id is provided
        if tenant_id:
            await session.execute(
                text(f"SET LOCAL app.tenant_id = '{tenant_id}'")
            )

        for query, embedding in query_embeddings:
            embedding_str = "[" + ",".join(str(v) for v in embedding) + "]"

            lang_filter = "AND language = :language" if language else ""
            tenant_filter = (
                "AND (tenant_id IS NULL OR tenant_id = CAST(:tenant_id AS uuid))"
                if tenant_id else
                "AND tenant_id IS NULL"
            )

            sql = text(f"""
                SELECT
                    content,
                    source_type,
                    language,
                    pillar,
                    metadata,
                    1 - (embedding <=> CAST(:embedding AS vector)) AS similarity
                FROM knowledge_chunks
                WHERE
                    (expires_at IS NULL OR expires_at > now())
                    {tenant_filter}
                    {lang_filter}
                ORDER BY embedding <=> CAST(:embedding AS vector)
                LIMIT :limit
            """)

            params = {
                "embedding": embedding_str,
                "limit": _TOP_K,
            }
            if language:
                params["language"] = language
            if tenant_id:
                params["tenant_id"] = tenant_id

            rows = (await session.execute(sql, params)).fetchall()

            for row in rows:
                sim = float(row.similarity)
                if sim < _MIN_SIMILARITY:
                    continue
                # De-duplicate by first 100 chars
                key = row.content[:100]
                if key not in seen_content:
                    seen_content.add(key)
                    results.append({
                        "content": row.content,
                        "source_type": row.source_type,
                        "language": row.language,
                        "pillar": row.pillar,
                        "similarity": sim,
                    })

    return results


def _rerank(chunks: list[dict]) -> list[dict]:
    """
    Sort chunks by similarity descending.
    Tenant-specific chunks get a small relevance boost to prioritize custom standards.
    """
    def _score(chunk: dict) -> float:
        sim = chunk["similarity"]
        if chunk["source_type"] in ("tenant_standards", "analysis_history", "cross_repo_pattern"):
            sim += 0.05  # small boost for tenant-specific knowledge
        return sim

    return sorted(chunks, key=_score, reverse=True)


def _format_rag_context(chunks: list[dict], state: AgentState) -> str:
    """
    Format the retrieved chunks into a structured context section
    to be injected into the analyze_coverage system prompt.
    """
    sections: dict[str, list[str]] = {
        "OTel Reference (global)": [],
        "Datadog Reference (global)": [],
        "Tenant Standards": [],
        "Previous Findings (confirmed)": [],
        "Cross-repo Patterns": [],
    }

    _SOURCE_TO_SECTION = {
        "otel_docs": "OTel Reference (global)",
        "dd_docs": "Datadog Reference (global)",
        "tenant_standards": "Tenant Standards",
        "analysis_history": "Previous Findings (confirmed)",
        "cross_repo_pattern": "Cross-repo Patterns",
    }

    total_chars = 0
    for chunk in chunks:
        if total_chars >= _MAX_RAG_CHARS:
            break
        section_key = _SOURCE_TO_SECTION.get(chunk["source_type"], "OTel Reference (global)")
        content = chunk["content"].strip()
        if total_chars + len(content) <= _MAX_RAG_CHARS:
            sections[section_key].append(content)
            total_chars += len(content)

    # Build the formatted context block
    lines = ["### CONTEXT FROM KNOWLEDGE BASE\n"]
    for section_title, contents in sections.items():
        if contents:
            lines.append(f"## {section_title}")
            for c in contents:
                lines.append(c)
            lines.append("")

    if len(lines) <= 2:
        return ""

    return "\n".join(lines)


def _primary_language(state: AgentState) -> str | None:
    """Return the primary language for this analysis."""
    repo_context = state.get("repo_context") or {}
    lang_list = repo_context.get("language")
    if isinstance(lang_list, list) and lang_list:
        return lang_list[0].lower()
    if isinstance(lang_list, str):
        return lang_list.lower()
    # Infer from changed files
    changed = state.get("changed_files", [])
    langs = [f["language"] for f in changed if f.get("language") and f.get("relevance_score", 0) >= 1]
    if langs:
        from collections import Counter
        return Counter(langs).most_common(1)[0][0]
    return None

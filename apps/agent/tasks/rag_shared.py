"""Shared utilities for RAG ingestion tasks."""
from __future__ import annotations

import uuid as uuid_lib
from datetime import datetime, timedelta, timezone

import structlog

log = structlog.get_logger(__name__)

# Default embedding dims for text-embedding-3-small (1536). If you change
# openai_embedding_model, align pgvector column / re-embed accordingly.
EMBEDDING_DIMS = 1536

# Token approximations for chunking
CHARS_PER_TOKEN = 4  # rough approximation


def chunk_text(text: str, max_tokens: int = 400, overlap_tokens: int = 50) -> list[str]:
    """
    Split text into overlapping chunks of approximately max_tokens tokens.
    Uses character-based approximation (4 chars ≈ 1 token).
    """
    max_chars = max_tokens * CHARS_PER_TOKEN
    overlap_chars = overlap_tokens * CHARS_PER_TOKEN

    if len(text) <= max_chars:
        return [text] if text.strip() else []

    chunks = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = end - overlap_chars

    return chunks


def chunk_by_sections(text: str, max_tokens: int = 400, overlap_tokens: int = 50) -> list[str]:
    """
    Split text by H2/H3 markdown headings, then chunk large sections further.
    Preserves section heading context in each chunk.
    """
    import re
    sections = re.split(r'\n(?=#{2,3}\s)', text)
    chunks = []
    for section in sections:
        section = section.strip()
        if not section:
            continue
        section_chunks = chunk_text(section, max_tokens, overlap_tokens)
        chunks.extend(section_chunks)
    return chunks or chunk_text(text, max_tokens, overlap_tokens)


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Generate embeddings via OpenAI API (model from Settings: openai_embedding_model)."""
    if not texts:
        return []

    from openai import AsyncOpenAI

    from apps.api.core.config import settings

    if not settings.openai_api_key:
        raise ValueError(
            "openai_api_key not set — add OPENAI_API_KEY to the environment (RAG embeddings)."
        )

    client = AsyncOpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url or None,
    )
    model = settings.openai_embedding_model
    embeddings = []
    batch_size = 100

    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        response = await client.embeddings.create(model=model, input=batch)
        embeddings.extend([item.embedding for item in response.data])

    return embeddings


async def upsert_chunks(
    chunks: list[dict],
    *,
    tenant_id: str | None = None,
    source_type: str,
    language: str | None = None,
    pillar: str | None = None,
    repo_id: str | None = None,
    expires_days: int | None = None,
) -> int:
    """
    Upsert knowledge chunks into the knowledge_chunks table.
    Uses raw SQL because SQLAlchemy doesn't natively support pgvector.

    Each chunk dict must have:
      - content: str
      - embedding: list[float]
      - metadata: dict (optional)
    """
    from sqlalchemy import text
    from apps.api.core.database import AsyncSessionFactory

    if not chunks:
        return 0

    expires_at = None
    if expires_days is not None:
        expires_at = datetime.now(timezone.utc) + timedelta(days=expires_days)

    inserted = 0
    async with AsyncSessionFactory() as session:
        for chunk in chunks:
            embedding_str = "[" + ",".join(str(v) for v in chunk["embedding"]) + "]"
            metadata = chunk.get("metadata", {}) or {}

            # Use CAST(... AS ...) not :param::type — SQLAlchemy misparses :: after named binds.
            await session.execute(text("""
                INSERT INTO knowledge_chunks
                    (id, tenant_id, source_type, content, embedding, metadata,
                     language, pillar, repo_id, expires_at)
                VALUES
                    (:id, :tenant_id, :source_type, :content, CAST(:embedding AS vector),
                     CAST(:metadata AS jsonb), :language, :pillar, :repo_id, :expires_at)
                ON CONFLICT DO NOTHING
            """), {
                "id": str(uuid_lib.uuid4()),
                "tenant_id": tenant_id,
                "source_type": source_type,
                "content": chunk["content"],
                "embedding": embedding_str,
                "metadata": __import__("json").dumps(metadata),
                "language": language,
                "pillar": pillar,
                "repo_id": repo_id,
                "expires_at": expires_at,
            })
            inserted += 1

        await session.commit()

    return inserted


async def delete_expired_chunks() -> int:
    """Remove all chunks where expires_at < now()."""
    from sqlalchemy import text
    from apps.api.core.database import AsyncSessionFactory

    async with AsyncSessionFactory() as session:
        result = await session.execute(text(
            "DELETE FROM knowledge_chunks WHERE expires_at IS NOT NULL AND expires_at < now()"
        ))
        await session.commit()
        return result.rowcount


async def delete_tenant_source_chunks(tenant_id: str, source_type: str) -> int:
    """Remove all chunks of a given source_type for a tenant (used before re-ingestion)."""
    from sqlalchemy import text
    from apps.api.core.database import AsyncSessionFactory

    async with AsyncSessionFactory() as session:
        result = await session.execute(text(
            "DELETE FROM knowledge_chunks WHERE tenant_id = :tenant_id AND source_type = :source_type"
        ), {"tenant_id": tenant_id, "source_type": source_type})
        await session.commit()
        return result.rowcount

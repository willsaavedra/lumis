"""Async SQLAlchemy engine and session factory."""
from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Annotated

import structlog
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.sql import text

from apps.api.core.config import settings

log = structlog.get_logger(__name__)

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_pre_ping=True,
    poolclass=NullPool,  # Required for per-request RLS isolation
)

AsyncSessionFactory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


@asynccontextmanager
async def get_session_with_tenant(tenant_id: str) -> AsyncGenerator[AsyncSession, None]:
    """
    Context manager that creates a session and sets the RLS tenant context.
    All queries within this session will be filtered by tenant_id via RLS.
    """
    async with AsyncSessionFactory() as session:
        # Set RLS context — uses SET LOCAL so it applies only to this transaction
        await session.execute(text(f"SET LOCAL app.tenant_id = '{tenant_id}'"))
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_db(tenant_id: str) -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for authenticated endpoints."""
    async with get_session_with_tenant(tenant_id) as session:
        yield session


async def get_db_no_rls() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency for admin/internal endpoints without tenant RLS.
    Use ONLY with Depends() or `async for session in get_db_no_rls(): ...`.
    Do NOT use `async with get_db_no_rls()` — async generators are not context managers.
    """
    async with AsyncSessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def db_session_no_rls():
    """
    Session without RLS for manual `async with` blocks (webhooks, scripts).
    Same commit/rollback semantics as get_db_no_rls.
    """
    async with AsyncSessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

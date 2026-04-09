"""Tag-based visibility for repositories and analyses (team default tags)."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.scm import Repository
from apps.api.models.teams import RepositoryTag, Tag, Team, TeamMembership


async def effective_tag_ids_for_user(
    session: AsyncSession,
    *,
    tenant_id: str,
    user_id: uuid.UUID,
    membership_role: str,
) -> list[uuid.UUID] | None:
    """
    Return tag IDs that define which repositories a non-admin user may access.

    - admin: None (no extra filter — full tenant).
    - user with no team memberships: None (unrestricted — backward compatible).
    - user in one or more teams: union of those teams' default_tag_id values (non-empty list).
    """
    if membership_role == "admin":
        return None

    tid = uuid.UUID(tenant_id)
    q = (
        select(Team.default_tag_id)
        .join(TeamMembership, TeamMembership.team_id == Team.id)
        .where(
            TeamMembership.tenant_id == tid,
            TeamMembership.user_id == user_id,
        )
    )
    rows = (await session.execute(q)).scalars().all()
    ids = list({r for r in rows if r is not None})
    if not ids:
        return None
    return ids


def repository_visible_predicate(effective_tag_ids: list[uuid.UUID] | None) -> Any:
    """
    SQLAlchemy expression: repositories visible to a scoped user.

    - effective_tag_ids None: no restriction (use True in boolean context carefully — callers skip filter).
    - non-empty: EXISTS repository_tags matching repo and tag set.
    """
    if effective_tag_ids is None:
        return None
    return exists(
        select(RepositoryTag.tag_id).where(
            RepositoryTag.repository_id == Repository.id,
            RepositoryTag.tag_id.in_(effective_tag_ids),
        )
    )


async def load_tags_for_repositories(
    session: AsyncSession,
    tenant_id: str,
    repo_ids: list[uuid.UUID],
) -> dict[uuid.UUID, list[dict[str, str]]]:
    """Map repo_id -> [{key, value}, ...]."""
    if not repo_ids:
        return {}
    tid = uuid.UUID(tenant_id)
    q = (
        select(RepositoryTag.repository_id, Tag.key, Tag.value)
        .join(Tag, Tag.id == RepositoryTag.tag_id)
        .where(
            RepositoryTag.repository_id.in_(repo_ids),
            Tag.tenant_id == tid,
        )
    )
    rows = (await session.execute(q)).all()
    out: dict[uuid.UUID, list[dict[str, str]]] = {rid: [] for rid in repo_ids}
    for rid, k, v in rows:
        out[rid].append({"key": k, "value": v})
    return out


async def assert_repo_accessible(
    session: AsyncSession,
    *,
    tenant_id: str,
    user_id: uuid.UUID,
    membership_role: str,
    repo_id: uuid.UUID,
) -> bool:
    """Return True if user may access this repository."""
    eff = await effective_tag_ids_for_user(
        session, tenant_id=tenant_id, user_id=user_id, membership_role=membership_role
    )
    if eff is None:
        return True
    q = select(RepositoryTag.tag_id).where(
        RepositoryTag.repository_id == repo_id,
        RepositoryTag.tag_id.in_(eff),
    )
    return (await session.execute(q)).first() is not None

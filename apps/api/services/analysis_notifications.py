"""Send analysis completion notifications to team Slack / Microsoft Teams webhooks."""
from __future__ import annotations

import uuid
from typing import Any

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from apps.api.core.config import settings
from apps.api.core.security import decrypt_scm_token, encrypt_scm_token
from apps.api.models.analysis import AnalysisJob
from apps.api.models.scm import Repository
from apps.api.models.teams import RepositoryTag, Tag, Team

log = structlog.get_logger(__name__)

SLACK_TIMEOUT = httpx.Timeout(12.0)
USER_AGENT = "HorionAnalysisBot/1.0"


def analysis_report_url(job_id: str) -> str:
    base = settings.frontend_url.rstrip("/")
    return f"{base}/analyses/{job_id}"


async def resolve_team_for_repo(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    repo_id: uuid.UUID,
) -> Team | None:
    """Return the platform Team whose default tag is linked to this repository."""
    r = await session.execute(
        select(Team)
        .join(Tag, Tag.id == Team.default_tag_id)
        .join(RepositoryTag, RepositoryTag.tag_id == Tag.id)
        .where(
            RepositoryTag.repository_id == repo_id,
            Team.tenant_id == tenant_id,
        )
        .options(selectinload(Team.default_tag_row))
        .limit(1)
    )
    return r.scalar_one_or_none()


def _summarize_exec(exec_summary: dict[str, Any]) -> dict[str, Any]:
    fs = exec_summary.get("findings_summary") or {}
    sc = exec_summary.get("scores") or {}
    return {
        "findings_total": fs.get("total", 0),
        "findings_critical": fs.get("critical", 0),
        "findings_warning": fs.get("warning", 0),
        "findings_info": fs.get("info", 0),
        "score_global": sc.get("global"),
        "score_metrics": sc.get("metrics"),
        "score_logs": sc.get("logs"),
        "score_traces": sc.get("traces"),
    }


def build_slack_payload(
    *,
    repo_full_name: str,
    branch_ref: str | None,
    analysis_type: str,
    job_id: str,
    summary: dict[str, Any],
) -> dict[str, Any]:
    url = analysis_report_url(job_id)
    sg = summary.get("score_global")
    lines = [
        f"*Horion* — analysis completed",
        f"*Repository:* `{repo_full_name}`",
        f"*Type:* {analysis_type.replace('_', ' ')}",
    ]
    if branch_ref:
        lines.append(f"*Branch:* `{branch_ref}`")
    lines.extend(
        [
            f"*Findings:* {summary['findings_total']} total "
            f"({summary['findings_critical']} critical, {summary['findings_warning']} warning, {summary['findings_info']} info)",
        ]
    )
    if sg is not None:
        lines.append(f"*Global score:* {sg}/100")
    text = "\n".join(lines) + f"\n<{url}|Open full report in Horion>"
    return {
        "text": text,
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn", "text": text}},
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "View report", "emoji": True},
                        "url": url,
                        "style": "primary",
                    }
                ],
            },
        ],
    }


def build_teams_message_card(
    *,
    repo_full_name: str,
    branch_ref: str | None,
    analysis_type: str,
    job_id: str,
    summary: dict[str, Any],
) -> dict[str, Any]:
    url = analysis_report_url(job_id)
    sg = summary.get("score_global")
    facts = [
        {"name": "Repository", "value": repo_full_name},
        {"name": "Analysis type", "value": analysis_type.replace("_", " ")},
    ]
    if branch_ref:
        facts.append({"name": "Branch", "value": branch_ref})
    facts.extend(
        [
            {
                "name": "Findings",
                "value": (
                    f"{summary['findings_total']} total — "
                    f"{summary['findings_critical']} critical, "
                    f"{summary['findings_warning']} warning, "
                    f"{summary['findings_info']} info"
                ),
            },
        ]
    )
    if sg is not None:
        facts.append({"name": "Global score", "value": f"{sg}/100"})
    return {
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "summary": f"Horion: {repo_full_name} analysis complete",
        "themeColor": "0078D7",
        "title": "Analysis completed",
        "sections": [
            {
                "activityTitle": "Horion reliability analysis",
                "facts": facts,
                "markdown": True,
            }
        ],
        "potentialAction": [
            {
                "@type": "OpenUri",
                "name": "View full report",
                "targets": [{"os": "default", "uri": url}],
            }
        ],
    }


async def send_slack_incoming(webhook_url: str, payload: dict[str, Any]) -> None:
    async with httpx.AsyncClient(timeout=SLACK_TIMEOUT, headers={"User-Agent": USER_AGENT}) as client:
        r = await client.post(webhook_url, json=payload)
        r.raise_for_status()


async def send_teams_incoming(webhook_url: str, payload: dict[str, Any]) -> None:
    async with httpx.AsyncClient(timeout=SLACK_TIMEOUT, headers={"User-Agent": USER_AGENT}) as client:
        r = await client.post(webhook_url, json=payload)
        r.raise_for_status()


def build_slack_payload_fix_pr(
    *,
    repo_full_name: str,
    job_id: str,
    pr_url: str,
) -> dict[str, Any]:
    report_url = analysis_report_url(job_id)
    lines = [
        "*Horion* — observability fix PR opened",
        f"*Repository:* `{repo_full_name}`",
        f"*Pull request:* <{pr_url}|Open on GitHub>",
    ]
    text = "\n".join(lines) + f"\n<{report_url}|View analysis in Horion>"
    return {
        "text": text,
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn", "text": text}},
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Open PR", "emoji": True},
                        "url": pr_url,
                        "style": "primary",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Analysis report", "emoji": True},
                        "url": report_url,
                    },
                ],
            },
        ],
    }


def build_teams_message_card_fix_pr(
    *,
    repo_full_name: str,
    job_id: str,
    pr_url: str,
) -> dict[str, Any]:
    report_url = analysis_report_url(job_id)
    return {
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "summary": f"Horion: fix PR for {repo_full_name}",
        "themeColor": "276749",
        "title": "Observability fix PR opened",
        "sections": [
            {
                "activityTitle": "Horion reliability",
                "facts": [
                    {"name": "Repository", "value": repo_full_name},
                    {"name": "Pull request", "value": pr_url},
                ],
                "markdown": True,
            }
        ],
        "potentialAction": [
            {"@type": "OpenUri", "name": "Open PR", "targets": [{"os": "default", "uri": pr_url}]},
            {"@type": "OpenUri", "name": "View analysis", "targets": [{"os": "default", "uri": report_url}]},
        ],
    }


async def notify_fix_pr_created(*, job_id: str, pr_url: str) -> None:
    """
    Post to team Slack / Teams when a Horion-generated fix PR is created.
    Skips when team has no webhooks, notify_on_fix_pr is false, or repo has no linked team.
    """
    try:
        jid = uuid.UUID(job_id)
    except ValueError:
        log.warning("notify_fix_pr_invalid_uuid", job_id=job_id)
        return

    from apps.api.core.database import AsyncSessionFactory

    async with AsyncSessionFactory() as session:
        job_result = await session.execute(select(AnalysisJob).where(AnalysisJob.id == jid))
        job = job_result.scalar_one_or_none()
        if not job:
            return
        tenant_id = str(job.tenant_id)
        repo_id = str(job.repo_id)
        tid = job.tenant_id
        rid = job.repo_id

    from apps.api.core.database import get_session_with_tenant

    async with get_session_with_tenant(tenant_id) as session:
        team = await resolve_team_for_repo(session, tid, rid)
        if not team:
            log.debug("notify_fix_pr_no_team_for_repo", job_id=job_id, repo_id=repo_id)
            return
        if not team.notify_on_fix_pr:
            return

        slack_url = decrypt_scm_token(team.slack_webhook_encrypted)
        teams_url = decrypt_scm_token(team.msteams_webhook_encrypted)
        if not slack_url and not teams_url:
            return

        repo_result = await session.execute(select(Repository).where(Repository.id == rid))
        repo = repo_result.scalar_one_or_none()
        repo_name = repo.full_name if repo else repo_id

        team_id_str = str(team.id)
        slack_body = build_slack_payload_fix_pr(
            repo_full_name=repo_name,
            job_id=job_id,
            pr_url=pr_url,
        )
        teams_body = build_teams_message_card_fix_pr(
            repo_full_name=repo_name,
            job_id=job_id,
            pr_url=pr_url,
        )

    if slack_url:
        try:
            await send_slack_incoming(slack_url, slack_body)
            log.info("notify_fix_pr_slack_sent", job_id=job_id, team_id=team_id_str)
        except Exception as e:
            log.warning("notify_fix_pr_slack_failed", job_id=job_id, error=str(e))
    if teams_url:
        try:
            await send_teams_incoming(teams_url, teams_body)
            log.info("notify_fix_pr_teams_sent", job_id=job_id, team_id=team_id_str)
        except Exception as e:
            log.warning("notify_fix_pr_teams_failed", job_id=job_id, error=str(e))


async def notify_analysis_completed(
    *,
    job_id: str,
    tenant_id: str,
    repo_id: str,
    exec_summary: dict[str, Any],
) -> None:
    """
    Load job/repo/team webhooks and POST to Slack/Teams. Errors are logged only.
    Skips when analysis_type is 'context' or team has no webhooks / notify disabled.
    """
    try:
        tid = uuid.UUID(tenant_id)
        jid = uuid.UUID(job_id)
        rid = uuid.UUID(repo_id)
    except ValueError:
        log.warning("notify_invalid_uuid", job_id=job_id)
        return

    from apps.api.core.database import get_session_with_tenant

    async with get_session_with_tenant(tenant_id) as session:
        job_result = await session.execute(select(AnalysisJob).where(AnalysisJob.id == jid))
        job = job_result.scalar_one_or_none()
        if not job:
            return
        if job.analysis_type == "context":
            return

        team = await resolve_team_for_repo(session, tid, rid)
        if not team:
            log.debug("notify_no_team_for_repo", job_id=job_id, repo_id=repo_id)
            return
        if not team.notify_on_analysis_complete:
            return

        slack_url = decrypt_scm_token(team.slack_webhook_encrypted)
        teams_url = decrypt_scm_token(team.msteams_webhook_encrypted)
        if not slack_url and not teams_url:
            return

        repo_result = await session.execute(select(Repository).where(Repository.id == rid))
        repo = repo_result.scalar_one_or_none()
        repo_name = repo.full_name if repo else repo_id

        summ = _summarize_exec(exec_summary)
        branch_ref = job.branch_ref

        team_id_str = str(team.id)
        slack_body = build_slack_payload(
            repo_full_name=repo_name,
            branch_ref=branch_ref,
            analysis_type=job.analysis_type,
            job_id=job_id,
            summary=summ,
        )
        teams_body = build_teams_message_card(
            repo_full_name=repo_name,
            branch_ref=branch_ref,
            analysis_type=job.analysis_type,
            job_id=job_id,
            summary=summ,
        )

    if slack_url:
        try:
            await send_slack_incoming(slack_url, slack_body)
            log.info("notify_slack_sent", job_id=job_id, team_id=team_id_str)
        except Exception as e:
            log.warning("notify_slack_failed", job_id=job_id, error=str(e))
    if teams_url:
        try:
            await send_teams_incoming(teams_url, teams_body)
            log.info("notify_teams_sent", job_id=job_id, team_id=team_id_str)
        except Exception as e:
            log.warning("notify_teams_failed", job_id=job_id, error=str(e))


def encrypt_webhook_url(url: str | None) -> bytes | None:
    if not url or not str(url).strip():
        return None
    return encrypt_scm_token(str(url).strip())


def webhook_url_hint(url: str | None) -> str | None:
    if not url:
        return None
    u = url.strip()
    if len(u) <= 4:
        return "****"
    return f"…{u[-4:]}"


async def send_test_notification(
    *,
    slack_webhook_encrypted: bytes | None,
    msteams_webhook_encrypted: bytes | None,
    channel: str,
) -> None:
    """channel: 'slack' | 'teams' | 'both'"""
    slack_url = decrypt_scm_token(slack_webhook_encrypted)
    teams_url = decrypt_scm_token(msteams_webhook_encrypted)
    base = settings.frontend_url.rstrip("/")
    if channel in ("slack", "both") and slack_url:
        slack_test = {
            "text": f"*Horion test message*\nIf you see this, the Slack webhook for this team is configured correctly.\n<{base}/analyses|Open Horion analyses>",
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "*Horion test message*\nIf you see this, the Slack webhook for this team is configured correctly.",
                    },
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Open Horion", "emoji": True},
                            "url": f"{base}/analyses",
                        }
                    ],
                },
            ],
        }
        await send_slack_incoming(slack_url, slack_test)
    if channel in ("teams", "both") and teams_url:
        teams_test = {
            "@type": "MessageCard",
            "@context": "https://schema.org/extensions",
            "summary": "Horion webhook test",
            "themeColor": "0078D7",
            "title": "Horion test message",
            "sections": [
                {
                    "activityTitle": "Teams webhook",
                    "activitySubtitle": "If you see this card, the Microsoft Teams webhook for this team is configured correctly.",
                    "markdown": True,
                }
            ],
            "potentialAction": [
                {
                    "@type": "OpenUri",
                    "name": "Open Horion",
                    "targets": [{"os": "default", "uri": f"{base}/analyses"}],
                }
            ],
        }
        await send_teams_incoming(teams_url, teams_test)

"""Transactional email service using AWS SES via aioboto3."""
from __future__ import annotations

import os
from pathlib import Path
from string import Template
from typing import Any

import structlog

from apps.api.core.config import settings

log = structlog.get_logger(__name__)

TEMPLATES_DIR = Path(__file__).parent.parent / "email_templates"

# Base layout wraps all individual templates.
_BASE_TEMPLATE: str | None = None


def _get_base() -> str:
    global _BASE_TEMPLATE
    if _BASE_TEMPLATE is None:
        _BASE_TEMPLATE = (TEMPLATES_DIR / "base.html").read_text()
    return _BASE_TEMPLATE


def render_template(template_name: str, context: dict[str, Any]) -> str:
    """Load an individual template, inject context, then wrap in base layout."""
    inner_path = TEMPLATES_DIR / template_name
    inner_raw = inner_path.read_text()
    # Apply context to inner first
    inner_html = Template(inner_raw).safe_substitute(context)
    # Wrap in base
    base_html = Template(_get_base()).safe_substitute({"content": inner_html, **context})
    return base_html


async def send_email(
    to: str | list[str],
    subject: str,
    html: str,
    text: str | None = None,
) -> bool:
    """
    Send an email via AWS SES.
    Returns True on success, False on failure (errors are logged but never raised).
    """
    if not settings.aws_ses_access_key_id or not settings.aws_ses_secret_access_key:
        log.warning("ses_not_configured", subject=subject)
        return False

    recipients = [to] if isinstance(to, str) else to
    if not recipients:
        return False

    source = f"{settings.aws_ses_from_name} <{settings.aws_ses_from_address}>"
    body: dict[str, Any] = {"Html": {"Charset": "UTF-8", "Data": html}}
    if text:
        body["Text"] = {"Charset": "UTF-8", "Data": text}

    try:
        import aioboto3  # type: ignore[import-untyped]

        session = aioboto3.Session(
            aws_access_key_id=settings.aws_ses_access_key_id,
            aws_secret_access_key=settings.aws_ses_secret_access_key,
            region_name=settings.aws_ses_region,
        )
        async with session.client("ses") as client:
            await client.send_email(
                Source=source,
                Destination={"ToAddresses": recipients},
                Message={
                    "Subject": {"Charset": "UTF-8", "Data": subject},
                    "Body": body,
                },
            )
        log.info("email_sent", to=recipients, subject=subject)
        return True
    except Exception as exc:
        log.error("email_send_failed", to=recipients, subject=subject, error=str(exc))
        return False


# ── Convenience senders ───────────────────────────────────────────────────────

async def send_verify_email(to: str, verify_url: str) -> bool:
    html = render_template("verify_email.html", {"verify_url": verify_url, "email": to})
    return await send_email(to, "Confirm your Horion account", html)


async def send_welcome_email(to: str, first_name: str = "") -> bool:
    display = first_name.strip() if first_name.strip() else to.split("@")[0]
    html = render_template("welcome.html", {"display_name": display, "dashboard_url": settings.frontend_url})
    return await send_email(to, "Welcome to Horion", html)


async def send_reset_password_email(to: str, reset_url: str) -> bool:
    html = render_template("reset_password.html", {"reset_url": reset_url, "email": to})
    return await send_email(to, "Reset your Horion password", html)


async def send_analysis_complete_email(
    to: list[str],
    *,
    repo_full_name: str,
    job_id: str,
    branch_ref: str | None,
    analysis_type: str,
    score_global: int | None,
    findings_critical: int,
    findings_warning: int,
    findings_total: int,
    exec_summary_snippet: str,
) -> bool:
    from apps.api.services.analysis_notifications import analysis_report_url
    report_url = analysis_report_url(job_id)
    grade, grade_color = _score_grade(score_global)
    html = render_template("analysis_complete.html", {
        "repo_full_name": repo_full_name,
        "branch_ref": branch_ref or "—",
        "analysis_type": analysis_type.replace("_", " "),
        "score_global": str(score_global) if score_global is not None else "—",
        "grade": grade,
        "grade_color": grade_color,
        "findings_critical": findings_critical,
        "findings_warning": findings_warning,
        "findings_total": findings_total,
        "exec_summary_snippet": exec_summary_snippet[:300] if exec_summary_snippet else "",
        "report_url": report_url,
    })
    return await send_email(to, f"Analysis complete — {repo_full_name}", html)


async def send_fix_pr_email(
    to: list[str],
    *,
    repo_full_name: str,
    job_id: str,
    pr_url: str,
) -> bool:
    from apps.api.services.analysis_notifications import analysis_report_url
    report_url = analysis_report_url(job_id)
    html = render_template("fix_pr_created.html", {
        "repo_full_name": repo_full_name,
        "pr_url": pr_url,
        "report_url": report_url,
    })
    return await send_email(to, f"Fix PR opened — {repo_full_name}", html)


def _score_grade(score: int | None) -> tuple[str, str]:
    if score is None:
        return "—", "#888880"
    if score >= 90:
        return "A", "#276749"
    if score >= 75:
        return "B", "#1a4480"
    if score >= 60:
        return "C", "#b7791f"
    return "D", "#c0392b"

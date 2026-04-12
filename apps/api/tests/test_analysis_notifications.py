"""Unit tests for analysis Slack/Teams notification payloads."""
from __future__ import annotations

from apps.api.services.analysis_notifications import (
    analysis_report_url,
    build_slack_payload,
    build_slack_payload_fix_pr,
    build_teams_message_card,
    build_teams_message_card_fix_pr,
    webhook_url_hint,
)


def test_analysis_report_url_uses_frontend():
    url = analysis_report_url("abc-123-def")
    assert url.endswith("/analyses/abc-123-def")
    assert url.startswith("http")


def test_webhook_url_hint():
    assert webhook_url_hint(None) is None
    assert webhook_url_hint("https://hooks.slack.com/x/y/z") == "…/z"


def test_build_slack_payload_contains_repo_and_link():
    payload = build_slack_payload(
        repo_full_name="acme/api",
        branch_ref="main",
        analysis_type="repository",
        job_id="11111111-1111-1111-1111-111111111111",
        summary={
            "findings_total": 3,
            "findings_critical": 1,
            "findings_warning": 2,
            "findings_info": 0,
            "score_global": 77,
        },
    )
    assert "acme/api" in payload["text"]
    assert "77/100" in payload["text"]
    link = analysis_report_url("11111111-1111-1111-1111-111111111111")
    assert link in payload["text"]


def test_build_teams_message_card_structure():
    card = build_teams_message_card(
        repo_full_name="acme/api",
        branch_ref=None,
        analysis_type="quick",
        job_id="22222222-2222-2222-2222-222222222222",
        summary={
            "findings_total": 0,
            "findings_critical": 0,
            "findings_warning": 0,
            "findings_info": 0,
            "score_global": None,
        },
    )
    assert card["@type"] == "MessageCard"
    assert "potentialAction" in card
    assert any("acme/api" in str(f.get("value", "")) for f in card["sections"][0]["facts"])


def test_build_slack_payload_fix_pr_contains_pr_and_report_links():
    payload = build_slack_payload_fix_pr(
        repo_full_name="acme/api",
        job_id="33333333-3333-3333-3333-333333333333",
        pr_url="https://github.com/acme/api/pull/42",
    )
    assert "fix PR" in payload["text"].lower() or "PR opened" in payload["text"]
    assert "github.com/acme/api/pull/42" in payload["text"]
    report = analysis_report_url("33333333-3333-3333-3333-333333333333")
    assert report in payload["text"]


def test_build_teams_message_card_fix_pr_structure():
    card = build_teams_message_card_fix_pr(
        repo_full_name="acme/api",
        job_id="44444444-4444-4444-4444-444444444444",
        pr_url="https://github.com/acme/api/pull/99",
    )
    assert card["@type"] == "MessageCard"
    assert len(card["potentialAction"]) >= 2
    uris = str(card)
    assert "github.com/acme/api/pull/99" in uris

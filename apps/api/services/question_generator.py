"""Generate contextual pre-analysis questions with pre-defined answer options."""
from __future__ import annotations

from dataclasses import dataclass, field

from apps.api.models.scm import Repository


@dataclass
class Question:
    id: str
    text: str
    options: list[str]
    multi: bool = False


_IAC_LANGUAGES = frozenset({"terraform", "hcl", "helm", "bicep", "pulumi"})


def _repo_languages(repo: Repository) -> list[str]:
    return [l.lower() for l in (repo.language or [])]


def _has_payment_domain(repo: Repository) -> bool:
    summary = (repo.context_summary or "").lower()
    name = (repo.full_name or "").lower()
    return any(kw in summary or kw in name for kw in ("payment", "billing", "checkout", "stripe", "invoice"))


def _has_otel_but_no_backend(repo: Repository) -> bool:
    return (repo.instrumentation or "").lower() in ("otel", "mixed") and not repo.observability_backend


def _is_iac_repo(repo: Repository) -> bool:
    if (repo.repo_type or "").lower() == "iac":
        return True
    if repo.iac_provider:
        return True
    return any(l in _IAC_LANGUAGES for l in _repo_languages(repo))


def generate_pre_run_questions(repo: Repository, *, is_first_full: bool) -> list[dict]:
    """
    Return 0-3 contextual questions based on what we know about the repo.
    Each question has pre-defined options the user can pick from.
    Returns serializable dicts (not dataclass) for JSONB storage.
    """
    questions: list[Question] = []

    if is_first_full:
        questions.append(Question(
            id="criticality",
            text="What is this service's production criticality?",
            options=[
                "Critical (customer-facing SLA)",
                "High (internal but revenue-impacting)",
                "Standard",
                "Internal only / non-production",
            ],
        ))

    if _has_payment_domain(repo):
        questions.append(Question(
            id="pci",
            text="Is this service PCI-scoped?",
            options=["Yes", "No", "Partial"],
        ))

    if _has_otel_but_no_backend(repo) and not _is_iac_repo(repo):
        questions.append(Question(
            id="obs_backend",
            text="What is your target observability backend?",
            options=["OpenTelemetry (OTLP)", "Datadog", "Both", "Not decided yet"],
        ))

    if not repo.instrumentation and not _is_iac_repo(repo) and is_first_full:
        questions.append(Question(
            id="obs_backend",
            text="What observability backend are you targeting?",
            options=["OpenTelemetry (OTLP)", "Datadog", "Prometheus/Grafana", "Not decided yet"],
        ))

    # De-duplicate by id (obs_backend may appear from two paths)
    seen: set[str] = set()
    unique: list[Question] = []
    for q in questions:
        if q.id not in seen:
            seen.add(q.id)
            unique.append(q)

    return [
        {"id": q.id, "text": q.text, "options": q.options, "multi": q.multi}
        for q in unique[:3]
    ]

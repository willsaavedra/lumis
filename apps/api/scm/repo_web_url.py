"""Derive a browser URL for a repository from SCM metadata."""
from __future__ import annotations

import logging
from urllib.parse import urlparse, urlunparse

from opentelemetry import trace
from opentelemetry.trace import StatusCode

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


def repo_web_url(*, scm_type: str, full_name: str, clone_url: str | None) -> str:
    """
    Build an HTTPS URL to open the repo in the browser.
    Strips .git and embedded credentials from clone URLs when present.
    """
    with tracer.start_as_current_span("repo_web_url") as span:
        span.set_attribute("scm_type", scm_type)
        span.set_attribute("full_name", full_name)
        span.set_attribute("has_clone_url", clone_url is not None)
        
        if clone_url:
            u = clone_url.strip()
            if u.startswith(("https://", "http://")):
                base = u.removesuffix(".git")
                try:
                    parsed = urlparse(base)
                    if "@" in parsed.netloc:
                        netloc = parsed.netloc.split("@")[-1]
                        base = urlunparse((parsed.scheme, netloc, parsed.path, "", "", ""))
                except Exception as exc:
                    span.record_exception(exc)
                    span.set_status(StatusCode.ERROR, str(exc))
                    logger.error("url_parse_failed", clone_url=clone_url, exc_info=True)
                    pass
                return base
            if u.startswith("git@github.com:"):
                path = u.split(":", 1)[1].removesuffix(".git")
                return f"https://github.com/{path}"
            if u.startswith("git@gitlab.com:"):
                path = u.split(":", 1)[1].removesuffix(".git")
                return f"https://gitlab.com/{path}"
            if u.startswith("git@bitbucket.org:"):
                path = u.split(":", 1)[1].removesuffix(".git")
                return f"https://bitbucket.org/{path}"

    if "/" not in full_name:
        return f"https://github.com/{full_name}"

    if scm_type == "github":
        return f"https://github.com/{full_name}"
    if scm_type == "gitlab":
        return f"https://gitlab.com/{full_name}"
    if scm_type == "bitbucket":
        return f"https://bitbucket.org/{full_name}"
    if scm_type == "azure_devops":
        parts = full_name.split("/")
        if len(parts) >= 3:
            org, project, repo = parts[0], parts[1], "/".join(parts[2:])
            return f"https://dev.azure.com/{org}/{project}/_git/{repo}"
        return f"https://dev.azure.com/{full_name}"

    return f"https://github.com/{full_name}"

"""Abstract SCM adapter interface."""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class SCMAdapter(ABC):
    @abstractmethod
    def verify_webhook_signature(self, payload: bytes, signature: str) -> bool: ...

    @abstractmethod
    def normalize_event(self, raw_payload: dict, event: str) -> Any | None: ...

    @abstractmethod
    async def clone_repo(self, installation_id: str, full_name: str, ref: str, target: Path) -> Path: ...

    @abstractmethod
    async def get_changed_files(self, installation_id: str, full_name: str, pr_number: int) -> list[str]: ...

    @abstractmethod
    async def post_report(self, installation_id: str, full_name: str, pr_number: int, report: str) -> None: ...

    @abstractmethod
    async def list_installation_repos(self, installation_id: int) -> list[dict]: ...

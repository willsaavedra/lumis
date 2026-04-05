"""Test fixtures."""
import pytest
import pytest_asyncio
from httpx import AsyncClient

from apps.api.main import app


@pytest_asyncio.fixture
async def client() -> AsyncClient:
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac

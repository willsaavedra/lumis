"""Auth endpoint tests."""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_signup_creates_tenant(client: AsyncClient) -> None:
    response = await client.post("/auth/signup", json={
        "email": "test@example.com",
        "password": "testpassword123",
        "company_name": "Test Corp",
    })
    assert response.status_code == 201
    data = response.json()
    assert "api_key" in data
    assert "tenant_id" in data
    assert len(data["api_key"]) > 10


@pytest.mark.asyncio
async def test_signup_duplicate_email(client: AsyncClient) -> None:
    await client.post("/auth/signup", json={
        "email": "dup@example.com",
        "password": "testpassword123",
        "company_name": "Corp A",
    })
    response = await client.post("/auth/signup", json={
        "email": "dup@example.com",
        "password": "testpassword123",
        "company_name": "Corp B",
    })
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_health(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

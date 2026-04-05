"""Observability vendor connection endpoints."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy import select

from apps.api.core.database import get_session_with_tenant
from apps.api.core.deps import CurrentUser
from apps.api.models.vendor import VendorConnection

router = APIRouter()

SUPPORTED_VENDORS = ["datadog", "grafana", "prometheus", "dynatrace", "splunk"]


class VendorConnectionResponse(BaseModel):
    id: str
    vendor: str
    display_name: str | None
    api_url: str | None
    created_at: str


class CreateVendorRequest(BaseModel):
    vendor: str
    display_name: str | None = None
    api_key: str | None = None
    api_url: str | None = None
    extra_config: dict | None = None


@router.get("", response_model=list[VendorConnectionResponse])
async def list_vendors(current: CurrentUser) -> list[VendorConnectionResponse]:
    user, tenant_id, _ = current
    async with get_session_with_tenant(tenant_id) as session:
        result = await session.execute(
            select(VendorConnection).where(VendorConnection.tenant_id == uuid.UUID(tenant_id))
        )
        vendors = result.scalars().all()
    return [
        VendorConnectionResponse(
            id=str(v.id),
            vendor=v.vendor,
            display_name=v.display_name,
            api_url=v.api_url,
            created_at=v.created_at.isoformat(),
        )
        for v in vendors
    ]


@router.post("", response_model=VendorConnectionResponse, status_code=status.HTTP_201_CREATED)
async def create_vendor(body: CreateVendorRequest, current: CurrentUser) -> VendorConnectionResponse:
    user, tenant_id, _ = current
    if body.vendor not in SUPPORTED_VENDORS:
        raise HTTPException(status_code=400, detail=f"Unsupported vendor: {body.vendor}")
    async with get_session_with_tenant(tenant_id) as session:
        # Upsert: one connection per vendor per tenant
        existing = (await session.execute(
            select(VendorConnection).where(
                VendorConnection.tenant_id == uuid.UUID(tenant_id),
                VendorConnection.vendor == body.vendor,
            )
        )).scalar_one_or_none()
        if existing:
            if body.api_key:
                existing.api_key = body.api_key
            if body.api_url is not None:
                existing.api_url = body.api_url
            if body.display_name:
                existing.display_name = body.display_name
            if body.extra_config:
                existing.extra_config = body.extra_config
            v = existing
        else:
            v = VendorConnection(
                tenant_id=uuid.UUID(tenant_id),
                vendor=body.vendor,
                display_name=body.display_name,
                api_key=body.api_key,
                api_url=body.api_url,
                extra_config=body.extra_config,
            )
            session.add(v)
        await session.flush()
    return VendorConnectionResponse(
        id=str(v.id),
        vendor=v.vendor,
        display_name=v.display_name,
        api_url=v.api_url,
        created_at=v.created_at.isoformat(),
    )


@router.delete("/{vendor_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_vendor(vendor_id: str, current: CurrentUser) -> None:
    user, tenant_id, _ = current
    async with get_session_with_tenant(tenant_id) as session:
        result = await session.execute(
            select(VendorConnection).where(
                VendorConnection.id == uuid.UUID(vendor_id),
                VendorConnection.tenant_id == uuid.UUID(tenant_id),
            )
        )
        v = result.scalar_one_or_none()
        if not v:
            raise HTTPException(status_code=404, detail="Vendor connection not found")
        await session.delete(v)

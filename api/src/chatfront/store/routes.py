"""The website store in the console (Pro plan): connect it with a read-only key, choose the
hour of the daily report, read it now, and see today's numbers. The key is sealed at once
and never sent back; the console only learns that one is set."""

from __future__ import annotations

import contextlib
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from chatfront.audit.service import Actor, ActorType, record
from chatfront.books.ledger import today
from chatfront.core.errors import AppError, NotFound
from chatfront.core.models import Tenant
from chatfront.core.secretbox import seal
from chatfront.owner.rights import Can
from chatfront.owner.routes import ServicesDep, needs, needs_feature
from chatfront.owner.sessions import OwnerSession
from chatfront.owner.subscription import Feature
from chatfront.store.clients import SHOPIFY, WOOCOMMERCE, StoreError, check_public, normal_url
from chatfront.store.models import StoreConnection, StoreOrder
from chatfront.store.service import day_summary, sync

router = APIRouter(prefix="/api/owner/store", dependencies=[needs_feature(Feature.REPORTS)])
SettingsDep = Annotated[OwnerSession, needs(Can.SETTINGS)]


class StoreIn(BaseModel):
    platform: Literal["shopify", "woocommerce"]
    store_url: str = Field(min_length=4, max_length=200)
    key: str = Field("", max_length=200)  # empty keeps the saved one
    secret: str = Field("", max_length=200)  # WooCommerce only
    report_hour: int = Field(21, ge=0, le=23)


class Today(BaseModel):
    orders: int
    sales: int
    paid: int
    cod: int
    pending: int
    closed: int
    unsent: int


class StoreOut(BaseModel):
    connected: bool
    platform: str | None = None
    store_url: str | None = None
    key_set: bool = False
    report_hour: int = 21
    synced_at: datetime | None = None
    last_error: str | None = None
    today: Today | None = None


async def _out(services: ServicesDep, session: OwnerSession) -> StoreOut:
    async with services.db.tenant(session.tenant_id) as db:
        tenant = await db.get(Tenant, session.tenant_id)
        link = await db.scalar(select(StoreConnection))
        if tenant is None:
            raise NotFound("shop")
        if link is None:
            return StoreOut(connected=False)
        summary = await day_summary(db, tenant, today(tenant))
        return StoreOut(
            connected=True,
            platform=link.platform,
            store_url=link.store_url,
            key_set=True,
            report_hour=link.report_hour,
            synced_at=link.synced_at,
            last_error=link.last_error,
            today=Today(
                orders=summary.orders,
                sales=summary.sales,
                paid=summary.paid,
                cod=summary.cod,
                pending=summary.pending,
                closed=summary.closed,
                unsent=summary.unsent,
            ),
        )


@router.get("")
async def get_store(session: SettingsDep, services: ServicesDep) -> StoreOut:
    return await _out(services, session)


@router.put("")
async def save_store(body: StoreIn, session: SettingsDep, services: ServicesDep) -> StoreOut:
    url = normal_url(body.platform, body.store_url)
    await check_public(url)
    secret_key = services.settings.secret_key.get_secret_value()
    async with services.db.tenant(session.tenant_id) as db:
        link = await db.scalar(select(StoreConnection))
        changed = link is None or link.platform != body.platform or link.store_url != url
        if changed and not body.key.strip():
            raise StoreError("Paste the store's read-only key")
        if body.platform == WOOCOMMERCE and changed and not body.secret.strip():
            raise StoreError("Paste the WooCommerce consumer secret too")
        if changed:
            await db.execute(delete(StoreOrder))  # another store's orders do not carry over
        if link is None:
            link = StoreConnection(
                tenant_id=session.tenant_id, platform=body.platform, store_url=url, key_sealed=""
            )
            db.add(link)
        if changed:
            link.synced_at = None
        link.platform, link.store_url, link.report_hour = body.platform, url, body.report_hour
        if body.key.strip():
            link.key_sealed = seal(body.key.strip(), secret_key)
        if body.secret.strip():
            link.secret_sealed = seal(body.secret.strip(), secret_key)
        if body.platform == SHOPIFY:
            link.secret_sealed = None
        link.last_error = None
        await record(
            db,
            session.tenant_id,
            Actor(ActorType.STAFF, str(session.staff_id)),
            "store.connect",
            entity=("tenant", str(session.tenant_id)),
            data={"platform": body.platform, "store_url": url, "report_hour": body.report_hour},
        )
    return await _out(services, session)


@router.post("/sync")
async def sync_now(session: SettingsDep, services: ServicesDep) -> StoreOut:
    async with services.db.tenant(session.tenant_id) as db:
        if await db.scalar(select(StoreConnection)) is None:
            raise NotFound("store")
    with contextlib.suppress(
        AppError
    ):  # kept on the connection as last_error; the console shows it
        await sync(services, session.tenant_id)
    return await _out(services, session)


@router.delete("")
async def remove_store(session: SettingsDep, services: ServicesDep) -> StoreOut:
    async with services.db.tenant(session.tenant_id) as db:
        await db.execute(delete(StoreOrder))
        await db.execute(delete(StoreConnection))
        await record(
            db,
            session.tenant_id,
            Actor(ActorType.STAFF, str(session.staff_id)),
            "store.remove",
            entity=("tenant", str(session.tenant_id)),
        )
    return StoreOut(connected=False)

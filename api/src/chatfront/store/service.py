"""Keeping a business's website orders up to date, and the report the owner reads.

Every 15 minutes each connected store is read for the orders changed since the last read.
Once a day, at the hour the owner chose, the owner gets the day's report on WhatsApp; the
owner can also ask for it ("aaj ka scene", "report", "pending cod") at any time.
"""

from __future__ import annotations

import contextlib
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, Protocol

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from chatfront.books.ledger import today, zone
from chatfront.channels.language import staff_language
from chatfront.core.clock import utcnow
from chatfront.core.countries import get_pack, shop_money
from chatfront.core.errors import AppError
from chatfront.core.i18n import t
from chatfront.core.models import Tenant
from chatfront.core.provisioning import owner_of
from chatfront.core.secretbox import unseal
from chatfront.jobs.cron import Periodic
from chatfront.jobs.queue import JobContext, enqueue
from chatfront.owner.subscription import Feature, features_of
from chatfront.stock import notices
from chatfront.store.clients import fetch_orders, store_client
from chatfront.store.models import StoreConnection, StoreOrder

if TYPE_CHECKING:
    import httpx
    from sqlalchemy.ext.asyncio import AsyncSession

    from chatfront.core.db import Database
    from chatfront.core.settings import Settings
    from chatfront.services import Services


class Deps(Protocol):
    """What reading a store needs: the app's services, or the owner's assistant."""

    @property
    def db(self) -> Database: ...
    @property
    def http(self) -> httpx.AsyncClient: ...
    @property
    def settings(self) -> Settings: ...


SYNC_ALL_JOB, SYNC_JOB = "store.sync_all", "store.sync"
REPORTS_JOB, REPORT_JOB = "store.reports", "store.report"
SYNC_EVERY, REPORTS_EVERY = timedelta(minutes=15), timedelta(hours=1)
FIRST_READ = timedelta(days=30)  # how far back the first read of a store goes
OVERLAP = timedelta(minutes=5)  # each read starts a little before the last one ended
COD_DAYS = 30
CLOSED = ("cancelled", "refunded")
_TODAY = re.compile(
    r"\b(report|aaj\s*ka\s*scene|aaj\s*ki\s*(sale|report)|today'?s?\s*(sales|report)|sales\s*today)\b",
    re.IGNORECASE,
)
_COD = re.compile(r"\b(pending\s*cod|cod\s*pending|cash\s*on\s*delivery)\b", re.IGNORECASE)


def periodic() -> list[Periodic]:
    return [
        Periodic("store-sync", SYNC_EVERY, SYNC_ALL_JOB),
        Periodic("store-reports", REPORTS_EVERY, REPORTS_JOB),
    ]


def asks(text: str | None) -> str | None:
    """What the owner asks for in so many words: "cod", "today", or None."""
    words = text or ""
    if _COD.search(words):
        return "cod"
    if _TODAY.search(words):
        return "today"
    return None


async def sync(services: Deps, tenant_id: uuid.UUID) -> int:
    """Read the store for the orders changed since the last read; returns how many came."""
    secret = services.settings.secret_key.get_secret_value()
    async with services.db.tenant(tenant_id) as session:
        tenant = await session.get(Tenant, tenant_id)
        link = await session.scalar(select(StoreConnection))
        if tenant is None or link is None:
            return 0
        platform, url = link.platform, link.store_url
        key = unseal(link.key_sealed, secret)
        consumer_secret = unseal(link.secret_sealed, secret) if link.secret_sealed else None
        started = utcnow()
        since = (link.synced_at - OVERLAP) if link.synced_at else started - FIRST_READ
        digits = get_pack(tenant.country).minor_digits
    try:
        async with store_client() as http:
            orders = await fetch_orders(http, platform, url, key, consumer_secret, since, digits)
    except AppError as exc:
        async with services.db.tenant(tenant_id) as session:
            link = await session.scalar(select(StoreConnection))
            if link is not None:
                link.last_error = exc.message[:300]
        raise
    async with services.db.tenant(tenant_id) as session:
        for order in orders:
            values = {
                "tenant_id": tenant_id,
                "external_id": order.external_id,
                "number": order.number,
                "placed_at": order.placed_at,
                "total": order.total,
                "currency": order.currency,
                "status": order.status,
                "cod": order.cod,
                "fulfilled": order.fulfilled,
            }
            await session.execute(
                insert(StoreOrder)
                .values(id=uuid.uuid4(), **values)
                .on_conflict_do_update(
                    index_elements=["tenant_id", "external_id"],
                    set_={k: v for k, v in values.items() if k not in ("tenant_id", "external_id")},
                )
            )
        link = await session.scalar(select(StoreConnection))
        if link is not None:
            link.synced_at, link.last_error = started, None
    return len(orders)


@dataclass(frozen=True, slots=True)
class DaySummary:
    day: date
    orders: int
    sales: int
    paid: int
    cod: int
    pending: int
    closed: int
    unsent: int


async def day_summary(session: AsyncSession, tenant: Tenant, day: date) -> DaySummary:
    start = datetime.combine(day, time.min, zone(tenant))
    rows = list(
        await session.scalars(
            select(StoreOrder).where(
                StoreOrder.placed_at >= start, StoreOrder.placed_at < start + timedelta(days=1)
            )
        )
    )
    open_ = [o for o in rows if o.status not in CLOSED]
    return DaySummary(
        day=day,
        orders=len(rows),
        sales=sum(o.total for o in open_),
        paid=sum(o.status == "paid" for o in open_),
        cod=sum(o.cod for o in open_),
        pending=sum(o.status == "pending" for o in open_),
        closed=len(rows) - len(open_),
        unsent=sum(not o.fulfilled for o in open_),
    )


def report_text(tenant: Tenant, summary: DaySummary, lang: str) -> str:
    return t(
        "store.report",
        lang,
        day=summary.day.strftime("%d %b"),
        orders=summary.orders,
        sales=shop_money(tenant, summary.sales, lang),
        paid=summary.paid,
        cod=summary.cod,
        pending=summary.pending,
        closed=summary.closed,
        unsent=summary.unsent,
    )


async def cod_text(session: AsyncSession, tenant: Tenant, lang: str) -> str:
    since = utcnow() - timedelta(days=COD_DAYS)
    waiting = list(
        await session.scalars(
            select(StoreOrder).where(
                StoreOrder.cod.is_(True),
                StoreOrder.fulfilled.is_(False),
                StoreOrder.status.not_in(CLOSED),
                StoreOrder.placed_at >= since,
            )
        )
    )
    amount = shop_money(tenant, sum(o.total for o in waiting), lang)
    return t("store.pending_cod", lang, count=len(waiting), amount=amount)


async def answer(services: Deps, tenant: Tenant, asked: str, lang: str) -> str | None:
    """The owner's question about the website, answered from the latest read; None when no
    store is connected (then the question goes on to the rest of the owner's assistant)."""
    async with services.db.tenant(tenant.id) as session:
        link = await session.scalar(select(StoreConnection))
    if link is None:
        return None
    with contextlib.suppress(
        AppError
    ):  # answer from the last good read; the console shows the error
        await sync(services, tenant.id)
    async with services.db.tenant(tenant.id) as session:
        if asked == "cod":
            return await cod_text(session, tenant, lang)
        return report_text(tenant, await day_summary(session, tenant, today(tenant)), lang)


# -- jobs ------------------------------------------------------------------------------------


async def _connected(services: Services) -> list[tuple[Tenant, StoreConnection]]:
    async with services.db.system() as session:
        rows = await session.execute(
            select(Tenant, StoreConnection).join(
                StoreConnection, StoreConnection.tenant_id == Tenant.id
            )
        )
        return [
            (tenant, link)
            for tenant, link in rows.all()
            if Feature.REPORTS in features_of(tenant, commerce=services.settings.commerce)
        ]


async def sync_all_job(ctx: JobContext) -> None:
    services: Services = ctx.services
    connected = await _connected(services)
    async with services.db.system() as session:
        slot = utcnow().replace(second=0, microsecond=0).isoformat()
        for tenant, _ in connected:
            await enqueue(
                session, SYNC_JOB, {}, tenant_id=tenant.id, dedupe_key=f"store:{tenant.id}:{slot}"
            )


async def sync_job(ctx: JobContext) -> None:
    assert ctx.tenant_id is not None
    with contextlib.suppress(
        AppError
    ):  # kept on the connection as last_error; the next read tries again
        await sync(ctx.services, ctx.tenant_id)


async def reports_job(ctx: JobContext) -> None:
    """Hourly: queue each business's daily report once its chosen hour has come."""
    services: Services = ctx.services
    connected = await _connected(services)
    async with services.db.system() as session:
        for tenant, link in connected:
            local = utcnow().astimezone(zone(tenant))
            if local.hour < link.report_hour:
                continue
            await enqueue(
                session,
                REPORT_JOB,
                {"day": local.date().isoformat()},
                tenant_id=tenant.id,
                dedupe_key=f"store-report:{tenant.id}:{local.date().isoformat()}",
            )


async def report_job(ctx: JobContext) -> None:
    services: Services = ctx.services
    assert ctx.tenant_id is not None
    # Report from the last good read.
    with contextlib.suppress(AppError):
        await sync(services, ctx.tenant_id)
    owner = await owner_of(services.db, ctx.tenant_id)
    async with services.db.tenant(ctx.tenant_id) as session:
        tenant = await session.get(Tenant, ctx.tenant_id)
        if tenant is None:
            return
        lang = staff_language(owner, tenant)
        day = date.fromisoformat(ctx.payload["day"])
        text = report_text(tenant, await day_summary(session, tenant, day), lang)
    await notices.notify(services, ctx.tenant_id, "store_report", text)

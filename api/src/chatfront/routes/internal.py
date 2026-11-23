"""Health, the cron entry point for cron-job.org, the model endpoints' state and outage drill,
local media files, and the operator setting a business's plan."""

from __future__ import annotations

import mimetypes
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select, text

from chatfront.audit.service import Actor, ActorType, record
from chatfront.books.ledger import today
from chatfront.channels.connect import CONNECTABLE, connect
from chatfront.core.clock import utcnow
from chatfront.core.errors import Forbidden, NotFound
from chatfront.core.models import Staff, StaffRole, Tenant
from chatfront.jobs.cron import run_due, secret_matches
from chatfront.media.storage import LocalStorage
from chatfront.owner.subscription import (
    PAID_UNTIL,
    PLAN_KEY,
    PLAN_REQUEST,
    VERIFIED,
    Plan,
    extended,
    plan_of,
    requested,
)
from chatfront.services import Services, get_services

router = APIRouter()
ServicesDep = Annotated[Services, Depends(get_services)]
SecretHeader = Annotated[str | None, Header(alias="X-Cron-Secret")]


def _check(services: Services, secret: str | None) -> None:
    if not secret_matches(secret, services.settings.cron_secret.get_secret_value()):
        raise Forbidden("Bad cron secret")


@router.get("/live")
async def live() -> dict[str, bool]:
    """The host's check that the process answers: no database, so a busy pool (a console
    loading dozens of panels) never gets a healthy instance restarted."""
    return {"ok": True}


@router.get("/health")
async def health(services: ServicesDep) -> dict[str, object]:
    async with services.db.system() as session:
        await session.execute(text("SELECT 1"))
    endpoints = [endpoint.name for endpoint in services.ai.endpoints()]
    return {"ok": True, "models": services.ai.mode, "endpoints": endpoints}


@router.post("/internal/cron")
async def cron(services: ServicesDep, secret: SecretHeader = None) -> dict[str, list[str]]:
    _check(services, secret)
    started = await run_due(services.db, services.registries.cron, utcnow())
    return {"enqueued": started}


class EndpointState(BaseModel):
    name: str
    model: str
    ready: bool
    failures: int  # in a row
    resting_until: datetime | None
    why: str | None  # failing, or drill
    last_error: str | None


class DrillIn(BaseModel):
    endpoint: str = Field(min_length=1, max_length=40)
    minutes: int = Field(ge=0, le=30)  # 0 brings it back now


def _states(services: Services) -> list[EndpointState]:
    endpoints = services.ai.endpoints()
    models = {endpoint.name: endpoint.model for endpoint in endpoints}
    return [
        EndpointState(
            name=status.name,
            model=models[status.name],
            ready=status.ready,
            failures=status.failures,
            resting_until=status.resting_until,
            why=status.why,
            last_error=status.last_error,
        )
        for status in services.ai.health.status(endpoints)
    ]


@router.get("/internal/ai")
async def ai_endpoints(services: ServicesDep, secret: SecretHeader = None) -> list[EndpointState]:
    """Each model endpoint in the failover chain and whether it is taking calls (114)."""
    _check(services, secret)
    return _states(services)


@router.post("/internal/ai/drill")
async def ai_drill(
    body: DrillIn, services: ServicesDep, secret: SecretHeader = None
) -> list[EndpointState]:
    """Take one endpoint out for some minutes, to show failover live."""
    _check(services, secret)
    if body.endpoint not in {endpoint.name for endpoint in services.ai.endpoints()}:
        raise NotFound("Endpoint")
    services.ai.health.drill(body.endpoint, body.minutes)
    return _states(services)


@router.get("/media/{key:path}")
async def local_media(key: str, exp: int, sig: str, services: ServicesDep) -> Response:
    """Serves files only for local storage; Supabase hands out its own signed URLs."""
    storage = services.storage
    if not isinstance(storage, LocalStorage) or not storage.verify(key, exp, sig):
        raise NotFound("Media")
    content_type = mimetypes.guess_type(key)[0] or "application/octet-stream"
    return Response(
        await storage.get(key),
        media_type=content_type,
        headers={
            "Cache-Control": "private, max-age=300",
            "Content-Disposition": 'attachment; filename="download"',
            "X-Content-Type-Options": "nosniff",
        },
    )


class PlanIn(BaseModel):
    shop: str = Field(min_length=1, max_length=60)  # the business's slug
    plan: Plan
    # Months paid for. Each payment adds them to the current end, so paying early loses
    # nothing. Leave out to change the plan without a payment (an upgrade mid-month).
    months: int | None = Field(None, ge=1, le=24)


@router.post("/internal/plan")
async def set_plan(
    body: PlanIn, services: ServicesDep, secret: SecretHeader = None
) -> dict[str, str | None]:
    """The operator sets what a business pays for (ReplyHub plans) once it has paid; owners
    cannot. The owner's request, if any, is cleared."""
    _check(services, secret)
    async with services.db.system() as session:
        tenant = await session.scalar(select(Tenant).where(Tenant.slug == body.shop))
        if tenant is None:
            raise NotFound("Shop")
        profile = {k: v for k, v in (tenant.profile or {}).items() if k != PLAN_REQUEST}
        profile[PLAN_KEY] = body.plan.value
        if body.plan == Plan.TRIAL:
            profile.pop(PAID_UNTIL, None)
        elif body.months is not None:
            profile[PAID_UNTIL] = extended(tenant, today(tenant), body.months).isoformat()
        tenant.profile = profile
        await record(
            session,
            tenant.id,
            Actor(ActorType.SYSTEM, "operator"),
            "settings.plan",
            entity=("tenant", str(tenant.id)),
            data={"plan": body.plan.value, "months": body.months},
        )
    return {"shop": body.shop, "plan": body.plan.value, "paid_until": profile.get(PAID_UNTIL)}


class PlanRequestOut(BaseModel):
    shop: str
    name: str
    plan: str  # the plan the owner asked for
    current: str
    asked_at: datetime
    owner_email: str | None


@router.get("/internal/plan-requests")
async def plan_requests(services: ServicesDep, secret: SecretHeader = None) -> list[PlanRequestOut]:
    """Owners who asked to pay for a plan, oldest first: the operator's to-do list."""
    _check(services, secret)
    async with services.db.system() as session:
        tenants = list(
            await session.scalars(select(Tenant).where(Tenant.profile.has_key(PLAN_REQUEST)))
        )
        found = []
        for tenant in tenants:
            asked = requested(tenant)
            if asked is None:
                continue
            owner = await session.scalar(
                select(Staff)
                .where(Staff.tenant_id == tenant.id, Staff.role == StaffRole.OWNER)
                .order_by(Staff.created_at)
                .limit(1)
            )
            found.append(
                PlanRequestOut(
                    shop=tenant.slug,
                    name=tenant.name,
                    plan=asked[0].value,
                    current=plan_of(tenant).value,
                    asked_at=asked[1],
                    owner_email=owner.email if owner else None,
                )
            )
    return sorted(found, key=lambda r: r.asked_at)


class ConnectIn(BaseModel):
    shop: str = Field(min_length=1, max_length=60)
    channel: Literal["whatsapp", "instagram", "messenger"]
    account_id: str = Field(min_length=1, max_length=80)  # phone number id, Instagram or Page id
    handle: str = Field(min_length=1, max_length=80)  # the number, or the username
    token: str | None = Field(None, max_length=600)  # the business's own access token


@router.post("/internal/connect")
async def connect_account(
    body: ConnectIn, services: ServicesDep, secret: SecretHeader = None
) -> dict[str, str]:
    """The operator connects a business's WhatsApp number (or Instagram, Messenger) after
    adding it in Meta; its token is sealed and kept per business."""
    _check(services, secret)
    account = await connect(
        services.db,
        services.settings,
        shop=body.shop,
        channel=CONNECTABLE[body.channel],
        account_id=body.account_id,
        handle=body.handle,
        token=body.token,
    )
    if body.channel == "whatsapp":  # the operator has checked the business: no more trial cap
        async with services.db.system() as session:
            tenant = await session.get(Tenant, account.tenant_id)
            if tenant is not None:
                tenant.profile = {**(tenant.profile or {}), VERIFIED: True}
    return {"shop": body.shop, "channel": body.channel, "display": account.display or ""}

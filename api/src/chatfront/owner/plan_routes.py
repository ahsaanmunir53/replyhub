"""The plan screen in the console (ReplyHub): where the business stands, what each plan gives,
and a way to ask for one. Paying happens with the operator, outside the app; the app only
records the request, and the operator sets the plan once the money is in."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter
from pydantic import BaseModel

from chatfront.audit.service import Actor, ActorType, record
from chatfront.core.clock import utcnow
from chatfront.core.errors import AppError, NotFound
from chatfront.core.models import Tenant
from chatfront.owner import usage
from chatfront.owner.rights import Can
from chatfront.owner.routes import ServicesDep, needs
from chatfront.owner.sessions import OwnerSession
from chatfront.owner.subscription import (
    PAID,
    PLAN_REQUEST,
    PLANS,
    SELLING,
    Feature,
    Plan,
    allowance,
    paid_until,
    plan_of,
    prices,
    requested,
)

router = APIRouter(prefix="/api/owner/plan")
SettingsDep = Annotated[OwnerSession, needs(Can.SETTINGS)]


class PlanOption(BaseModel):
    id: str
    price: str | None  # as the operator wrote it; None when not set
    replies: int  # assistant replies a month
    features: list[str]


class PlanView(BaseModel):
    plan: str
    used: int  # assistant replies in this period (the trial, or this month)
    limit: int
    chats_used: int
    chats_limit: int
    trial_ends: date | None
    paid_until: date | None
    stopped: str | None  # why the assistant is not answering now: trial_over, allowance, lapsed
    requested: str | None  # the plan the owner asked for, until the operator sets it
    requested_at: datetime | None
    contact: str | None  # a wa.me link to the operator, with the request written in
    options: list[PlanOption]


class PlanAsk(BaseModel):
    plan: Plan


def _contact(number: str, shop: str, plan: str | None) -> str | None:
    digits = "".join(c for c in number if c.isdigit())
    if not digits:
        return None
    wanted = f"the {plan} plan" if plan else "a plan"
    return f"https://wa.me/{digits}?text={quote(f'Hi, I want {wanted} for ReplyHub ({shop}).')}"


async def _view(services: ServicesDep, tenant: Tenant) -> PlanView:
    settings = services.settings
    async with services.db.tenant(tenant.id) as db:
        stand = await usage.standing(db, settings, tenant)
    asked = requested(tenant)
    price_of = prices(settings.plan_prices)
    return PlanView(
        plan=stand.plan.value,
        used=stand.used,
        limit=stand.limit,
        chats_used=stand.chats_used,
        chats_limit=stand.chats_limit,
        trial_ends=stand.trial_ends,
        paid_until=paid_until(tenant),
        # Seen without a chat, a trial whose chats are used is shown as over.
        stopped=stand.stop.value if stand.stop else None,
        requested=asked[0].value if asked else None,
        requested_at=asked[1] if asked else None,
        contact=_contact(settings.sales_whatsapp, tenant.slug, asked[0].value if asked else None),
        options=[
            PlanOption(
                id=plan.value,
                price=price_of.get(plan.value),
                replies=allowance(settings.plan_replies, plan),
                features=sorted(PLANS[plan]),
            )
            for plan in PAID
        ],
    )


@router.get("")
async def get_plan(session: SettingsDep, services: ServicesDep) -> PlanView:
    async with services.db.tenant(session.tenant_id) as db:
        tenant = await db.get(Tenant, session.tenant_id)
    if tenant is None:
        raise NotFound("shop")
    return await _view(services, tenant)


@router.post("/request")
async def ask_for_plan(body: PlanAsk, session: SettingsDep, services: ServicesDep) -> PlanView:
    """The owner asks to pay for a plan. Asking again replaces the earlier request."""
    if body.plan not in PAID:
        raise AppError("bad_plan", "Choose Basic, Pro or Business")
    services.limiter.check(f"plan-request:{session.tenant_id}")
    async with services.db.tenant(session.tenant_id) as db:
        tenant = await db.get(Tenant, session.tenant_id)
        if tenant is None:
            raise NotFound("shop")
        tenant.profile = {
            **(tenant.profile or {}),
            PLAN_REQUEST: {"plan": body.plan.value, "at": utcnow().isoformat()},
        }
        await record(
            db,
            tenant.id,
            Actor(ActorType.STAFF, str(session.staff_id)),
            "settings.plan_request",
            entity=("tenant", str(tenant.id)),
            data={"plan": body.plan.value},
        )
    return await _view(services, tenant)


class SellingIn(BaseModel):
    on: bool


@router.put("/selling")
async def set_selling(body: SellingIn, session: SettingsDep, services: ServicesDep) -> PlanView:
    """Turn orders in the chat on or off (cash on delivery only). Needs a plan with the shop."""
    async with services.db.tenant(session.tenant_id) as db:
        tenant = await db.get(Tenant, session.tenant_id)
        if tenant is None:
            raise NotFound("shop")
        if body.on and Feature.SHOP not in PLANS[plan_of(tenant)]:
            raise AppError("plan_needed", "Orders in the chat come with the Pro plan")
        tenant.profile = {**(tenant.profile or {}), SELLING: body.on}
        await record(
            db,
            tenant.id,
            Actor(ActorType.STAFF, str(session.staff_id)),
            "settings.selling",
            entity=("tenant", str(tenant.id)),
            data={"on": body.on},
        )
    return await _view(services, tenant)

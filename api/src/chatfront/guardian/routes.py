"""Money Guardian in the console: courier money, profit per order, disputes, courier cards,
customers to watch and the advisor, with the uploads and settings behind them."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, File, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select

from chatfront.audit.service import Actor, ActorType, record
from chatfront.catalog.models import Product
from chatfront.core.countries import get_pack
from chatfront.core.errors import AppError, NotFound
from chatfront.core.models import Tenant
from chatfront.core.money import to_minor
from chatfront.delivery.shipping import order_by_code
from chatfront.guardian import bank, cases, insights, ledger, verify
from chatfront.guardian.models import CaseKind, CaseStatus, CourierCase, CourierPayout
from chatfront.orders.models import Order
from chatfront.owner.rights import Can
from chatfront.owner.routes import ServicesDep, needs
from chatfront.owner.sessions import OwnerSession

router = APIRouter(prefix="/api/owner/guardian")
MoneyDep = Annotated[OwnerSession, needs(Can.BOOKS)]
ShipDep = Annotated[OwnerSession, needs(Can.SHIP)]
MAX_SHEET = 5 * 1024 * 1024


def _actor(session: OwnerSession) -> Actor:
    return Actor(ActorType.STAFF, str(session.staff_id))


@router.get("")
async def overview(
    session: MoneyDep, services: ServicesDep, days: int = 30, city: str = ""
) -> dict[str, Any]:
    days = min(max(days, 1), 365)
    since = ledger.since_days(days)
    async with services.db.tenant(session.tenant_id) as db:
        tenant = await db.get(Tenant, session.tenant_id)
        if tenant is None:
            raise NotFound("shop")
        cod = await ledger.cod_lines(db, tenant, ledger.since_days(max(days, 90)))
        opened = await cases.detect(db, tenant, cod)
        profits = await ledger.profits(db, tenant, since)
        cards = await insights.scorecards(db, since, city.strip(), cod)
        watch = await insights.watch_list(db)
        alerts = await insights.advice(db, cod, profits, cards)
        found = (
            await db.execute(
                select(CourierCase, Order.code)
                .join(Order, Order.id == CourierCase.order_id)
                .order_by(CourierCase.created_at.desc())
                .limit(100)
            )
        ).all()
        payouts = list(
            await db.scalars(
                select(CourierPayout).order_by(CourierPayout.created_at.desc()).limit(20)
            )
        )
    known = [p for p in profits if not p.unknown and p.status != "returned"]
    open_cases = [c for c, _ in found if c.status not in cases.CLOSED]
    return {
        "days": days,
        "summary": {
            "unpaid": sum(line.unpaid for line in cod),
            "unproven": sum(line.unproven for line in cod),
            "banked": sum(line.banked for line in cod),
            "at_risk": sum(c.at_stake - c.recovered for c in open_cases),
            "recovered": sum(c.recovered for c, _ in found),
            "unreconciled": sum(1 for line in cod if line.state in ("unpaid", "short", "reported")),
            "net_profit": sum(p.net for p in known)
            + sum(p.net for p in profits if p.status == "returned"),
            "profit_orders": len(known),
            "costs_missing": sum(1 for p in profits if p.unknown),
            "new_cases": opened,
        },
        "alerts": alerts,
        "cod": [
            {
                **{
                    k: getattr(line, k)
                    for k in (
                        "code",
                        "courier",
                        "city",
                        "expected",
                        "reported",
                        "banked",
                        "days",
                        "overdue",
                    )
                },
                "state": line.state,
                "unpaid": line.unpaid,
            }
            for line in cod[:200]
        ],
        "profits": [
            {
                "code": p.code,
                "status": p.status,
                "revenue": p.revenue,
                "goods": p.goods,
                "courier": p.courier,
                "returned": p.returned,
                "packaging": p.packaging,
                "ads": p.ads,
                "payment": p.payment,
                "net": p.net,
                "unknown": p.unknown,
            }
            for p in profits[:200]
        ],
        "cases": [cases.out(c, code) for c, code in found],
        "couriers": cards,
        "watch": watch,
        "payouts": [
            {
                "name": p.name,
                "courier": p.courier,
                "rows": p.rows,
                "paid_out": p.paid_out,
                "banked": p.bank_receipt_id is not None,
                "at": p.created_at.isoformat(),
            }
            for p in payouts
        ],
        "settings": ledger.settings_of(tenant),
    }


@router.post("/bank")
async def upload_bank(
    session: MoneyDep, services: ServicesDep, file: Annotated[UploadFile, File()]
) -> dict[str, Any]:
    """The shop's bank statement: credits kept, and courier payouts they prove marked."""
    data = await file.read(MAX_SHEET + 1)
    if len(data) > MAX_SHEET:
        raise AppError("too_big", "The sheet is over 5 MB")
    async with services.db.tenant(session.tenant_id) as db:
        tenant = await db.get(Tenant, session.tenant_id)
        assert tenant is not None
        rows, credits = bank.read(data, get_pack(tenant.country).minor_digits)
        report = await bank.keep(db, session.tenant_id, credits)
        report.rows = rows
        await record(
            db,
            session.tenant_id,
            _actor(session),
            "guardian.bank",
            entity=("sheet", file.filename or "bank"),
            data={"credits": report.credits, "new": report.new, "proved": len(report.proved)},
        )
    return {
        "rows": report.rows,
        "credits": report.credits,
        "new": report.new,
        "proved": report.proved,
    }


class GuardSettings(BaseModel):
    packaging: Decimal | None = Field(default=None, ge=0, le=100000)
    ads: Decimal | None = Field(default=None, ge=0, le=1000000)
    payment_percent: float | None = Field(default=None, ge=0, le=20)
    overdue_days: int | None = Field(default=None, ge=1, le=90)


@router.put("/settings")
async def save_settings(
    body: GuardSettings, session: MoneyDep, services: ServicesDep
) -> dict[str, Any]:
    """The shop's usual cost per order (packaging, ads), its online payment charge and how
    many days a courier may take to pay before the money counts as overdue."""
    async with services.db.tenant(session.tenant_id) as db:
        tenant = await db.get(Tenant, session.tenant_id)
        assert tenant is not None
        digits = get_pack(tenant.country).minor_digits
        now = dict(ledger.settings_of(tenant))
        for key in ("packaging", "ads"):
            value = getattr(body, key)
            if value is not None:
                now[key] = to_minor(value, digits)
        if body.payment_percent is not None:
            now["payment_percent"] = body.payment_percent
        if body.overdue_days is not None:
            now["overdue_days"] = body.overdue_days
        tenant.profile = {**(tenant.profile or {}), ledger.GUARD_KEY: now}
        await record(db, session.tenant_id, _actor(session), "guardian.settings", data=now)
    return now


class OrderCosts(BaseModel):
    packaging: Decimal | None = Field(default=None, ge=0, le=100000)
    ads: Decimal | None = Field(default=None, ge=0, le=1000000)
    payment: Decimal | None = Field(default=None, ge=0, le=1000000)


@router.put("/orders/{code}/costs")
async def order_costs(
    code: str, body: OrderCosts, session: MoneyDep, services: ServicesDep
) -> dict[str, int]:
    async with services.db.tenant(session.tenant_id) as db:
        tenant = await db.get(Tenant, session.tenant_id)
        assert tenant is not None
        order = await order_by_code(db, code)
        digits = get_pack(tenant.country).minor_digits
        costs = dict(order.costs or {})
        for key in ledger.COST_KEYS:
            value = getattr(body, key)
            if value is not None:
                costs[key] = to_minor(value, digits)
        order.costs = costs
    return costs


class UnitCost(BaseModel):
    unit_cost: Decimal | None = Field(default=None, ge=0, le=Decimal("100000000"))


@router.put("/products/{product_id}/cost")
async def product_cost(
    product_id: uuid.UUID, body: UnitCost, session: MoneyDep, services: ServicesDep
) -> dict[str, int | None]:
    async with services.db.tenant(session.tenant_id) as db:
        tenant = await db.get(Tenant, session.tenant_id)
        product = await db.get(Product, product_id)
        if tenant is None or product is None:
            raise NotFound("product")
        digits = get_pack(tenant.country).minor_digits
        product.unit_cost = None if body.unit_cost is None else to_minor(body.unit_cost, digits)
    return {"unit_cost": product.unit_cost}


class Attempt(BaseModel):
    note: str = Field(default="", max_length=300)


@router.post("/orders/{code}/attempt")
async def attempt(
    code: str, body: Attempt, session: ShipDep, services: ServicesDep
) -> dict[str, bool]:
    """The courier says it tried and could not deliver: recorded, and the customer asked."""
    asked = await verify.attempt_failed(services, session.tenant_id, code, body.note, "courier")
    return {"asked": asked}


class NewCase(BaseModel):
    order: str = Field(min_length=3, max_length=16)
    kind: CaseKind
    at_stake: Decimal = Field(default=Decimal(0), ge=0, le=Decimal("100000000"))
    note: str = Field(default="", max_length=500)


@router.post("/cases")
async def new_case(body: NewCase, session: MoneyDep, services: ServicesDep) -> dict[str, Any]:
    async with services.db.tenant(session.tenant_id) as db:
        tenant = await db.get(Tenant, session.tenant_id)
        assert tenant is not None
        order = await order_by_code(db, body.order)
        digits = get_pack(tenant.country).minor_digits
        case = await cases.open_case(
            db,
            tenant,
            order,
            body.kind,
            to_minor(body.at_stake, digits),
            "staff",
            body.note or "Opened by the shop.",
        )
        if case is None:
            raise AppError(
                "case_open", "This parcel already has an open case of this kind", status_code=409
            )
        return cases.out(case, order.code)


class CaseChange(BaseModel):
    status: CaseStatus | None = None
    recovered: Decimal | None = Field(default=None, ge=0, le=Decimal("100000000"))
    reference: str | None = Field(default=None, max_length=80)
    note: str = Field(default="", max_length=500)
    assigned_staff_id: uuid.UUID | None = None


@router.put("/cases/{case_id}")
async def change_case(
    case_id: uuid.UUID, body: CaseChange, session: MoneyDep, services: ServicesDep
) -> dict[str, Any]:
    async with services.db.tenant(session.tenant_id) as db:
        tenant = await db.get(Tenant, session.tenant_id)
        assert tenant is not None
        digits = get_pack(tenant.country).minor_digits
        case = await cases.update(
            db,
            case_id,
            "staff",
            status=body.status,
            recovered=None if body.recovered is None else to_minor(body.recovered, digits),
            reference=body.reference,
            note=body.note,
            assigned=body.assigned_staff_id,
        )
        code = await db.scalar(select(Order.code).where(Order.id == case.order_id))
        return cases.out(case, code or "")


@router.get("/cases/{case_id}/complaint")
async def case_complaint(
    case_id: uuid.UUID, session: MoneyDep, services: ServicesDep
) -> dict[str, str]:
    async with services.db.tenant(session.tenant_id) as db:
        tenant = await db.get(Tenant, session.tenant_id)
        case = await db.get(CourierCase, case_id)
        if tenant is None or case is None:
            raise NotFound("case")
        return {"text": await cases.complaint(db, tenant, case)}

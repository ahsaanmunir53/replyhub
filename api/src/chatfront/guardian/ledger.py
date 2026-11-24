"""The COD ledger and each order's true profit, worked out by code from what is recorded.

COD money for a delivered parcel moves in three steps, and the ledger keeps them apart:
  expected   what the rider collected, less the courier's charge;
  reported   what the courier's own sheet says it paid over for that parcel;
  banked     the part of that sheet a bank receipt of the same amount proves arrived.
A courier saying "paid" is never taken as money received: until the bank agrees it is
"reported", and only "banked" counts as in.

Profit per order: what the customer paid, less the goods (batch cost, else the owner's unit
cost), the courier both ways, packaging, ads and payment charges. A cost nobody entered is
listed as unknown, never guessed.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from chatfront.catalog.models import Product, Variant
from chatfront.core.clock import utcnow
from chatfront.core.models import Tenant
from chatfront.delivery.models import CodSettlement, Shipment
from chatfront.guardian.models import CourierPayout
from chatfront.orders.models import Order, OrderItem
from chatfront.orders.states import OrderStatus
from chatfront.stock.models import BatchAllocation

GUARD_KEY = "guardian"  # the shop's usual costs and its patience with couriers, in the profile
OVERDUE_DAYS = 10
COST_KEYS = ("packaging", "ads", "payment")
DONE = (OrderStatus.DELIVERED, OrderStatus.RETURNED)


def settings_of(tenant: Tenant) -> dict[str, Any]:
    found = (tenant.profile or {}).get(GUARD_KEY) or {}
    return found if isinstance(found, dict) else {}


def overdue_days(tenant: Tenant) -> int:
    value = settings_of(tenant).get("overdue_days")
    return int(value) if isinstance(value, int) and 1 <= value <= 90 else OVERDUE_DAYS


@dataclass
class CodLine:
    code: str
    courier: str
    city: str
    delivered_at: datetime | None
    expected: int
    reported: int
    banked: int
    days: int  # since delivered
    overdue: bool

    @property
    def state(self) -> str:
        if self.expected <= 0:
            return "nothing_due"
        if self.banked >= self.expected:
            return "banked"
        if self.reported >= self.expected:
            return "reported"  # the courier says paid; no bank receipt proves it yet
        if self.reported > 0:
            return "short"
        return "unpaid"

    @property
    def unpaid(self) -> int:
        return max(self.expected - self.reported, 0)

    @property
    def unproven(self) -> int:
        return max(min(self.reported, self.expected) - self.banked, 0)


async def cod_lines(session: AsyncSession, tenant: Tenant, since: datetime) -> list[CodLine]:
    """Every delivered cash-on-delivery parcel since the date, with its money so far."""
    rows = (
        await session.execute(
            select(Order, Shipment)
            .join(Shipment, Shipment.order_id == Order.id)
            .where(
                Order.status == OrderStatus.DELIVERED,
                Shipment.cod_amount > 0,
                Shipment.delivered_at >= since,
            )
            .order_by(Shipment.delivered_at.desc())
        )
    ).all()
    if not rows:
        return []
    money = {
        order_id: (int(reported or 0), int(banked or 0))
        for order_id, reported, banked in (
            await session.execute(
                select(
                    CodSettlement.order_id,
                    func.sum(CodSettlement.paid),
                    func.sum(CodSettlement.paid).filter(CourierPayout.bank_receipt_id.is_not(None)),
                )
                .outerjoin(CourierPayout, CourierPayout.id == CodSettlement.payout_id)
                .where(CodSettlement.order_id.in_([order.id for order, _ in rows]))
                .group_by(CodSettlement.order_id)
            )
        ).all()
    }
    now, patience = utcnow(), overdue_days(tenant)
    out = []
    for order, shipment in rows:
        expected = shipment.cod_amount - (shipment.courier_charge or 0)
        reported, banked = money.get(order.id, (0, 0))
        days = (now - shipment.delivered_at).days if shipment.delivered_at else 0
        line = CodLine(
            order.code,
            shipment.courier or "",
            str((order.address or {}).get("city") or ""),
            shipment.delivered_at,
            expected,
            reported,
            banked,
            days,
            False,
        )
        line.overdue = line.state in ("unpaid", "short") and days > patience
        out.append(line)
    return out


@dataclass
class Profit:
    code: str
    status: str
    placed_at: datetime | None
    revenue: int  # what the customer paid, delivery charge included; 0 when it came back
    goods: int | None
    courier: int | None
    returned: int  # the courier's charge to bring it back
    packaging: int
    ads: int
    payment: int
    unknown: list[str] = field(default_factory=list)

    @property
    def net(self) -> int:
        return (
            self.revenue
            - (self.goods or 0)
            - (self.courier or 0)
            - self.returned
            - self.packaging
            - self.ads
            - self.payment
        )


def _usual(tenant: Tenant, key: str) -> int:
    value = settings_of(tenant).get(key)
    return int(value) if isinstance(value, int) and value >= 0 else 0


def payment_charge(tenant: Tenant, order: Order) -> int:
    """A percentage the shop pays on online payments, from its settings; cash pays none."""
    if order.payment_method == "cod":
        return 0
    percent = settings_of(tenant).get("payment_percent")
    if not isinstance(percent, (int, float)) or not 0 < percent <= 20:
        return 0
    return round(order.total * float(percent) / 100)


async def _goods_cost(
    session: AsyncSession, order_ids: list[uuid.UUID]
) -> dict[uuid.UUID, int | None]:
    """Each order's goods: its batch costs, else each product's unit cost; None if any unit's
    cost is unknown."""
    batch = {
        order_id: (int(cost or 0), int(unknown or 0))
        for order_id, cost, unknown in (
            await session.execute(
                select(
                    BatchAllocation.order_id,
                    func.sum(BatchAllocation.cost),
                    func.sum(BatchAllocation.units).filter(BatchAllocation.cost.is_(None)),
                )
                .where(BatchAllocation.order_id.in_(order_ids))
                .group_by(BatchAllocation.order_id)
            )
        ).all()
    }
    unit = {
        order_id: (int(cost or 0), int(missing or 0))
        for order_id, cost, missing in (
            await session.execute(
                select(
                    OrderItem.order_id,
                    func.sum(OrderItem.quantity * Product.unit_cost),
                    func.count().filter(Product.unit_cost.is_(None)),
                )
                .join(Variant, Variant.id == OrderItem.variant_id)
                .join(Product, Product.id == Variant.product_id)
                .where(OrderItem.order_id.in_(order_ids))
                .group_by(OrderItem.order_id)
            )
        ).all()
    }
    out: dict[uuid.UUID, int | None] = {}
    for order_id in order_ids:
        cost, unknown = batch.get(order_id, (0, 0))
        if order_id in batch and not unknown:
            out[order_id] = cost
            continue
        cost, missing = unit.get(order_id, (0, 1))
        out[order_id] = None if missing else cost
    return out


async def profits(
    session: AsyncSession, tenant: Tenant, since: datetime, limit: int = 300
) -> list[Profit]:
    """Delivered and returned orders since the date, each with what it really made."""
    rows = (
        await session.execute(
            select(Order, Shipment)
            .outerjoin(Shipment, Shipment.order_id == Order.id)
            .where(Order.status.in_(DONE), Order.placed_at >= since)
            .order_by(Order.placed_at.desc())
            .limit(limit)
        )
    ).all()
    goods = await _goods_cost(session, [order.id for order, _ in rows])
    out = []
    for order, shipment in rows:
        costs = order.costs or {}
        came_back = order.status == OrderStatus.RETURNED
        line = Profit(
            order.code,
            order.status,
            order.placed_at,
            0 if came_back else order.total,
            0 if came_back else goods.get(order.id),
            shipment.courier_charge if shipment else None,
            (shipment.return_charge or 0) if shipment and came_back else 0,
            int(costs.get("packaging", _usual(tenant, "packaging"))),
            int(costs.get("ads", _usual(tenant, "ads"))),
            int(costs.get("payment", payment_charge(tenant, order))),
        )
        if line.goods is None:
            line.unknown.append("goods")
        if line.courier is None:
            line.unknown.append("courier")
        if came_back and shipment and shipment.return_charge is None:
            line.unknown.append("return")
        out.append(line)
    return out


def since_days(days: int) -> datetime:
    return utcnow() - timedelta(days=days)

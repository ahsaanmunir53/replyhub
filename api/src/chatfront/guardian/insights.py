"""Courier scorecards, customers to watch, and the advisor's alerts, all counted by code.

Each courier's card covers the parcels sent out in the period: delivered and returned
shares, first-attempt deliveries, attempts the customer denied, days to deliver, days the
COD money took to come, and money still out. The advisor turns the same numbers into
sentences; every figure it says is one counted here, never a model's.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from chatfront.core.clock import utcnow
from chatfront.core.models import Customer
from chatfront.delivery.models import CodSettlement, Shipment
from chatfront.guardian.ledger import CodLine, Profit
from chatfront.guardian.models import EventKind, ShipmentEvent
from chatfront.orders.models import Order, OrderItem
from chatfront.orders.states import OrderStatus


@dataclass
class Card:
    courier: str
    sent: int = 0
    delivered: int = 0
    returned: int = 0
    first_try: int = 0  # delivered with no failed attempt recorded
    denied: int = 0  # attempts the customer said never happened
    days_to_deliver: list[float] = field(default_factory=list)
    days_to_pay: list[float] = field(default_factory=list)
    unpaid: int = 0

    def out(self) -> dict[str, Any]:
        def avg(values: list[float]) -> float | None:
            return round(sum(values) / len(values), 1) if values else None

        def share(part: int) -> int | None:
            return round(part * 100 / self.sent) if self.sent else None

        return {
            "courier": self.courier,
            "sent": self.sent,
            "delivered_pct": share(self.delivered),
            "returned_pct": share(self.returned),
            "first_try_pct": round(self.first_try * 100 / self.delivered)
            if self.delivered
            else None,
            "denied": self.denied,
            "days_to_deliver": avg(self.days_to_deliver),
            "days_to_pay": avg(self.days_to_pay),
            "unpaid": self.unpaid,
        }


async def scorecards(
    session: AsyncSession, since: datetime, city: str, cod: list[CodLine]
) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(Order, Shipment)
            .join(Shipment, Shipment.order_id == Order.id)
            .where(Shipment.dispatched_at >= since)
        )
    ).all()
    if city:
        rows = [
            r for r in rows if str((r[0].address or {}).get("city", "")).lower() == city.lower()
        ]
    ids = [order.id for order, _ in rows]
    failed: dict[Any, set[str]] = defaultdict(set)
    for order_id, kind in (
        await session.execute(
            select(ShipmentEvent.order_id, ShipmentEvent.kind).where(
                ShipmentEvent.order_id.in_(ids)
            )
        )
    ).all():
        failed[order_id].add(kind)
    first_paid = dict(
        (
            await session.execute(
                select(CodSettlement.order_id, func.min(CodSettlement.created_at))
                .where(CodSettlement.order_id.in_(ids))
                .group_by(CodSettlement.order_id)
            )
        ).all()
    )
    unpaid: dict[str, int] = defaultdict(int)
    for line in cod:
        unpaid[line.courier or "-"] += line.unpaid
    cards: dict[str, Card] = {}
    for order, shipment in rows:
        card = cards.setdefault(shipment.courier or "-", Card(shipment.courier or "-"))
        card.sent += 1
        kinds = failed.get(order.id, set())
        card.denied += EventKind.CUSTOMER_DENIED in kinds
        if order.status == OrderStatus.DELIVERED and shipment.delivered_at:
            card.delivered += 1
            card.first_try += EventKind.ATTEMPT_FAILED not in kinds
            if shipment.dispatched_at:
                card.days_to_deliver.append(
                    (shipment.delivered_at - shipment.dispatched_at).total_seconds() / 86400
                )
            if paid_at := first_paid.get(order.id):
                card.days_to_pay.append((paid_at - shipment.delivered_at).total_seconds() / 86400)
        elif order.status == OrderStatus.RETURNED:
            card.returned += 1
    for name, card in cards.items():
        card.unpaid = unpaid.get(name, 0)
    return sorted((c.out() for c in cards.values()), key=lambda c: -c["sent"])


async def watch_list(session: AsyncSession, limit: int = 20) -> list[dict[str, Any]]:
    """Customers whose own record calls for a check before sending: refused or returned COD
    parcels, cancellations, or attempts they confirmed and still refused. Reasons, not labels."""
    counts = (
        await session.execute(
            select(
                Order.customer_id,
                func.count().filter(Order.status == OrderStatus.DELIVERED),
                func.count().filter(Order.status == OrderStatus.RETURNED),
                func.count().filter(Order.status == OrderStatus.CANCELLED),
            )
            .where(Order.status != OrderStatus.CART)
            .group_by(Order.customer_id)
            .having(
                (func.count().filter(Order.status == OrderStatus.RETURNED) > 0)
                | (func.count().filter(Order.status == OrderStatus.CANCELLED) > 1)
            )
            .limit(limit)
        )
    ).all()
    if not counts:
        return []
    names = {
        c.id: c.display_name or ""
        for c in await session.scalars(
            select(Customer).where(Customer.id.in_([row[0] for row in counts]))
        )
    }
    out = []
    for customer_id, delivered, returned, cancelled in counts:
        out.append(
            {
                "customer_id": str(customer_id),
                "name": names.get(customer_id, ""),
                "delivered": delivered,
                "returned": returned,
                "cancelled": cancelled,
            }
        )
    return sorted(out, key=lambda c: (-c["returned"], -c["cancelled"]))


async def advice(
    session: AsyncSession,
    cod: list[CodLine],
    profits: list[Profit],
    cards: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """The advisor's alerts: a key and the counted numbers it fills in."""
    alerts: list[dict[str, Any]] = []
    overdue = [line for line in cod if line.overdue]
    if overdue:
        alerts.append(
            {
                "key": "overdue",
                "level": "high",
                "count": len(overdue),
                "amount": sum(line.unpaid for line in overdue),
            }
        )
    unproven = sum(line.unproven for line in cod)
    if unproven:
        alerts.append({"key": "unproven", "level": "medium", "amount": unproven})
    week = utcnow() - timedelta(days=7)
    sales = (
        await session.execute(
            select(OrderItem.name, func.sum(OrderItem.unit_price * OrderItem.quantity))
            .join(Order, Order.id == OrderItem.order_id)
            .where(
                Order.placed_at >= week,
                Order.status.not_in([OrderStatus.CANCELLED, OrderStatus.CART]),
            )
            .group_by(OrderItem.name)
        )
    ).all()
    total = sum(int(v or 0) for _, v in sales)
    if total and len(sales) > 1:
        name, best = max(sales, key=lambda r: int(r[1] or 0))
        share = round(int(best or 0) * 100 / total)
        if share >= 30:
            alerts.append({"key": "top_product", "level": "info", "name": name, "share": share})
    this_week = [p for p in profits if p.placed_at and p.placed_at >= week]
    last_week = [
        p for p in profits if p.placed_at and week - timedelta(days=7) <= p.placed_at < week
    ]

    def rate(lines: list[Profit]) -> int | None:
        return (
            round(sum(p.status == OrderStatus.RETURNED for p in lines) * 100 / len(lines))
            if len(lines) >= 5
            else None
        )

    now_rate, then_rate = rate(this_week), rate(last_week)
    if now_rate is not None and then_rate is not None and now_rate - then_rate >= 5:
        alerts.append({"key": "returns_up", "level": "medium", "now": now_rate, "then": then_rate})
    timed = [c for c in cards if c["days_to_deliver"] is not None and c["sent"] >= 5]
    if len(timed) >= 2:
        slow = max(timed, key=lambda c: c["days_to_deliver"])
        fast = min(timed, key=lambda c: c["days_to_deliver"])
        if slow["days_to_deliver"] - fast["days_to_deliver"] >= 1:
            alerts.append(
                {
                    "key": "slow_courier",
                    "level": "info",
                    "courier": slow["courier"],
                    "days": slow["days_to_deliver"],
                    "other": fast["courier"],
                    "other_days": fast["days_to_deliver"],
                }
            )
    losing = [
        p for p in profits if not p.unknown and p.status == OrderStatus.DELIVERED and p.net < 0
    ]
    if losing:
        alerts.append(
            {
                "key": "losing_orders",
                "level": "high",
                "count": len(losing),
                "amount": -sum(p.net for p in losing),
            }
        )
    known = [p for p in profits if not p.unknown and p.status == OrderStatus.DELIVERED]
    ads = sum(p.ads for p in known)
    gross = sum(p.net + p.ads for p in known)
    if ads and gross > 0 and ads * 100 >= gross * 30:
        alerts.append({"key": "ads_heavy", "level": "medium", "share": round(ads * 100 / gross)})
    unknown = sum(1 for p in profits if p.unknown)
    if unknown:
        alerts.append({"key": "costs_missing", "level": "info", "count": unknown})
    return alerts

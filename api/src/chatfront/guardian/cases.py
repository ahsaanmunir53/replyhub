"""Disputes & Claims: one case per parcel and problem, with its evidence and its ending.

Code opens a case only from recorded facts:
  cod_missing      delivered by COD, past the shop's patience, and the courier paid less;
  wrong_deduction  the courier's sheet took a bigger charge than the one agreed for it;
  lost             sent out more than two weeks ago and neither delivered nor back;
  false_attempt    the courier says it tried, and the customer says nobody came or called;
  unjustified_rto  it came back, and the customer had said nobody came or called.
The owner opens any kind by hand too (a damaged parcel, say). A customer's word is shown as
what the customer said, never as proof; the complaint says what each record shows.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from chatfront.core.clock import utcnow
from chatfront.core.countries import shop_money
from chatfront.core.errors import AppError, NotFound
from chatfront.core.models import Tenant
from chatfront.delivery.models import CodSettlement, Shipment
from chatfront.guardian.ledger import CodLine
from chatfront.guardian.models import CaseKind, CaseStatus, CourierCase, EventKind, ShipmentEvent
from chatfront.orders.models import Order
from chatfront.orders.states import OrderStatus

LOST_AFTER = timedelta(days=14)
CLOSED = (CaseStatus.RESOLVED, CaseStatus.REJECTED)


def _note(by: str, text: str) -> dict[str, str]:
    return {"at": utcnow().isoformat(timespec="minutes"), "by": by, "text": text[:500]}


async def open_case(
    session: AsyncSession,
    tenant: Tenant,
    order: Order,
    kind: CaseKind,
    at_stake: int,
    by: str,
    why: str,
) -> CourierCase | None:
    """A new case, unless this parcel already has one of this kind still open."""
    existing = await session.scalar(
        select(CourierCase).where(
            CourierCase.order_id == order.id,
            CourierCase.kind == kind,
            CourierCase.status.not_in(list(CLOSED)),
        )
    )
    if existing is not None:
        return None
    shipment = await session.scalar(select(Shipment).where(Shipment.order_id == order.id))
    case = CourierCase(
        tenant_id=tenant.id,
        order_id=order.id,
        kind=kind,
        opened_by=by,
        courier=(shipment.courier or "") if shipment else "",
        at_stake=max(at_stake, 0),
        timeline=[_note(by, why)],
    )
    session.add(case)
    await session.flush()
    return case


async def detect(session: AsyncSession, tenant: Tenant, cod: list[CodLine]) -> int:
    """Open the cases the records call for; returns how many are new."""
    opened = 0
    codes = {line.code: line for line in cod if line.overdue and line.unpaid}
    for order in await session.scalars(select(Order).where(Order.code.in_(list(codes)))):
        line = codes[order.code]
        why = (
            f"Delivered {line.days} days ago; expected {line.expected}, "
            f"courier paid {line.reported}."
        )
        if await open_case(session, tenant, order, CaseKind.COD_MISSING, line.unpaid, "code", why):
            opened += 1
    over = (
        await session.execute(
            select(Order, Shipment, func.max(CodSettlement.charges))
            .join(Shipment, Shipment.order_id == Order.id)
            .join(CodSettlement, CodSettlement.order_id == Order.id)
            .where(Shipment.courier_charge.is_not(None))
            .group_by(Order.id, Shipment.id)
            .having(func.max(CodSettlement.charges) > Shipment.courier_charge)
        )
    ).all()
    for order, shipment, charged in over:
        extra = int(charged or 0) - (shipment.courier_charge or 0)
        why = f"Agreed charge {shipment.courier_charge}; the courier's sheet took {charged}."
        if await open_case(session, tenant, order, CaseKind.WRONG_DEDUCTION, extra, "code", why):
            opened += 1
    stuck = await session.execute(
        select(Order, Shipment)
        .join(Shipment, Shipment.order_id == Order.id)
        .where(
            Order.status == OrderStatus.DISPATCHED,
            Shipment.dispatched_at < utcnow() - LOST_AFTER,
        )
    )
    for order, shipment in stuck.all():
        why = f"Sent out {shipment.dispatched_at:%Y-%m-%d}; no delivery or return since."
        if await open_case(session, tenant, order, CaseKind.LOST, order.total, "code", why):
            opened += 1
    denied = await session.execute(
        select(Order)
        .join(ShipmentEvent, ShipmentEvent.order_id == Order.id)
        .where(
            Order.status == OrderStatus.RETURNED, ShipmentEvent.kind == EventKind.CUSTOMER_DENIED
        )
    )
    for order in denied.scalars().unique():
        parcel = await session.scalar(select(Shipment).where(Shipment.order_id == order.id))
        cost = ((parcel.courier_charge or 0) + (parcel.return_charge or 0)) if parcel else 0
        why = "Returned, though the customer said no rider came or called."
        if await open_case(session, tenant, order, CaseKind.UNJUSTIFIED_RTO, cost, "code", why):
            opened += 1
    return opened


async def update(
    session: AsyncSession,
    case_id: uuid.UUID,
    by: str,
    *,
    status: CaseStatus | None,
    recovered: int | None,
    reference: str | None,
    note: str,
    assigned: uuid.UUID | None,
) -> CourierCase:
    case = await session.get(CourierCase, case_id)
    if case is None:
        raise NotFound("case")
    if status is not None and status != case.status:
        if case.status in CLOSED and status not in CLOSED:
            raise AppError("case_closed", "This case is closed", status_code=409)
        case.timeline = [*case.timeline, _note(by, f"status: {status}")]
        case.status = status
        case.closed_at = utcnow() if status in CLOSED else None
    if recovered is not None:
        case.recovered = max(recovered, 0)
        case.timeline = [*case.timeline, _note(by, f"recovered: {case.recovered}")]
    if reference is not None:
        case.reference = reference.strip()[:80]
    if assigned is not None:
        case.assigned_staff_id = assigned
    if note.strip():
        case.timeline = [*case.timeline, _note(by, note.strip())]
    await session.flush()
    return case


async def complaint(session: AsyncSession, tenant: Tenant, case: CourierCase) -> str:
    """A plain complaint for the courier, built from the records only, in English, which
    couriers' support desks read."""
    order = await session.get(Order, case.order_id)
    shipment = await session.scalar(select(Shipment).where(Shipment.order_id == case.order_id))
    events = list(
        await session.scalars(
            select(ShipmentEvent)
            .where(ShipmentEvent.order_id == case.order_id)
            .order_by(ShipmentEvent.created_at)
        )
    )
    paid = await session.scalar(
        select(func.sum(CodSettlement.paid)).where(CodSettlement.order_id == case.order_id)
    )

    def money(amount: int | None) -> str:
        return shop_money(tenant, amount or 0, "en")

    titles = {
        CaseKind.FALSE_ATTEMPT: "Delivery attempt disputed by the customer",
        CaseKind.UNJUSTIFIED_RTO: "Return to origin without a confirmed attempt",
        CaseKind.COD_MISSING: "COD amount not settled",
        CaseKind.WRONG_DEDUCTION: "Charge deducted above the agreed rate",
        CaseKind.LOST: "Parcel without movement",
        CaseKind.DAMAGED: "Parcel delivered damaged",
    }
    lines = [
        f"Subject: {titles.get(CaseKind(case.kind), case.kind)} - "
        f"order {order.code if order else ''}",
        "",
        f"Merchant: {tenant.name}",
        f"Courier: {case.courier or 'not recorded'}",
        f"Tracking number: {(shipment.tracking_number if shipment else None) or 'not recorded'}",
        f"Order: {order.code if order else ''}, value {money(order.total if order else 0)}",
    ]
    if shipment:
        for label, when in (
            ("Booked/dispatched", shipment.dispatched_at),
            ("Delivered", shipment.delivered_at),
            ("Returned", shipment.returned_at),
        ):
            if when:
                lines.append(f"{label}: {when:%Y-%m-%d %H:%M} UTC")
        if shipment.cod_amount:
            lines.append(f"COD collected: {money(shipment.cod_amount)}")
        if shipment.courier_charge is not None:
            lines.append(f"Agreed courier charge: {money(shipment.courier_charge)}")
    if paid is not None:
        lines.append(f"Settled by courier so far: {money(int(paid))}")
    if events:
        lines += ["", "Recorded events:"]
        for event in events:
            who = {"customer": "Customer said", "courier": "Courier reported"}.get(
                event.source, "Recorded"
            )
            stamp = f"{event.created_at:%Y-%m-%d %H:%M} UTC"
            lines.append(f"- {stamp}: {who}: {event.kind}. {event.note}".rstrip())
    lines += [
        "",
        f"Amount in question: {money(case.at_stake)}",
        "We ask you to investigate and confirm the outcome, with your scan history and any "
        "call or delivery evidence for this parcel.",
    ]
    return "\n".join(lines)


def out(case: CourierCase, code: str) -> dict[str, Any]:
    return {
        "id": str(case.id),
        "order": code,
        "kind": case.kind,
        "status": case.status,
        "courier": case.courier,
        "at_stake": case.at_stake,
        "recovered": case.recovered,
        "reference": case.reference,
        "opened_by": case.opened_by,
        "assigned_staff_id": str(case.assigned_staff_id) if case.assigned_staff_id else None,
        "timeline": case.timeline,
        "created_at": case.created_at.isoformat(),
    }

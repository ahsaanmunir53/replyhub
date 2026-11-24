"""Delivery attempt checks: when a courier says it tried and could not deliver, the customer
is asked on their own chat whether a rider came or called, and their answer is recorded.

"Nobody came" opens a false-attempt case; "yes, they came" closes the question. Both are
kept as what the customer said, next to what the courier said, never as proof by itself.
Outside WhatsApp's 24-hour window the question cannot go out; the owner then sees that.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from chatfront.channels.language import chat_language
from chatfront.channels.notify import send_to
from chatfront.channels.types import Button, Outbound, OutButtons, OutText
from chatfront.core.i18n import t
from chatfront.core.models import Tenant
from chatfront.delivery.models import Shipment
from chatfront.delivery.shipping import order_by_code
from chatfront.guardian.cases import open_case
from chatfront.guardian.models import CaseKind, EventKind, ShipmentEvent
from chatfront.orders.models import Order

if TYPE_CHECKING:
    import uuid

    from chatfront.channels.conversation import Turn
    from chatfront.services import Services

PREFIX = "guard:"


async def attempt_failed(
    services: Services, tenant_id: uuid.UUID, code: str, note: str, source: str
) -> bool:
    """Record the courier's failed attempt and ask the customer. True if the question went out."""
    async with services.db.tenant(tenant_id) as session:
        tenant = await session.get(Tenant, tenant_id)
        assert tenant is not None
        order = await order_by_code(session, code)
        session.add(
            ShipmentEvent(
                tenant_id=tenant_id,
                order_id=order.id,
                kind=EventKind.ATTEMPT_FAILED,
                source=source,
                note=note.strip()[:300],
            )
        )
        lang = await chat_language(session, tenant, order.conversation_id)
        conversation_id = order.conversation_id
    if conversation_id is None:
        return False
    question = OutButtons(
        t("guard.ask_attempt", lang, code=order.code),
        (
            Button(f"{PREFIX}yes:{order.code}", t("guard.ask_yes", lang)),
            Button(f"{PREFIX}no:{order.code}", t("guard.ask_no", lang)),
        ),
    )
    return await send_to(services, tenant_id, conversation_id, question, lang)


async def answer(services: Services, turn: Turn, tapped: str | None) -> list[Outbound] | None:
    """The customer's tap on the attempt question; None when the tap is something else."""
    if not tapped or not tapped.startswith(PREFIX):
        return None
    said, _, code = tapped.removeprefix(PREFIX).partition(":")
    if said not in ("yes", "no") or not code:
        return None
    async with services.db.tenant(turn.tenant.id) as session:
        order = await session.scalar(
            select(Order).where(
                Order.code == code, Order.customer_id == turn.conversation.customer_id
            )
        )
        if order is None:
            return None
        denied = said == "no"
        session.add(
            ShipmentEvent(
                tenant_id=turn.tenant.id,
                order_id=order.id,
                kind=EventKind.CUSTOMER_DENIED if denied else EventKind.CUSTOMER_CONFIRMED,
                source="customer",
                note="",
            )
        )
        if denied:
            shipment = await session.scalar(select(Shipment).where(Shipment.order_id == order.id))
            charge = (shipment.courier_charge or 0) if shipment else 0
            await open_case(
                session,
                turn.tenant,
                order,
                CaseKind.FALSE_ATTEMPT,
                charge,
                "code",
                "The courier reported a failed attempt; the customer said nobody came or called.",
            )
    key = "guard.thanks_no" if denied else "guard.thanks_yes"
    return [OutText(t(key, turn.lang, code=code))]

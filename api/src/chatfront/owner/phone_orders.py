"""Orders that came by phone call or in the shop (ReplyHub): the owner types them in, so every
order, wherever it came from, sits in one list with the same stock, delivery and books.

It runs through the same checkout as the shop page, so prices, stock and delivery charges are
worked out by code, never typed by hand. The order is marked as a phone order; it is cash on
delivery, as the business takes payment itself.
"""

from __future__ import annotations

import secrets
import uuid
from typing import Annotated

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from chatfront.audit.service import Actor, ActorType, record
from chatfront.catalog.service import load_items
from chatfront.channels.models import Conversation, Party
from chatfront.core.errors import AppError, NotFound
from chatfront.core.models import Tenant
from chatfront.orders.checkout import CheckoutIn, DetailsIn, LineIn, PlacedOut, place_from_page
from chatfront.orders.models import Order
from chatfront.owner.rights import Can
from chatfront.owner.routes import ServicesDep, needs
from chatfront.owner.sessions import OwnerSession

router = APIRouter(prefix="/api/owner/orders")
OrdersDep = Annotated[OwnerSession, needs(Can.ORDERS)]


class PhoneLine(BaseModel):
    variant_id: uuid.UUID
    quantity: int = Field(ge=1, le=99)


class PhoneOrder(BaseModel):
    lines: list[PhoneLine] = Field(min_length=1, max_length=20)
    details: DetailsIn


@router.post("/phone")
async def add_phone_order(body: PhoneOrder, session: OrdersDep, services: ServicesDep) -> PlacedOut:
    async with services.db.tenant(session.tenant_id) as db:
        tenant = await db.get(Tenant, session.tenant_id)
        items = await load_items(db)
    if tenant is None:
        raise NotFound("shop")
    ids: dict[uuid.UUID, str] = {
        variant.id: item.catalog_id(variant) for item in items for variant in item.variants
    }
    missing = [str(line.variant_id) for line in body.lines if line.variant_id not in ids]
    if missing:
        raise AppError("not_found", "A product in this order is not on sale", status_code=409)
    placed = await place_from_page(
        services,
        tenant,
        f"phone-{secrets.token_urlsafe(18)}",  # its own record, never a real visitor's chat
        CheckoutIn(
            lines=[
                LineIn(item=ids[line.variant_id], quantity=line.quantity) for line in body.lines
            ],
            details=body.details,
            payment_method="cod",
            source="phone",
        ),
    )
    async with services.db.tenant(session.tenant_id) as db:
        # The order's own record chat is no customer's chat: keep it out of the inbox.
        order = await db.scalar(select(Order).where(Order.code == placed.code))
        chat = (
            await db.get(Conversation, order.conversation_id)
            if order and order.conversation_id
            else None
        )
        if chat is not None:
            chat.party = Party.STAFF
        await record(
            db,
            session.tenant_id,
            Actor(ActorType.STAFF, str(session.staff_id)),
            "order.phone",
            entity=("order", placed.code),
        )
    return placed

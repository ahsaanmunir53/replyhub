"""Adding a product from a plain form (ReplyHub): name, price, stock and options, for owners who
would rather fill in boxes than tell the assistant. Same rules as every other way in."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter
from pydantic import BaseModel, Field

from chatfront.audit.service import Actor, ActorType
from chatfront.catalog.service import ProductInput, VariantInput, create_product
from chatfront.core.countries import get_pack
from chatfront.core.errors import NotFound
from chatfront.core.models import Tenant
from chatfront.core.money import to_minor
from chatfront.owner.rights import Can
from chatfront.owner.routes import ServicesDep, needs
from chatfront.owner.sessions import OwnerSession

router = APIRouter(prefix="/api/owner/products")
CatalogDep = Annotated[OwnerSession, needs(Can.CATALOG)]


class ProductForm(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    price: Decimal = Field(gt=0, le=Decimal("100000000"))
    unit_cost: Decimal | None = Field(default=None, ge=0, le=Decimal("100000000"))
    description: str = Field(default="", max_length=1000)
    stock: int | None = Field(default=None, ge=0, le=100000)
    # One option, such as colour or size, with its values: "Colour" and ["Blue", "Peach"].
    option: str = Field(default="", max_length=30)
    values: list[str] = Field(default_factory=list, max_length=20)


class Added(BaseModel):
    code: str
    name: str


@router.post("/form")
async def add_from_form(body: ProductForm, session: CatalogDep, services: ServicesDep) -> Added:
    async with services.db.tenant(session.tenant_id) as db:
        tenant = await db.get(Tenant, session.tenant_id)
        if tenant is None:
            raise NotFound("shop")
        digits = get_pack(tenant.country).minor_digits
        values = [v.strip()[:40] for v in body.values if v.strip()]
        option = body.option.strip() or "Option"
        variants = (
            tuple(VariantInput(options={option: v}, stock=body.stock) for v in values)
            if values
            else (VariantInput(stock=body.stock),)
        )
        item = await create_product(
            db,
            session.tenant_id,
            ProductInput(
                name=body.name,
                price=to_minor(body.price, digits),
                source="form",
                description=body.description,
                variants=variants,
            ),
            Actor(ActorType.STAFF, str(session.staff_id)),
        )
        if body.unit_cost is not None:
            item.product.unit_cost = to_minor(body.unit_cost, digits)
    return Added(code=item.product.code, name=item.product.name)

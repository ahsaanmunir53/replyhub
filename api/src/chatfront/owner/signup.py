"""Signing a business up for ReplyHub: a short form makes the business on the Basic plan, with
its owner, and signs the owner straight into the console.

The form asks only what the assistant and the plan need: the business's name and kind, its
country and city, the owner's name, email and WhatsApp number (so the owner's own messages
are known as the owner's, and the owner can ask for a new sign-in link on WhatsApp). The
operator can close sign-ups with SIGNUP_OPEN=false.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from chatfront.core.countries import get_pack
from chatfront.core.errors import AppError, Forbidden
from chatfront.core.models import Tenant, Tier
from chatfront.core.phone import hash_phone, normalise_phone
from chatfront.core.provisioning import NewShop, create_shop, free_slug, owner_of
from chatfront.owner.routes import ServicesDep
from chatfront.owner.sessions import console_link, issue
from chatfront.owner.subscription import PLAN_KEY, Plan
from chatfront.templates import all_templates

router = APIRouter(prefix="/api/signup")
COUNTRIES = ("AE", "SA", "PK", "IN", "BD")  # where ReplyHub is offered first
LANGS = ("en", "ar", "ur-Latn", "ur", "hi", "bn", "pa-Arab", "sd", "ps")
Country = Literal["AE", "SA", "PK", "IN", "BD"]
Lang = Literal["en", "ar", "ur-Latn", "ur", "hi", "bn", "pa-Arab", "sd", "ps"]


class Option(BaseModel):
    id: str
    name: str


class Options(BaseModel):
    open: bool
    business_types: list[Option]
    countries: list[Option]


class SignupIn(BaseModel):
    business_name: str = Field(min_length=2, max_length=120)
    business_type: str = Field(min_length=2, max_length=40)
    country: Country
    city: str = Field(min_length=2, max_length=80)
    owner_name: str = Field(min_length=2, max_length=80)
    email: str = Field(min_length=5, max_length=160, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    whatsapp: str = Field(min_length=6, max_length=24)
    lang: Lang = "en"


class SignedUp(BaseModel):
    slug: str
    token: str
    console_url: str


@router.get("")
async def options(services: ServicesDep) -> Options:
    return Options(
        open=services.settings.signup_open,
        business_types=[Option(id=k, name=v.name.en) for k, v in sorted(all_templates().items())],
        countries=[Option(id=c, name=get_pack(c).name) for c in COUNTRIES],
    )


@router.post("")
async def sign_up(body: SignupIn, request: Request, services: ServicesDep) -> SignedUp:
    """The console link carries the owner's first sign-in (seven days)."""
    if not services.settings.signup_open:
        raise Forbidden("Sign-ups are closed for now")
    client = request.client.host if request.client else "unknown"
    services.limiter.check(f"signup:{client}")
    if body.business_type not in all_templates():
        raise AppError("unknown_type", "Choose one of the listed kinds of business")
    pack = get_pack(body.country)
    number = normalise_phone(
        body.whatsapp,
        pack.phone.calling_code,
        trunk_prefix=pack.phone.trunk_prefix,
        national_lengths=pack.phone.national_lengths,
    )
    name = " ".join(body.business_name.split())
    slug = await free_slug(services.db, name)
    tenant = await create_shop(
        services.db,
        services.registries.modules,
        NewShop(
            slug=slug,
            name=name,
            template=body.business_type,
            tier=Tier.SMALL,
            owner_name=" ".join(body.owner_name.split()),
            owner_email=str(body.email),
            profile={"city": " ".join(body.city.split()), PLAN_KEY: Plan.BASIC.value},
            owner_phone_hash=hash_phone(number, services.keys.phone_hash_key),
        ),
    )
    async with services.db.system() as session:
        stored = await session.get(Tenant, tenant.id)
        assert stored is not None
        stored.country, stored.currency = pack.code, pack.currency
        stored.timezone, stored.default_lang = pack.timezone, body.lang
    owner = await owner_of(services.db, tenant.id)
    token = issue(owner.id, tenant.id, services.settings.secret_key.get_secret_value())
    return SignedUp(
        slug=slug, token=token, console_url=console_link(services.settings.web_url, token)
    )

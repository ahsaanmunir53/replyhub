"""The rules screen in the console: the owner reads and saves the assistant's rules."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter

from chatfront.audit.service import Actor, ActorType, record
from chatfront.core.errors import NotFound
from chatfront.core.models import Tenant
from chatfront.owner.rights import Can
from chatfront.owner.routes import ServicesDep, needs
from chatfront.owner.rules import FAQS, TEXT_KEYS, TONE, Rules, rules_of
from chatfront.owner.sessions import OwnerSession

router = APIRouter(prefix="/api/owner/rules")
SettingsDep = Annotated[OwnerSession, needs(Can.SETTINGS)]


@router.get("")
async def get_rules(session: SettingsDep, services: ServicesDep) -> Rules:
    async with services.db.tenant(session.tenant_id) as db:
        tenant = await db.get(Tenant, session.tenant_id)
        if tenant is None:
            raise NotFound("shop")
        return rules_of(tenant)


@router.put("")
async def save_rules(body: Rules, session: SettingsDep, services: ServicesDep) -> Rules:
    async with services.db.tenant(session.tenant_id) as db:
        tenant = await db.get(Tenant, session.tenant_id)
        if tenant is None:
            raise NotFound("shop")
        values: dict[str, Any] = {key: getattr(body, key).strip() for key in TEXT_KEYS}
        values[TONE] = body.tone
        values[FAQS] = [
            {"question": f.question.strip(), "answer": f.answer.strip()} for f in body.faqs
        ]
        tenant.profile = {**(tenant.profile or {}), **values}
        await record(
            db,
            tenant.id,
            Actor(ActorType.STAFF, str(session.staff_id)),
            "settings.rules",
            entity=("tenant", str(tenant.id)),
            data={"filled": sorted(k for k in TEXT_KEYS if values[k]), "faqs": len(body.faqs)},
        )
        return rules_of(tenant)

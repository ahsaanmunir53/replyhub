"""How much the assistant has answered, and whether it may answer again (ReplyHub).

The trial answers `trial_chats` chats, `trial_replies` times in all, for `trial_days` days. A
paid plan answers its monthly allowance (`plan_replies`) until `paid_until` plus a few grace
days. Past any of these the customer is told the team will reply, the chat waits for the
owner, and the owner is told once why the assistant stopped. Nothing here applies with
selling on (Chatfront).

Counting is one atomic upsert per reply, so two replies at the same moment never lose a count.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import case, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from chatfront.books.ledger import today
from chatfront.core.ids import new_id
from chatfront.core.models import Tenant
from chatfront.owner.models import AssistantUsage
from chatfront.owner.subscription import Plan, allowance, lapsed, plan_of
from chatfront.stock import notices

if TYPE_CHECKING:
    from chatfront.core.settings import Settings

TRIAL = "trial"
WARN_SHARE = 0.8  # the owner hears when this share of the month's replies is used


class Stop(StrEnum):
    TRIAL_OVER = "trial_over"
    ALLOWANCE = "allowance"  # the month's replies are used up
    LAPSED = "lapsed"  # the payment ran out


@dataclass(frozen=True, slots=True)
class Standing:
    """Where a business stands, for the console and the gate."""

    plan: Plan
    period: str
    used: int
    limit: int  # replies allowed in the period
    chats_used: int
    chats_limit: int  # trial only; 0 on paid plans
    trial_ends: date | None
    stop: Stop | None


def period_of(tenant: Tenant, day: date) -> str:
    return TRIAL if plan_of(tenant) == Plan.TRIAL else day.strftime("%Y-%m")


async def _row(session: AsyncSession, period: str) -> AssistantUsage | None:
    return await session.scalar(select(AssistantUsage).where(AssistantUsage.period == period))


async def standing(
    session: AsyncSession,
    settings: Settings,
    tenant: Tenant,
    conversation_id: uuid.UUID | None = None,
) -> Standing:
    """The plan, what is used, and the reason the assistant must stop, if any. With a
    conversation, a trial chat already answered may carry on even when the chats are used."""
    day = today(tenant)
    plan = plan_of(tenant)
    period = period_of(tenant, day)
    if tenant.is_demo:  # the public demo shops answer every visitor; rate limits guard them
        return Standing(plan, period, 0, 0, 0, 0, None, None)
    row = await _row(session, period)
    used = row.replies if row else 0
    chats = [str(c) for c in (row.chats if row else [])]
    if plan == Plan.TRIAL:
        ends = tenant.created_at.date() + timedelta(days=settings.trial_days)
        new_chat = conversation_id is not None and str(conversation_id) not in chats
        over = (
            day > ends
            or used >= settings.trial_replies
            or (new_chat and len(chats) >= settings.trial_chats)
            or (conversation_id is None and len(chats) >= settings.trial_chats)
        )
        return Standing(
            plan,
            period,
            used,
            settings.trial_replies,
            len(chats),
            settings.trial_chats,
            ends,
            Stop.TRIAL_OVER if over else None,
        )
    limit = allowance(settings.plan_replies, plan)
    stop = Stop.LAPSED if lapsed(tenant, day) else Stop.ALLOWANCE if used >= limit else None
    return Standing(plan, period, used, limit, 0, 0, None, stop)


async def count(
    session: AsyncSession,
    settings: Settings,
    tenant: Tenant,
    conversation_id: uuid.UUID,
    *,
    model: bool,
) -> None:
    """One assistant reply: count it, remember the trial chat, and warn the owner once when
    the month's replies are nearly used."""
    period = period_of(tenant, today(tenant))
    chat = [str(conversation_id)]
    trial = period == TRIAL
    row = AssistantUsage
    upsert = (
        insert(row)
        .values(
            id=new_id(),
            tenant_id=tenant.id,
            period=period,
            replies=1,
            model_replies=int(model),
            chats=chat if trial else [],
            warned=False,
            stopped=False,
        )
        .on_conflict_do_update(
            index_elements=[row.tenant_id, row.period],
            set_={
                "replies": row.replies + 1,
                "model_replies": row.model_replies + int(model),
                # A trial chat is added once; month rows keep no chats.
                "chats": (
                    case((row.chats.contains(chat), row.chats), else_=row.chats.concat(chat))
                    if trial
                    else row.chats
                ),
            },
        )
        .returning(row.replies, row.warned)
    )
    replies, warned = (await session.execute(upsert)).one()
    if trial or warned:
        return
    limit = allowance(settings.plan_replies, plan_of(tenant))
    if limit and replies >= limit * WARN_SHARE:
        await session.execute(
            update(row).where(row.tenant_id == tenant.id, row.period == period).values(warned=True)
        )
        await notices.queue(
            session,
            tenant.id,
            "plan_nearly_used",
            "plan.notice_nearly",
            {"used": replies, "limit": limit},
        )


async def stopped(session: AsyncSession, tenant: Tenant, reason: Stop) -> None:
    """Tell the owner once per period why the assistant stopped answering."""
    period = period_of(tenant, today(tenant))
    row = AssistantUsage
    upsert = (
        insert(row)
        .values(
            id=new_id(),
            tenant_id=tenant.id,
            period=period,
            replies=0,
            model_replies=0,
            chats=[],
            warned=False,
            stopped=True,
        )
        .on_conflict_do_update(
            index_elements=[row.tenant_id, row.period],
            set_={"stopped": True},
            where=row.stopped.is_(False),
        )
        .returning(row.id)
    )
    if (await session.execute(upsert)).first() is None:
        return  # already told
    await notices.queue(
        session, tenant.id, f"plan_{reason.value}", f"plan.notice_{reason.value}", {}
    )

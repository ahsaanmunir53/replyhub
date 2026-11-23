"""Departments (ReplyHub): teams inside the business, such as Sales, Delivery or Complaints,
so chats reach the right people like tickets.

The owner gives each department a few keywords ("price, order, buy" for Sales; "late,
broken, refund" for Complaints) and puts staff in it. The first customer message that uses
one of the words routes the chat to that department, once. When the chat is handed to a
person, it goes to the member of that department with the fewest open chats. The inbox can
then show one department at a time. Matching is plain word matching, no model and no cost.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from chatfront.channels.models import Conversation
from chatfront.core.errors import AppError, NotFound
from chatfront.core.models import Staff
from chatfront.owner.models import Department
from chatfront.owner.rights import Can, rights
from chatfront.owner.routes import ServicesDep, needs
from chatfront.owner.rules import content_words
from chatfront.owner.sessions import OwnerSession

router = APIRouter(prefix="/api/owner/departments")
TeamDep = Annotated[OwnerSession, needs(Can.TEAM)]
ViewDep = Annotated[OwnerSession, needs(Can.CHATS)]
MAX_DEPARTMENTS = 20
HANDOVER = "handover"


def _words(keywords: list[str]) -> set[str]:
    found: set[str] = set()
    for keyword in keywords:
        found |= content_words(keyword)
    return found


async def match(session: AsyncSession, text: str) -> uuid.UUID | None:
    """The department whose keywords the text uses most; the oldest wins a tie."""
    asked = content_words(text)
    if not asked:
        return None
    best: tuple[int, uuid.UUID] | None = None
    for department in await session.scalars(select(Department).order_by(Department.created_at)):
        hits = len(asked & _words([str(k) for k in department.keywords or []]))
        if hits and (best is None or hits > best[0]):
            best = (hits, department.id)
    return best[1] if best else None


async def member_for(session: AsyncSession, department_id: uuid.UUID) -> uuid.UUID | None:
    """The active member of the department who answers chats and has the fewest open ones."""
    members = [
        staff
        for staff in await session.scalars(
            select(Staff).where(Staff.department_id == department_id, Staff.active.is_(True))
        )
        if Can.CHATS in rights(staff.role)
    ]
    if not members:
        return None
    open_chats: dict[uuid.UUID | None, int] = dict(
        (
            await session.execute(
                select(Conversation.assigned_staff_id, func.count())
                .where(
                    Conversation.status == HANDOVER,
                    Conversation.assigned_staff_id.in_([m.id for m in members]),
                )
                .group_by(Conversation.assigned_staff_id)
            )
        ).all()
    )
    return min(members, key=lambda m: (open_chats.get(m.id, 0), m.created_at)).id


class DepartmentIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    keywords: list[str] = Field(default_factory=list, max_length=40)


class DepartmentOut(BaseModel):
    id: uuid.UUID
    name: str
    keywords: list[str]
    members: list[uuid.UUID]
    open_chats: int


class MemberIn(BaseModel):
    staff_id: uuid.UUID
    department_id: uuid.UUID | None


def _clean(keywords: list[str]) -> list[str]:
    seen: list[str] = []
    for keyword in keywords:
        word = " ".join(keyword.split())[:40]
        if word and word.lower() not in {s.lower() for s in seen}:
            seen.append(word)
    return seen


async def _list(session: AsyncSession) -> list[DepartmentOut]:
    staff = list(await session.scalars(select(Staff).where(Staff.active.is_(True))))
    counts: dict[uuid.UUID | None, int] = dict(
        (
            await session.execute(
                select(Conversation.department_id, func.count())
                .where(Conversation.status == HANDOVER, Conversation.department_id.is_not(None))
                .group_by(Conversation.department_id)
            )
        ).all()
    )
    return [
        DepartmentOut(
            id=d.id,
            name=d.name,
            keywords=[str(k) for k in d.keywords or []],
            members=[s.id for s in staff if s.department_id == d.id],
            open_chats=counts.get(d.id, 0),
        )
        for d in await session.scalars(select(Department).order_by(Department.created_at))
    ]


@router.get("")
async def list_departments(session: ViewDep, services: ServicesDep) -> list[DepartmentOut]:
    async with services.db.tenant(session.tenant_id) as db:
        return await _list(db)


@router.post("")
async def add_department(
    body: DepartmentIn, session: TeamDep, services: ServicesDep
) -> list[DepartmentOut]:
    async with services.db.tenant(session.tenant_id) as db:
        count = await db.scalar(select(func.count()).select_from(Department))
        if (count or 0) >= MAX_DEPARTMENTS:
            raise AppError("too_many", "A business can have up to 20 departments")
        db.add(
            Department(
                tenant_id=session.tenant_id,
                name=" ".join(body.name.split()),
                keywords=_clean(body.keywords),
            )
        )
        await db.flush()
        return await _list(db)


@router.put("/{department_id}")
async def edit_department(
    department_id: uuid.UUID, body: DepartmentIn, session: TeamDep, services: ServicesDep
) -> list[DepartmentOut]:
    async with services.db.tenant(session.tenant_id) as db:
        found = await db.get(Department, department_id)
        if found is None:
            raise NotFound("department")
        found.name, found.keywords = " ".join(body.name.split()), _clean(body.keywords)
        await db.flush()
        return await _list(db)


@router.delete("/{department_id}")
async def remove_department(
    department_id: uuid.UUID, session: TeamDep, services: ServicesDep
) -> list[DepartmentOut]:
    async with services.db.tenant(session.tenant_id) as db:
        found = await db.get(Department, department_id)
        if found is None:
            raise NotFound("department")
        await db.delete(found)
        await db.flush()
        return await _list(db)


@router.put("/members/set")
async def set_member(
    body: MemberIn, session: TeamDep, services: ServicesDep
) -> list[DepartmentOut]:
    async with services.db.tenant(session.tenant_id) as db:
        staff = await db.get(Staff, body.staff_id)
        if staff is None:
            raise NotFound("staff")
        if body.department_id is not None and await db.get(Department, body.department_id) is None:
            raise NotFound("department")
        staff.department_id = body.department_id
        await db.flush()
        return await _list(db)

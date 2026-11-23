"""Signing in with an email and a password, so an owner or staff member gets back into the
console from any browser without a new link.

The password is set at sign-up, or later in the console. It is stored only as a salted scrypt
hash; hashing runs off the event loop, so a sign-in never holds up other requests. A wrong
email and a wrong password give the same answer, and tries are limited per address and per
email. One email can own several businesses: when the password fits more than one, the person
picks the business.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import secrets
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from chatfront.core.errors import AppError
from chatfront.core.models import Staff, Tenant
from chatfront.owner.routes import ServicesDep, active_staff
from chatfront.owner.sessions import NotSignedIn, OwnerSession, issue

router = APIRouter(prefix="/api/owner")
LOGIN_TTL = timedelta(days=30)
MAX_MATCHES = 10
# scrypt cost: about 50 ms on a laptop core, still well under a second on a small server.
_N, _R, _P = 2**14, 8, 1


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, dklen=32, maxmem=64 << 20)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = _scrypt(password, salt, _N, _R, _P)
    enc = base64.urlsafe_b64encode
    return f"scrypt${_N}${_R}${_P}${enc(salt).decode()}${enc(digest).decode()}"


def password_fits(password: str, stored: str | None) -> bool:
    try:
        kind, n, r, p, salt, digest = (stored or "").split("$")
        if kind != "scrypt":
            return False
        dec = base64.urlsafe_b64decode
        found = _scrypt(password, dec(salt), int(n), int(r), int(p))
        return hmac.compare_digest(found, dec(digest))
    except (ValueError, TypeError):
        return False


class LoginIn(BaseModel):
    email: str = Field(min_length=5, max_length=160)
    password: str = Field(min_length=1, max_length=128)
    shop: str | None = Field(default=None, max_length=80)  # the business, when several fit


class ShopChoice(BaseModel):
    slug: str
    name: str


class LoggedIn(BaseModel):
    token: str | None = None  # None while the person still has to pick a business
    slug: str | None = None
    shops: list[ShopChoice] = []


class PasswordIn(BaseModel):
    password: str = Field(min_length=8, max_length=128)
    current: str | None = Field(default=None, max_length=128)


@router.post("/login")
async def login(body: LoginIn, request: Request, services: ServicesDep) -> LoggedIn:
    email = body.email.strip().lower()
    client = request.client.host if request.client else "unknown"
    services.limiter.check(f"login:{client}")
    services.limiter.check(f"login-email:{email}")
    async with services.db.system() as db:
        rows = (
            await db.execute(
                select(Staff, Tenant)
                .join(Tenant, Tenant.id == Staff.tenant_id)
                .where(
                    func.lower(Staff.email) == email,
                    Staff.active.is_(True),
                    Staff.password_hash.is_not(None),
                )
                .order_by(Staff.created_at.desc())
                .limit(MAX_MATCHES)
            )
        ).all()
    fits = []
    for staff, tenant in rows:
        if body.shop and tenant.slug != body.shop:
            continue
        if await asyncio.to_thread(password_fits, body.password, staff.password_hash):
            fits.append((staff, tenant))
    if not fits:
        raise AppError("login_failed", "The email or password is wrong", status_code=401)
    if len(fits) > 1:
        return LoggedIn(shops=[ShopChoice(slug=t.slug, name=t.name) for _, t in fits])
    staff, tenant = fits[0]
    token = issue(
        staff.id,
        tenant.id,
        services.settings.secret_key.get_secret_value(),
        ttl=LOGIN_TTL,
        session_version=staff.session_version,
    )
    return LoggedIn(token=token, slug=tenant.slug)


@router.put("/password")
async def set_password(
    body: PasswordIn,
    session: Annotated[OwnerSession, Depends(active_staff)],
    services: ServicesDep,
) -> dict[str, bool]:
    """Set one's own password. Changing an existing one needs the current password, so a
    session left open on someone else's phone cannot lock the owner out."""
    services.limiter.check(f"password:{session.staff_id}")
    async with services.db.tenant(session.tenant_id) as db:
        staff = await db.get(Staff, session.staff_id)
        if staff is None:
            raise NotSignedIn
        if staff.password_hash and not await asyncio.to_thread(
            password_fits, body.current or "", staff.password_hash
        ):
            raise AppError("wrong_password", "The current password is wrong", status_code=403)
        staff.password_hash = await asyncio.to_thread(hash_password, body.password)
    return {"ok": True}

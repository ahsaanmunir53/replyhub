"""Signing a business up for ReplyHub, connecting its WhatsApp number, and the owner asking
for a new sign-in link on WhatsApp."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
import respx
from sqlalchemy import select

from chatfront.core.i18n import t
from chatfront.core.models import Staff, Tenant
from chatfront.core.phone import hash_phone
from chatfront.services import Services
from tests.integration.chat import Client, signed, wa_message
from tests.integration.test_books_shield import LANG, drain, graph_mock, owner_on_whatsapp, texts

CRON = {"X-Cron-Secret": "test-cron-secret"}
FORM: dict[str, Any] = {
    "business_name": "Al Noor Perfumes",
    "business_type": "services",
    "country": "AE",
    "city": "Dubai",
    "owner_name": "Sara Khan",
    "email": "sara@alnoor.example",
    "whatsapp": "050 123 4567",
    "lang": "en",
}


@pytest.fixture
def replyhub(
    app: tuple[Client, Services], monkeypatch: pytest.MonkeyPatch
) -> tuple[Client, Services]:
    client, services = app
    monkeypatch.setattr(services.settings, "commerce", False)
    return client, services


async def test_a_business_signs_up_and_lands_in_its_console(
    replyhub: tuple[Client, Services],
) -> None:
    client, services = replyhub
    options = (await client.get("/api/signup")).json()
    assert options["open"] is True
    assert {"AE", "PK"} <= {c["id"] for c in options["countries"]}
    assert "services" in {b["id"] for b in options["business_types"]}

    made = await client.post("/api/signup", json=FORM)
    assert made.status_code == 200, made.text
    body = made.json()
    assert body["slug"] == "al-noor-perfumes"
    assert body["console_url"].endswith(f"#t={body['token']}")
    me = (
        await client.get("/api/owner/me", headers={"Authorization": f"Bearer {body['token']}"})
    ).json()
    assert (me["shop_name"], me["plan"], me["country"], me["currency"]) == (
        "Al Noor Perfumes",
        "basic",
        "AE",
        "AED",
    )
    assert me["whatsapp_connected"] is False
    async with services.db.system() as session:
        tenant = await session.scalar(select(Tenant).where(Tenant.slug == body["slug"]))
        assert tenant is not None
        owner = await session.scalar(select(Staff).where(Staff.tenant_id == tenant.id))
    assert tenant.timezone == "Asia/Dubai"
    assert owner is not None
    assert owner.phone_hash == hash_phone("+971501234567", services.keys.phone_hash_key)

    again = await client.post("/api/signup", json=FORM)
    assert again.json()["slug"] == "al-noor-perfumes-2"  # a second business of the same name
    bad = await client.post("/api/signup", json={**FORM, "email": "not-an-email"})
    assert bad.status_code == 422


async def test_sign_ups_can_be_closed(
    replyhub: tuple[Client, Services], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, services = replyhub
    monkeypatch.setattr(services.settings, "signup_open", False)
    assert (await client.get("/api/signup")).json()["open"] is False
    assert (await client.post("/api/signup", json=FORM)).status_code == 403


async def test_the_operator_connects_the_business_number(
    replyhub: tuple[Client, Services],
) -> None:
    client, _ = replyhub
    body = (await client.post("/api/signup", json=FORM)).json()
    connect = {
        "shop": body["slug"],
        "channel": "whatsapp",
        "account_id": "PN-ALNOOR",
        "handle": "+971501234567",
        "token": "EAAG-business-own-token",
    }
    assert (await client.post("/internal/connect", json=connect)).status_code == 403
    done = await client.post("/internal/connect", headers=CRON, json=connect)
    assert done.status_code == 200, done.text
    assert "4567" in done.json()["display"]
    me = (
        await client.get("/api/owner/me", headers={"Authorization": f"Bearer {body['token']}"})
    ).json()
    assert me["whatsapp_connected"] is True


async def test_the_owner_gets_a_sign_in_link_on_whatsapp_on_any_plan(
    replyhub: tuple[Client, Services],
) -> None:
    client, services = replyhub
    number = "923009995555"
    with respx.mock:
        graph = graph_mock()
        await owner_on_whatsapp(client, services, number)
        sent = len(graph.calls)
        body, headers = signed(wa_message(f"wamid.{uuid.uuid4().hex}", sender=number, body="login"))
        await client.post("/webhooks/meta", content=body, headers=headers)
        await drain(services)
        [reply] = [m["text"]["body"] for m in texts(graph, sent) if m["type"] == "text"]
    link = next(word for word in reply.split() if "/owner#t=" in word)
    assert "/owner#t=" in reply
    assert reply == t("owner.sign_in_link", LANG, link=link)

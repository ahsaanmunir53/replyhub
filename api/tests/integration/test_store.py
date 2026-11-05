"""The website store (ReplyHub, Pro plan) on real PostgreSQL: connect a Shopify store with a
read-only key, read its orders, and the owner's report on WhatsApp, daily and on request."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx
from sqlalchemy import select

from chatfront.core.i18n import t
from chatfront.core.reseal import reseal
from chatfront.core.secretbox import remember_previous, unseal
from chatfront.jobs.queue import enqueue
from chatfront.services import Services
from chatfront.store import clients, routes, service
from chatfront.store.models import StoreConnection
from tests.integration.chat import Client, owner_auth, shop_id, signed, wa_message
from tests.integration.conftest import SHOP
from tests.integration.test_books_shield import LANG, drain, graph_mock, owner_on_whatsapp, texts

CRON = {"X-Cron-Secret": "test-cron-secret"}
STORE = "https://gulmohar.myshopify.com"
ORDERS = f"{STORE}/admin/api/{clients.SHOPIFY_API}/orders.json"
KEY = "shpat_read_only_test_key"


def order(n: int, *, total: str, financial: str = "paid", cod: bool = False, **extra: Any) -> dict:
    return {
        "id": 1000 + n,
        "name": f"#{1000 + n}",
        "created_at": datetime.now(UTC).isoformat(),
        "total_price": total,
        "currency": "PKR",
        "financial_status": financial,
        "fulfillment_status": None,
        "cancelled_at": None,
        "payment_gateway_names": ["Cash on Delivery (COD)"] if cod else ["shopify_payments"],
        **extra,
    }


SHOP_ORDERS = [
    order(1, total="4850.00"),
    order(2, total="2200.00", financial="pending", cod=True),
    order(3, total="1500.00", cancelled_at=datetime.now(UTC).isoformat()),
]


@pytest.fixture
def pro(app: tuple[Client, Services], monkeypatch: pytest.MonkeyPatch) -> tuple[Client, Services]:
    client, services = app
    monkeypatch.setattr(services.settings, "commerce", False)

    async def public(url: str) -> None:  # the test store resolves to no real address
        return None

    monkeypatch.setattr(clients, "check_public", public)
    monkeypatch.setattr(routes, "check_public", public)
    return client, services


async def set_plan(client: Client, plan: str) -> None:
    response = await client.post("/internal/plan", headers=CRON, json={"shop": SHOP, "plan": plan})
    assert response.status_code == 200


async def connect(client: Client, owner: dict[str, str]) -> dict[str, Any]:
    body = {"platform": "shopify", "store_url": "gulmohar.myshopify.com", "key": KEY}
    response = await client.put("/api/owner/store", headers=owner, json=body)
    assert response.status_code == 200, response.text
    synced = await client.post("/api/owner/store/sync", headers=owner)
    return synced.json()


async def test_basic_has_no_website_store(pro: tuple[Client, Services]) -> None:
    client, services = pro
    owner = await owner_auth(services)
    assert (await client.get("/api/owner/store", headers=owner)).status_code == 403


async def test_the_owner_connects_shopify_and_sees_today(pro: tuple[Client, Services]) -> None:
    client, services = pro
    await set_plan(client, "pro")
    owner = await owner_auth(services)
    with respx.mock:
        route = respx.get(ORDERS).mock(
            return_value=httpx.Response(200, json={"orders": SHOP_ORDERS})
        )
        store = await connect(client, owner)
        assert route.calls[0].request.headers["X-Shopify-Access-Token"] == KEY
    assert store["connected"] is True
    assert store["store_url"] == STORE
    assert store["key_set"] is True
    assert KEY not in str(store)  # the key never comes back
    assert store["last_error"] is None
    assert store["today"] == {
        "orders": 3,
        "sales": 705_000,  # 4,850 + 2,200; the cancelled one does not count
        "paid": 1,
        "cod": 1,
        "pending": 1,
        "closed": 1,
        "unsent": 2,
    }
    async with services.db.system() as session:
        link = await session.scalar(select(StoreConnection))
    assert link is not None
    assert KEY not in link.key_sealed  # sealed at rest

    refused = await client.put(
        "/api/owner/store",
        headers=owner,
        json={"platform": "shopify", "store_url": "http://evil.example", "key": KEY},
    )
    assert refused.status_code == 400  # only a myshopify.com address over https


async def test_a_refused_key_shows_in_the_console(pro: tuple[Client, Services]) -> None:
    client, services = pro
    await set_plan(client, "pro")
    owner = await owner_auth(services)
    with respx.mock:
        respx.get(ORDERS).mock(return_value=httpx.Response(401, json={"errors": "Invalid"}))
        store = await connect(client, owner)
    assert store["connected"] is True
    assert "401" in store["last_error"]


async def test_the_owner_asks_on_whatsapp_and_gets_the_daily_report(
    pro: tuple[Client, Services],
) -> None:
    client, services = pro
    await set_plan(client, "pro")
    owner = await owner_auth(services)
    number = "923009997777"
    with respx.mock:
        respx.get(ORDERS).mock(return_value=httpx.Response(200, json={"orders": SHOP_ORDERS}))
        graph = graph_mock()
        await connect(client, owner)
        await owner_on_whatsapp(client, services, number)
        sent = len(graph.calls)
        body, headers = signed(
            wa_message(f"wamid.{uuid.uuid4().hex}", sender=number, body="pending cod")
        )
        await client.post("/webhooks/meta", content=body, headers=headers)
        await drain(services)
        replies = [m["text"]["body"] for m in texts(graph, sent) if m["type"] == "text"]
        assert replies == [t("store.pending_cod", LANG, count=1, amount="Rs 2,200")]

        async with services.db.system() as session:
            day = (datetime.now(UTC) + timedelta(hours=5)).date().isoformat()
            await enqueue(
                session, service.REPORT_JOB, {"day": day}, tenant_id=await shop_id(session)
            )
        sent = len(graph.calls)
        await drain(services)
        report = [m["text"]["body"] for m in texts(graph, sent) if m["type"] == "text"]
        assert len(report) == 1
        assert "Orders: 3" in report[0]
        assert "Rs 7,050" in report[0]


async def test_basic_owner_commands_on_whatsapp_point_to_pro(pro: tuple[Client, Services]) -> None:
    client, services = pro
    number = "923009996666"
    with respx.mock:
        graph = graph_mock()
        await owner_on_whatsapp(client, services, number)
        replies = [m["text"]["body"] for m in texts(graph) if m["type"] == "text"]
    assert replies[-1] == t("plan.no_owner_whatsapp", LANG)


async def test_resealing_after_a_key_rotation(pro: tuple[Client, Services]) -> None:
    """The store key, sealed with the old SECRET_KEY, opens with the new one after reseal."""
    client, services = pro
    await set_plan(client, "pro")
    owner = await owner_auth(services)
    body = {"platform": "shopify", "store_url": "gulmohar.myshopify.com", "key": KEY}
    assert (await client.put("/api/owner/store", headers=owner, json=body)).status_code == 200
    old = services.settings.secret_key.get_secret_value()
    new = "rotated-secret-key-" + "z" * 32
    remember_previous([old])
    try:
        assert await reseal(services.db, new) >= 1
    finally:
        remember_previous([])
    async with services.db.system() as session:
        link = await session.scalar(select(StoreConnection))
    assert link is not None
    assert unseal(link.key_sealed, new) == KEY

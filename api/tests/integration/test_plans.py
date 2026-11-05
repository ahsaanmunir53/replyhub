"""ReplyHub plans on real PostgreSQL: a business gets the features it pays for, the operator
sets the plan, and Instagram waits for the Business plan."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from chatfront.channels.models import Message
from chatfront.services import Services
from tests.integration.chat import Client, owner_auth
from tests.integration.conftest import SHOP
from tests.integration.test_posting_sales import ig_dm, webhook

CRON = {"X-Cron-Secret": "test-cron-secret"}


@pytest.fixture
def replyhub(
    app: tuple[Client, Services], monkeypatch: pytest.MonkeyPatch
) -> tuple[Client, Services]:
    client, services = app
    monkeypatch.setattr(services.settings, "commerce", False)
    return client, services


async def set_plan(client: Client, plan: str) -> None:
    response = await client.post("/internal/plan", headers=CRON, json={"shop": SHOP, "plan": plan})
    assert response.status_code == 200


async def test_a_new_business_is_on_basic(replyhub: tuple[Client, Services]) -> None:
    client, services = replyhub
    owner = await owner_auth(services)
    me = (await client.get("/api/owner/me", headers=owner)).json()
    assert (me["plan"], me["features"]) == ("basic", ["assistant", "rules"])
    assert (await client.get("/api/owner/rules", headers=owner)).status_code == 200
    assert (await client.get("/api/owner/inbox", headers=owner)).status_code == 403
    assert (await client.get("/api/owner/team", headers=owner)).status_code == 403
    assert (await client.get("/api/owner/broadcasts", headers=owner)).status_code == 403


async def test_the_operator_moves_a_business_up(replyhub: tuple[Client, Services]) -> None:
    client, services = replyhub
    owner = await owner_auth(services)
    bad = await client.post("/internal/plan", json={"shop": SHOP, "plan": "business"})
    assert bad.status_code == 403  # only the operator, with the cron secret
    await set_plan(client, "pro")
    assert (await client.get("/api/owner/inbox", headers=owner)).status_code == 200
    assert (await client.get("/api/owner/team", headers=owner)).status_code == 403
    await set_plan(client, "business")
    assert (await client.get("/api/owner/team", headers=owner)).status_code == 200
    me = (await client.get("/api/owner/me", headers=owner)).json()
    assert me["plan"] == "business"
    assert {"instagram", "messenger", "team", "broadcasts"} <= set(me["features"])
    missing = await client.post(
        "/internal/plan", headers=CRON, json={"shop": "nope", "plan": "pro"}
    )
    assert missing.status_code == 404


async def test_instagram_is_answered_only_on_the_business_plan(
    replyhub: tuple[Client, Services],
) -> None:
    client, services = replyhub

    async def stored(mid: str) -> bool:
        async with services.db.system() as session:
            found = await session.scalar(select(Message.id).where(Message.external_id == mid))
        return found is not None

    await webhook(client, ig_dm("plan-1", "IGSID7", text="price?"))
    assert not await stored("plan-1")
    await set_plan(client, "business")
    await webhook(client, ig_dm("plan-2", "IGSID7", text="price?"))
    assert await stored("plan-2")


async def test_selling_on_means_every_feature(app: tuple[Client, Services]) -> None:
    """Chatfront (COMMERCE on) has no plans: everything stays on, as before."""
    client, services = app
    owner = await owner_auth(services)
    me = (await client.get("/api/owner/me", headers=owner)).json()
    assert "inbox" in me["features"]
    assert (await client.get("/api/owner/inbox", headers=owner)).status_code == 200

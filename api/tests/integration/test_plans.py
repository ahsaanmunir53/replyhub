"""ReplyHub plans on real PostgreSQL: a business gets the features it pays for, the operator
sets the plan, and Instagram waits for the Business plan."""

from __future__ import annotations

import dataclasses
import uuid
from datetime import date, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select

from chatfront.ai.mock import Fixture
from chatfront.ai.models import AiCall
from chatfront.channels.models import Message
from chatfront.core.models import Tenant
from chatfront.owner.rules import faq_answer
from chatfront.owner.subscription import PAID_UNTIL
from chatfront.services import Services
from chatfront.stock.models import OwnerNotice
from tests.integration.chat import (
    Client,
    agent,
    customer,
    last,
    owner_auth,
    said,
    say,
    settle,
    use,
)
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


async def test_a_new_business_is_on_the_trial(replyhub: tuple[Client, Services]) -> None:
    """The trial shows the assistant, the rules and the inbox (where the trial chat lands)."""
    client, services = replyhub
    owner = await owner_auth(services)
    me = (await client.get("/api/owner/me", headers=owner)).json()
    assert (me["plan"], me["features"]) == ("trial", ["assistant", "inbox", "rules"])
    assert (await client.get("/api/owner/rules", headers=owner)).status_code == 200
    assert (await client.get("/api/owner/inbox", headers=owner)).status_code == 200
    await set_plan(client, "basic")
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


# -- the trial, quick answers, the allowance and the owner's request ----------------------

FAQ = {"faqs": [{"question": "What are your timings?", "answer": "11am to 9pm, every day."}]}


def replying(match: str, **answer: Any) -> Fixture:
    return dataclasses.replace(agent(match, **answer), prompt="reply_agent")


async def real_business(services: Services) -> None:
    """The seeded shop is a demo, which the trial leaves alone; these tests need a real one."""
    async with services.db.system() as session:
        tenant = await session.scalar(select(Tenant).where(Tenant.slug == SHOP))
        assert tenant is not None
        tenant.is_demo = False


async def model_calls(services: Services) -> int:
    async with services.db.system() as session:
        return int(await session.scalar(select(func.count(AiCall.id))) or 0)


async def test_the_trial_answers_one_chat_then_stops(
    replyhub: tuple[Client, Services], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, services = replyhub
    await real_business(services)
    monkeypatch.setattr(services.settings, "trial_replies", 2)
    owner = await owner_auth(services)
    use(
        services,
        replying("price", content="Sure, tell me more."),
        replying("size", content="Sure, tell me more."),
    )
    first, token = await customer(client)
    assert last(await say(client, services, SHOP, first, "price?", token=token))["body"] == (
        "Sure, tell me more."
    )
    other, other_token = await customer(client)  # a second chat: the trial has one
    reply = last(await say(client, services, SHOP, other, "price?", token=other_token))
    assert reply["body"] in said("reply.trial_limit")
    assert last(await say(client, services, SHOP, first, "size?", token=token))["body"] == (
        "Sure, tell me more."
    )
    reply = last(await say(client, services, SHOP, first, "colour?", token=token))
    assert reply["body"] in said("reply.trial_limit")  # two replies used
    view = (await client.get("/api/owner/plan", headers=owner)).json()
    assert (view["plan"], view["used"], view["limit"]) == ("trial", 2, 2)
    assert (view["chats_used"], view["stopped"]) == (1, "trial_over")
    async with services.db.system() as session:
        told = await session.scalar(
            select(func.count(OwnerNotice.id)).where(OwnerNotice.kind == "plan_trial_over")
        )
    assert told == 1  # once, however many messages wait


async def test_the_owners_own_answer_and_thanks_need_no_model(
    replyhub: tuple[Client, Services],
) -> None:
    client, services = replyhub
    owner = await owner_auth(services)
    await client.put("/api/owner/rules", headers=owner, json=FAQ)
    before = await model_calls(services)
    guest, token = await customer(client)
    reply = last(await say(client, services, SHOP, guest, "your timings?", token=token))
    assert reply["body"] == "11am to 9pm, every day."
    reply = last(await say(client, services, SHOP, guest, "Shukriya", token=token))
    assert reply["body"] in said("reply.welcome")
    assert await model_calls(services) == before
    assert faq_answer_of("timings for delivery to Sharjah and Ajman please?") is None


def faq_answer_of(text: str) -> str | None:
    tenant = Tenant(profile=FAQ)
    return faq_answer(tenant, text)


async def test_the_owner_asks_for_a_plan_and_the_operator_sets_it(
    replyhub: tuple[Client, Services], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, services = replyhub
    await real_business(services)
    monkeypatch.setattr(services.settings, "sales_whatsapp", "+971 50 000 1111")
    monkeypatch.setattr(services.settings, "plan_prices", "pro=AED 199 a month")
    owner = await owner_auth(services)
    view = (await client.get("/api/owner/plan", headers=owner)).json()
    assert [o["id"] for o in view["options"]] == ["basic", "pro", "business"]
    assert view["options"][1]["price"] == "AED 199 a month"
    assert view["options"][0]["price"] is None
    bad = await client.post("/api/owner/plan/request", headers=owner, json={"plan": "trial"})
    assert bad.status_code == 400
    asked = await client.post("/api/owner/plan/request", headers=owner, json={"plan": "pro"})
    assert asked.json()["requested"] == "pro"
    assert asked.json()["contact"].startswith("https://wa.me/971500001111?text=")
    todo = (await client.get("/internal/plan-requests", headers=CRON)).json()
    assert [(r["shop"], r["plan"], r["current"]) for r in todo] == [(SHOP, "pro", "trial")]
    assert (await client.get("/internal/plan-requests")).status_code == 403
    done = await client.post(
        "/internal/plan", headers=CRON, json={"shop": SHOP, "plan": "pro", "months": 1}
    )
    until = date.fromisoformat(done.json()["paid_until"]) - timedelta(days=30)
    assert abs((until - date.today()).days) <= 1  # the business's own day
    view = (await client.get("/api/owner/plan", headers=owner)).json()
    assert (view["plan"], view["requested"], view["limit"]) == ("pro", None, 4000)
    assert (await client.get("/internal/plan-requests", headers=CRON)).json() == []


async def test_a_paid_plan_stops_at_its_allowance_and_when_it_lapses(
    replyhub: tuple[Client, Services], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, services = replyhub
    await real_business(services)
    monkeypatch.setattr(services.settings, "plan_replies", "basic=1")
    await set_plan(client, "basic")
    owner = await owner_auth(services)
    use(services, replying("price", content="Sure."))
    guest, token = await customer(client)
    assert last(await say(client, services, SHOP, guest, "price?", token=token))["body"] == "Sure."
    reply = last(await say(client, services, SHOP, guest, "size?", token=token))
    assert reply["body"] in said("reply.trial_limit")
    assert (await client.get("/api/owner/plan", headers=owner)).json()["stopped"] == "allowance"

    monkeypatch.setattr(services.settings, "plan_replies", "basic=100")
    async with services.db.system() as session:
        tenant = await session.scalar(select(Tenant).where(Tenant.slug == SHOP))
        assert tenant is not None
        old = (date.today() - timedelta(days=10)).isoformat()
        tenant.profile = {**(tenant.profile or {}), PAID_UNTIL: old}
    reply = last(await say(client, services, SHOP, guest, "colour?", token=token))
    assert reply["body"] in said("reply.trial_limit")
    assert (await client.get("/api/owner/plan", headers=owner)).json()["stopped"] == "lapsed"


async def test_several_quick_messages_get_one_answer(replyhub: tuple[Client, Services]) -> None:
    client, services = replyhub
    use(services, replying("delivery", content="Sure."))
    guest, token = await customer(client)
    for text in ("hello there", "price?", "and delivery?"):
        post = {"client_id": str(uuid.uuid4()), "text": text, "token": token}
        await client.post(f"/api/shops/{SHOP}/chat/messages", json=post, headers=guest)
    messages = await settle(client, services, SHOP, guest)
    assert [m["body"] for m in messages if m["direction"] == "out"] == ["Sure."]

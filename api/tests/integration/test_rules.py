"""The owner's rules for the assistant (ReplyHub): saved in the console, read back, and given
to the assistant as the business details it answers from."""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from chatfront.ai.mock import Fixture
from chatfront.services import Services
from tests.integration.chat import Client, agent, customer, last, owner_auth, say, use
from tests.integration.conftest import SHOP

RULES: dict[str, Any] = {
    "about": "Lawn and chiffon suits, stitched and unstitched.",
    "hours": "Mon to Sat, 11am to 9pm",
    "address": "Shop 4, Al Karama, Dubai",
    "delivery": "All of Dubai in 2 days",
    "how_to_order": "Order on our website gulmohar.example or visit the shop.",
    "returns": "Exchange within 7 days with the receipt.",
    "policies": "No cash on delivery outside Dubai.",
    "avoid": "Do not promise same-day delivery.",
    "tone": "formal",
    "faqs": [{"question": "Do you stitch?", "answer": "Yes, stitching takes 5 days."}],
}


def replying(match: str, **answer: Any) -> Fixture:
    return dataclasses.replace(agent(match, **answer), prompt="reply_agent")


async def test_the_owner_saves_the_rules_and_reads_them_back(
    app: tuple[Client, Services],
) -> None:
    client, services = app
    owner = await owner_auth(services)
    saved = await client.put("/api/owner/rules", headers=owner, json=RULES)
    assert saved.status_code == 200
    assert saved.json() == RULES
    assert (await client.get("/api/owner/rules", headers=owner)).json() == RULES

    too_many = {**RULES, "faqs": [{"question": "q", "answer": "a"}] * 41}
    assert (await client.put("/api/owner/rules", headers=owner, json=too_many)).status_code == 422
    assert (await client.get("/api/owner/rules")).status_code == 401


async def test_the_assistant_answers_from_the_rules(
    app: tuple[Client, Services], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, services = app
    monkeypatch.setattr(services.settings, "commerce", False)
    owner = await owner_auth(services)
    await client.put("/api/owner/rules", headers=owner, json=RULES)
    mock = use(services, replying("stitch", content="Ji, silai mein 5 din lagte hain."))
    guest, token = await customer(client)
    reply = last(await say(client, services, SHOP, guest, "aap stitch karte ho?", token=token))
    assert reply["body"] == "Ji, silai mein 5 din lagte hain."
    call = next(r for r in mock.requests if r.prompt and r.prompt.startswith("reply_agent"))
    system = call.messages[0].text()
    for line in (
        "Address: Shop 4, Al Karama, Dubai",
        "How to buy: Order on our website gulmohar.example or visit the shop.",
        "Opening hours: Mon to Sat, 11am to 9pm",
        "- Q: Do you stitch? A: Yes, stitching takes 5 days.",
        "Never say or promise: Do not promise same-day delivery.",
        "Tone the owner wants: polite and formal",
    ):
        assert line in system

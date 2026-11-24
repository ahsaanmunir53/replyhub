"""Money Guardian: a courier sheet says paid, the bank proves it, cases open from records,
the customer's answer about a delivery attempt is kept, and profit per order is counted."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from chatfront.core.clock import utcnow
from chatfront.delivery.models import Shipment
from chatfront.guardian.models import CourierCase, ShipmentEvent
from chatfront.services import Services
from tests.integration.chat import Client, owner_auth, say
from tests.integration.test_couriers import dispatched, sheet, upload
from tests.integration.test_delivery import GROCERY, cod_order, latest


async def guardian(client: Client, owner: dict[str, str]) -> dict:  # type: ignore[type-arg]
    found = await client.get("/api/owner/guardian?days=30", headers=owner)
    assert found.status_code == 200, found.text
    return found.json()  # type: ignore[no-any-return]


async def test_courier_money_is_counted_only_when_the_bank_proves_it(
    app: tuple[Client, Services],
) -> None:
    client, services = app
    owner = await owner_auth(services, GROCERY)
    order = await dispatched(client, services, owner, "0300 1112231", "G1001")
    rupees = order.total // 100
    await upload(client, owner, sheet(f"G1001,,Delivered,{rupees},150,{rupees - 150}"))
    board = await guardian(client, owner)
    line = next(c for c in board["cod"] if c["code"] == order.code)
    assert line["state"] == "reported"  # the courier says it paid; nothing proves it yet
    assert board["summary"]["unproven"] == (rupees - 150) * 100
    assert board["payouts"][0]["banked"] is False

    statement = (
        "Date,Description,Debit,Credit\n"
        f"{utcnow().date():%d/%m/%Y},TCS COD payout,,{rupees - 150}\n"
        f"{utcnow().date():%d/%m/%Y},Rent,5000,\n"
    ).encode()
    sent = await client.post(
        "/api/owner/guardian/bank",
        files={"file": ("bank.csv", statement, "text/csv")},
        headers=owner,
    )
    assert sent.status_code == 200, sent.text
    assert sent.json()["credits"] == 1
    assert sent.json()["proved"] == ["tcs.csv"]
    board = await guardian(client, owner)
    line = next(c for c in board["cod"] if c["code"] == order.code)
    assert line["state"] == "banked"
    assert board["summary"]["unproven"] == 0


async def test_cases_open_from_records_and_a_complaint_is_written(
    app: tuple[Client, Services],
) -> None:
    client, services = app
    owner = await owner_auth(services, GROCERY)
    order = await dispatched(client, services, owner, "0300 1112232", "G2001")
    rupees = order.total // 100
    # Delivered, but the courier paid 300 short, and long ago.
    await upload(client, owner, sheet(f"G2001,,Delivered,{rupees},150,{rupees - 450}"))
    async with services.db.system() as session:
        shipment = await session.scalar(select(Shipment).where(Shipment.order_id == order.id))
        assert shipment is not None
        shipment.delivered_at = utcnow() - timedelta(days=20)
        shipment.courier_charge = 10_000  # agreed Rs 100, lower than the sheet's Rs 150
    board = await guardian(client, owner)
    kinds = sorted(c["kind"] for c in board["cases"] if c["order"] == order.code)
    assert kinds == ["cod_missing", "wrong_deduction"]
    missing = next(c for c in board["cases"] if c["kind"] == "cod_missing")
    assert missing["at_stake"] == 35_000  # expected (total - Rs 100) less what was paid
    assert any(a["key"] == "overdue" for a in board["alerts"])
    # Opening again opens nothing new.
    assert (await guardian(client, owner))["summary"]["new_cases"] == 0

    text = (
        await client.get(f"/api/owner/guardian/cases/{missing['id']}/complaint", headers=owner)
    ).json()["text"]
    assert order.code in text
    assert "G2001" in text
    closed = await client.put(
        f"/api/owner/guardian/cases/{missing['id']}",
        json={"status": "resolved", "recovered": "200", "reference": "TCS-55"},
        headers=owner,
    )
    assert closed.json()["status"] == "resolved"
    assert closed.json()["recovered"] == 20_000


async def test_a_failed_attempt_is_checked_with_the_customer(
    app: tuple[Client, Services],
) -> None:
    client, services = app
    owner = await owner_auth(services, GROCERY)
    made = await cod_order(client, services, "cheeni bhej do", "0300 1112233")
    order = await latest(services, status="confirmed")
    for move in ({"to": "packed"}, {"to": "dispatched", "courier": "TCS", "tracking": "G3001"}):
        url = f"/api/owner/orders/{order.code}/status"
        assert (await client.post(url, json=move, headers=owner)).status_code == 200
    asked = await client.post(
        f"/api/owner/guardian/orders/{order.code}/attempt",
        json={"note": "Customer unavailable"},
        headers=owner,
    )
    assert asked.status_code == 200, asked.text
    assert asked.json() == {"asked": True}
    # The customer taps "nobody came".
    await say(
        client,
        services,
        GROCERY,
        made["guest"],
        token=made["token"],
        text="Nahi",
        button_id=f"guard:no:{order.code}",
    )
    async with services.db.system() as session:
        kinds = list(
            await session.scalars(
                select(ShipmentEvent.kind).where(ShipmentEvent.order_id == order.id)
            )
        )
        case = await session.scalar(select(CourierCase).where(CourierCase.order_id == order.id))
    assert kinds == ["attempt_failed", "customer_denied"]
    assert case is not None
    assert case.kind == "false_attempt"


async def test_profit_per_order_uses_the_owners_costs(app: tuple[Client, Services]) -> None:
    client, services = app
    owner = await owner_auth(services, GROCERY)
    order = await dispatched(client, services, owner, "0300 1112234", "G4001")
    rupees = order.total // 100
    await upload(client, owner, sheet(f"G4001,,Delivered,{rupees},150,{rupees - 150}"))
    saved = await client.put(
        "/api/owner/guardian/settings",
        json={"packaging": "30", "overdue_days": 7},
        headers=owner,
    )
    assert saved.json()["packaging"] == 3_000
    await client.put(
        f"/api/owner/guardian/orders/{order.code}/costs", json={"ads": "100"}, headers=owner
    )
    board = await guardian(client, owner)
    line = next(p for p in board["profits"] if p["code"] == order.code)
    assert (line["revenue"], line["courier"], line["packaging"], line["ads"]) == (
        order.total,
        15_000,
        3_000,
        10_000,
    )

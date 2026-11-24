"""Bank statements: each credit kept once, and matched to a courier payout of the same amount.

A courier sheet says what it paid; a bank credit of exactly that amount, from the day of the
sheet to three weeks after (or up to three days before), proves the money arrived. One
receipt proves one payout, and a payout is never proved twice. Amounts must agree to the
last paisa: a near match is shown to the owner, not taken as proof.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from chatfront.core.errors import AppError
from chatfront.core.numbers import find_numbers
from chatfront.guardian.models import BankReceipt, CourierPayout
from chatfront.stock.sheets import read_rows

BEFORE = timedelta(days=3)
AFTER = timedelta(days=21)
HEADERS: dict[str, tuple[str, ...]] = {
    "date": ("date", "value date", "transaction date", "posting date", "txn date"),
    "credit": ("credit", "deposit", "deposits", "credit amount", "cr", "amount in"),
    "amount": ("amount", "transaction amount"),
    "reference": ("description", "narration", "details", "reference", "particulars", "remarks"),
}
DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d %b %Y", "%d-%b-%Y", "%m/%d/%Y")


@dataclass(frozen=True, slots=True)
class Credit:
    on: date
    amount: int
    reference: str


@dataclass
class BankReport:
    rows: int = 0
    credits: int = 0
    new: int = 0
    proved: list[str] = field(default_factory=list)  # payout names now proved by the bank


def _column(headers: list[str], name: str) -> int | None:
    lowered = [" ".join(h.lower().replace("_", " ").split()) for h in headers]
    for word in HEADERS[name]:
        if word in lowered:
            return lowered.index(word)
    for index, header in enumerate(lowered):
        if any(re.search(rf"\b{re.escape(word)}\b", header) for word in HEADERS[name]):
            return index
    return None


def _date(text: str) -> date | None:
    cleaned = text.strip().split(" ")[0] if ":" in text else text.strip()
    for form in DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, form).date()
        except ValueError:
            continue
    return None


def read(data: bytes, digits: int) -> tuple[int, list[Credit]]:
    """The sheet's credits (money in). Debits and rows without a date are left out."""
    table = read_rows(data)
    if len(table) < 2:
        raise AppError("empty_sheet", "The sheet has no rows")
    headers = table[0]
    where = {name: _column(headers, name) for name in HEADERS}
    if where["date"] is None or (where["credit"] is None and where["amount"] is None):
        raise AppError("no_bank_columns", "A date column and a credit or amount column are needed")

    def cell(row: list[str], name: str) -> str:
        index = where[name]
        return row[index].strip() if index is not None and index < len(row) else ""

    credits = []
    rows = [row for row in table[1:] if any(part.strip() for part in row)]
    for row in rows:
        on = _date(cell(row, "date"))
        text = cell(row, "credit") if where["credit"] is not None else cell(row, "amount")
        found = find_numbers(text.replace(",", ""))
        if on is None or not found or text.strip().startswith("-") or found[0] <= 0:
            continue
        credits.append(Credit(on, round(found[0] * 10**digits), cell(row, "reference")[:200]))
    return len(rows), credits


def _key(credit: Credit) -> str:
    text = f"{credit.on.isoformat()}|{credit.amount}|{credit.reference}"
    return hashlib.sha256(text.encode()).hexdigest()[:32]


async def keep(session: AsyncSession, tenant_id: object, credits: list[Credit]) -> BankReport:
    """Keep the new credits, then match every unproved payout to an unused receipt."""
    report = BankReport(credits=len(credits))
    for credit in credits:
        key = _key(credit)
        if await session.scalar(select(BankReceipt.id).where(BankReceipt.row_key == key)):
            continue
        session.add(
            BankReceipt(
                tenant_id=tenant_id,
                row_key=key,
                received_on=credit.on,
                amount=credit.amount,
                reference=credit.reference,
            )
        )
        report.new += 1
    await session.flush()
    report.proved = await match(session)
    return report


async def match(session: AsyncSession) -> list[str]:
    used = set(
        await session.scalars(
            select(CourierPayout.bank_receipt_id).where(CourierPayout.bank_receipt_id.is_not(None))
        )
    )
    receipts = [r for r in await session.scalars(select(BankReceipt)) if r.id not in used]
    proved = []
    payouts = await session.scalars(
        select(CourierPayout)
        .where(CourierPayout.bank_receipt_id.is_(None), CourierPayout.paid_out > 0)
        .order_by(CourierPayout.created_at)
    )
    for payout in payouts:
        day = payout.created_at.date()
        found = next(
            (
                r
                for r in sorted(receipts, key=lambda r: abs((r.received_on - day).days))
                if r.amount == payout.paid_out and day - BEFORE <= r.received_on <= day + AFTER
            ),
            None,
        )
        if found is not None:
            payout.bank_receipt_id = found.id
            receipts.remove(found)
            proved.append(payout.name or payout.courier)
    await session.flush()
    return proved

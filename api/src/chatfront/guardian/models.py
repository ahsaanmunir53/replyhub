"""Money Guardian records: courier payouts and the bank receipts that prove them, every
shipment event as it happened, and cases opened against a courier.

Amounts are minor units and come only from sheets, the owner or code, never from a model.
Events are never changed once written: a courier changing its mind adds a new one."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from chatfront.core.db import Base, created_at_column, id_column


class CourierPayout(Base):
    """One courier sheet uploaded: what the courier says it paid over, all rows together."""

    __tablename__ = "courier_payouts"

    id: Mapped[uuid.UUID] = id_column()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    courier: Mapped[str] = mapped_column(String(60), default="")
    name: Mapped[str] = mapped_column(String(120), default="")  # the file's name
    rows: Mapped[int] = mapped_column(default=0)
    paid_out: Mapped[int] = mapped_column(BigInteger, default=0)
    bank_receipt_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("bank_receipts.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = created_at_column()


class BankReceipt(Base):
    """A credit in the shop's bank statement. It proves a payout when the amounts agree."""

    __tablename__ = "bank_receipts"
    __table_args__ = (UniqueConstraint("tenant_id", "row_key"),)

    id: Mapped[uuid.UUID] = id_column()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    row_key: Mapped[str] = mapped_column(String(64))
    received_on: Mapped[date]
    amount: Mapped[int] = mapped_column(BigInteger)
    reference: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = created_at_column()


class EventKind(StrEnum):
    ATTEMPT_FAILED = "attempt_failed"  # the courier says it tried and could not deliver
    CUSTOMER_CONFIRMED = "customer_confirmed"  # the customer says a rider did call or come
    CUSTOMER_DENIED = "customer_denied"  # the customer says nobody called or came
    NOTE = "note"


class ShipmentEvent(Base):
    """One thing that happened to a parcel, as reported, with who reported it."""

    __tablename__ = "shipment_events"

    id: Mapped[uuid.UUID] = id_column()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(24))
    source: Mapped[str] = mapped_column(String(20))  # courier, customer, staff
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = created_at_column()


class CaseKind(StrEnum):
    FALSE_ATTEMPT = "false_attempt"
    UNJUSTIFIED_RTO = "unjustified_rto"
    COD_MISSING = "cod_missing"
    WRONG_DEDUCTION = "wrong_deduction"
    LOST = "lost"
    DAMAGED = "damaged"


class CaseStatus(StrEnum):
    OPEN = "open"
    SENT = "sent"  # the complaint went to the courier
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    REJECTED = "rejected"


class CourierCase(Base):
    """A dispute with a courier about one parcel, with its evidence and how it ended."""

    __tablename__ = "courier_cases"

    id: Mapped[uuid.UUID] = id_column()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(14), default=CaseStatus.OPEN)
    opened_by: Mapped[str] = mapped_column(String(10))  # code or staff
    courier: Mapped[str] = mapped_column(String(60), default="")
    at_stake: Mapped[int] = mapped_column(BigInteger, default=0)  # what the shop stands to lose
    recovered: Mapped[int] = mapped_column(BigInteger, default=0)
    reference: Mapped[str] = mapped_column(String(80), default="")  # the courier's ticket
    assigned_staff_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("staff.id", ondelete="SET NULL")
    )
    timeline: Mapped[list[Any]] = mapped_column(default=list)  # [{at, by, text}]
    created_at: Mapped[datetime] = created_at_column()
    closed_at: Mapped[datetime | None]

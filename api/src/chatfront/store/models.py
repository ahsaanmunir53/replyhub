"""A business's website store and the orders read from it."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from chatfront.core.db import Base, created_at_column, id_column


class StoreConnection(Base):
    """One per business: where its store is and the read-only key, sealed with SECRET_KEY.
    The key never leaves the server again; the console only learns that one is set."""

    __tablename__ = "store_connections"

    id: Mapped[uuid.UUID] = id_column()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), unique=True
    )
    platform: Mapped[str] = mapped_column(String(20))  # shopify | woocommerce
    store_url: Mapped[str] = mapped_column(String(200))
    key_sealed: Mapped[str] = mapped_column(Text)
    secret_sealed: Mapped[str | None] = mapped_column(Text)  # WooCommerce's consumer secret
    report_hour: Mapped[int] = mapped_column(Integer, default=21)  # the business's local hour
    synced_at: Mapped[datetime | None]
    last_error: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = created_at_column()


class StoreOrder(Base):
    """An order as the store has it. Amounts in minor units; no customer details are kept."""

    __tablename__ = "store_orders"
    __table_args__ = (
        UniqueConstraint("tenant_id", "external_id"),
        Index("ix_store_orders_tenant_placed", "tenant_id", "placed_at"),
    )

    id: Mapped[uuid.UUID] = id_column()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    external_id: Mapped[str] = mapped_column(String(40))
    number: Mapped[str] = mapped_column(String(40))
    placed_at: Mapped[datetime]
    total: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(20))  # pending | paid | cancelled | refunded
    cod: Mapped[bool] = mapped_column(default=False)
    fulfilled: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = created_at_column()

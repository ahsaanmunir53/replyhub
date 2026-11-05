"""ReplyHub: the business's website store and the orders read from it.

Revision ID: 0031
Revises: 0030
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from chatfront.core.rls import secure, unsecure

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _created_at() -> sa.Column[sa.DateTime]:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "store_connections",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("platform", sa.String(length=20), nullable=False),
        sa.Column("store_url", sa.String(length=200), nullable=False),
        sa.Column("key_sealed", sa.Text(), nullable=False),
        sa.Column("secret_sealed", sa.Text(), nullable=True),
        sa.Column("report_hour", sa.Integer(), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=300), nullable=True),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_store_connections_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_store_connections")),
        sa.UniqueConstraint("tenant_id", name=op.f("uq_store_connections_tenant_id")),
    )
    secure("store_connections")
    op.create_table(
        "store_orders",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(length=40), nullable=False),
        sa.Column("number", sa.String(length=40), nullable=False),
        sa.Column("placed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("cod", sa.Boolean(), nullable=False),
        sa.Column("fulfilled", sa.Boolean(), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_store_orders_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_store_orders")),
        sa.UniqueConstraint(
            "tenant_id", "external_id", name=op.f("uq_store_orders_tenant_id_external_id")
        ),
    )
    op.create_index("ix_store_orders_tenant_placed", "store_orders", ["tenant_id", "placed_at"])
    secure("store_orders")


def downgrade() -> None:
    unsecure("store_orders")
    op.drop_index("ix_store_orders_tenant_placed", table_name="store_orders")
    op.drop_table("store_orders")
    unsecure("store_connections")
    op.drop_table("store_connections")

"""ReplyHub Money Guardian: courier payouts proved by bank receipts, shipment events, courier
cases, a product's unit cost, an order's extra costs and a return's inspection.

Revision ID: 0034
Revises: 0033
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from chatfront.core.rls import secure, unsecure

revision: str = "0034"
down_revision: str | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW = ("bank_receipts", "courier_payouts", "shipment_events", "courier_cases")


def _base(name: str, *columns: sa.Column) -> None:  # type: ignore[type-arg]
    op.create_table(
        name,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        *columns,
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f(f"fk_{name}_tenant_id_tenants"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{name}")),
    )
    op.create_index(op.f(f"ix_{name}_tenant_id"), name, ["tenant_id"])


def upgrade() -> None:
    _base(
        "bank_receipts",
        sa.Column("row_key", sa.String(64), nullable=False),
        sa.Column("received_on", sa.Date(), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("reference", sa.String(200), nullable=False),
    )
    op.create_unique_constraint(
        op.f("uq_bank_receipts_tenant_id_row_key"), "bank_receipts", ["tenant_id", "row_key"]
    )
    _base(
        "courier_payouts",
        sa.Column("courier", sa.String(60), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("rows", sa.Integer(), nullable=False),
        sa.Column("paid_out", sa.BigInteger(), nullable=False),
        sa.Column(
            "bank_receipt_id",
            sa.UUID(),
            sa.ForeignKey("bank_receipts.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    _base(
        "shipment_events",
        sa.Column(
            "order_id", sa.UUID(), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
    )
    op.create_index(op.f("ix_shipment_events_order_id"), "shipment_events", ["order_id"])
    _base(
        "courier_cases",
        sa.Column(
            "order_id", sa.UUID(), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("status", sa.String(14), nullable=False),
        sa.Column("opened_by", sa.String(10), nullable=False),
        sa.Column("courier", sa.String(60), nullable=False),
        sa.Column("at_stake", sa.BigInteger(), nullable=False),
        sa.Column("recovered", sa.BigInteger(), nullable=False),
        sa.Column("reference", sa.String(80), nullable=False),
        sa.Column(
            "assigned_staff_id",
            sa.UUID(),
            sa.ForeignKey("staff.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("timeline", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(op.f("ix_courier_cases_order_id"), "courier_cases", ["order_id"])
    for table in NEW:
        secure(table)
    op.add_column("products", sa.Column("unit_cost", sa.BigInteger(), nullable=True))
    op.add_column(
        "orders", sa.Column("costs", postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )
    op.add_column("cod_settlements", sa.Column("payout_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_cod_settlements_payout_id_courier_payouts"),
        "cod_settlements",
        "courier_payouts",
        ["payout_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(op.f("ix_cod_settlements_payout_id"), "cod_settlements", ["payout_id"])
    op.add_column("return_requests", sa.Column("inspection", sa.String(10), nullable=True))
    op.add_column("return_requests", sa.Column("loss", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("return_requests", "loss")
    op.drop_column("return_requests", "inspection")
    op.drop_index(op.f("ix_cod_settlements_payout_id"), table_name="cod_settlements")
    op.drop_constraint(
        op.f("fk_cod_settlements_payout_id_courier_payouts"), "cod_settlements", "foreignkey"
    )
    op.drop_column("cod_settlements", "payout_id")
    op.drop_column("orders", "costs")
    op.drop_column("products", "unit_cost")
    for table in reversed(NEW):
        unsecure(table)
        op.drop_table(table)

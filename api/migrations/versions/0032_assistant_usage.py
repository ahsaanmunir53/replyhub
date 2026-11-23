"""ReplyHub: the assistant's replies counted per business, for the trial and each month.

Revision ID: 0032
Revises: 0031
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from chatfront.core.rls import secure, unsecure

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "assistant_usage",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("period", sa.String(length=7), nullable=False),
        sa.Column("replies", sa.Integer(), nullable=False),
        sa.Column("model_replies", sa.Integer(), nullable=False),
        sa.Column("chats", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("warned", sa.Boolean(), nullable=False),
        sa.Column("stopped", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_assistant_usage_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assistant_usage")),
        sa.UniqueConstraint(
            "tenant_id", "period", name=op.f("uq_assistant_usage_tenant_id_period")
        ),
    )
    secure("assistant_usage")


def downgrade() -> None:
    unsecure("assistant_usage")
    op.drop_table("assistant_usage")

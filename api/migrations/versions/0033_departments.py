"""ReplyHub: departments. A chat goes to the department whose words it uses, and a chat
handed to a person goes to a member of that department.

Revision ID: 0033
Revises: 0032
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from chatfront.core.rls import secure, unsecure

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "departments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("keywords", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_departments_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_departments")),
    )
    op.create_index(op.f("ix_departments_tenant_id"), "departments", ["tenant_id"])
    secure("departments")
    for table in ("staff", "conversations"):
        op.add_column(table, sa.Column("department_id", sa.UUID(), nullable=True))
        op.create_foreign_key(
            op.f(f"fk_{table}_department_id_departments"),
            table,
            "departments",
            ["department_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    for table in ("staff", "conversations"):
        op.drop_constraint(op.f(f"fk_{table}_department_id_departments"), table, "foreignkey")
        op.drop_column(table, "department_id")
    unsecure("departments")
    op.drop_index(op.f("ix_departments_tenant_id"), table_name="departments")
    op.drop_table("departments")

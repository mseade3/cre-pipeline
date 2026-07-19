"""Add auditable human outreach approval fields.

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-19
"""

from sqlalchemy import Column, DateTime, String, inspect

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("contacts")}
    additions = []
    if "outreach_approved_by" not in columns:
        additions.append(Column("outreach_approved_by", String(120), nullable=True))
    if "outreach_approved_at" not in columns:
        additions.append(Column("outreach_approved_at", DateTime(timezone=True), nullable=True))
    if additions:
        with op.batch_alter_table("contacts") as batch:
            for column in additions:
                batch.add_column(column)
    activity_columns = {column["name"] for column in inspector.get_columns("activities")}
    if "outcome_code" not in activity_columns:
        with op.batch_alter_table("activities") as batch:
            batch.add_column(Column("outcome_code", String(40), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    activity_columns = {column["name"] for column in inspector.get_columns("activities")}
    if "outcome_code" in activity_columns:
        with op.batch_alter_table("activities") as batch:
            batch.drop_column("outcome_code")
    columns = {column["name"] for column in inspector.get_columns("contacts")}
    with op.batch_alter_table("contacts") as batch:
        if "outreach_approved_at" in columns:
            batch.drop_column("outreach_approved_at")
        if "outreach_approved_by" in columns:
            batch.drop_column("outreach_approved_by")

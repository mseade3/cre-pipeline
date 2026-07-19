"""Link ownership records to manually verified entities.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-19
"""

from sqlalchemy import Column, Integer, inspect

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("ownerships")}
    if "entity_id" not in columns:
        with op.batch_alter_table("ownerships") as batch:
            batch.add_column(Column("entity_id", Integer(), nullable=True))
            batch.create_foreign_key(
                "fk_ownerships_entity_id_entities", "entities", ["entity_id"], ["id"]
            )
            batch.create_index("ix_ownerships_entity_id", ["entity_id"])


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("ownerships")}
    if "entity_id" in columns:
        with op.batch_alter_table("ownerships") as batch:
            batch.drop_index("ix_ownerships_entity_id")
            batch.drop_constraint("fk_ownerships_entity_id_entities", type_="foreignkey")
            batch.drop_column("entity_id")

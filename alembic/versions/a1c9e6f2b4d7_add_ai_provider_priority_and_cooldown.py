"""add ai provider priority, label, and rate-limit cooldown

Revision ID: a1c9e6f2b4d7
Revises: b3c2d1e0f9a8
"""
from alembic import op
import sqlalchemy as sa

revision = "a1c9e6f2b4d7"
down_revision = "b3c2d1e0f9a8"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("ai_settings") as batch:
        batch.add_column(sa.Column("label", sa.String(100), nullable=True))
        batch.add_column(sa.Column("priority", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("rate_limited_until", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    with op.batch_alter_table("ai_settings") as batch:
        batch.drop_column("rate_limited_until")
        batch.drop_column("priority")
        batch.drop_column("label")

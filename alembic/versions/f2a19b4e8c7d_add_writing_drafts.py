"""add writing drafts

Revision ID: f2a19b4e8c7d
Revises: 06de31cc5f8d
Create Date: 2026-08-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f2a19b4e8c7d"
down_revision: Union[str, Sequence[str], None] = "06de31cc5f8d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "writing_drafts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=True),
        sa.Column("base_version_id", sa.Integer(), nullable=True),
        sa.Column("context_key", sa.String(length=64), nullable=False),
        sa.Column("type", sa.Enum("essay", "book_chapter", name="documenttype"), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("book_title", sa.String(length=255), nullable=True),
        sa.Column("author", sa.String(length=255), nullable=True),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("target_word_count", sa.Integer(), nullable=True),
        sa.Column("ignored_correction_ids_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["base_version_id"], ["document_versions.id"]),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "context_key", name="uq_writing_drafts_user_context"),
    )
    op.create_index(op.f("ix_writing_drafts_user_id"), "writing_drafts", ["user_id"], unique=False)
    op.create_index(op.f("ix_writing_drafts_document_id"), "writing_drafts", ["document_id"], unique=False)
    op.create_index(op.f("ix_writing_drafts_base_version_id"), "writing_drafts", ["base_version_id"], unique=False)
    op.create_index(op.f("ix_writing_drafts_updated_at"), "writing_drafts", ["updated_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_writing_drafts_updated_at"), table_name="writing_drafts")
    op.drop_index(op.f("ix_writing_drafts_base_version_id"), table_name="writing_drafts")
    op.drop_index(op.f("ix_writing_drafts_document_id"), table_name="writing_drafts")
    op.drop_index(op.f("ix_writing_drafts_user_id"), table_name="writing_drafts")
    op.drop_table("writing_drafts")

"""add learning records

Revision ID: b3c2d1e0f9a8
Revises: f2a19b4e8c7d
"""
from alembic import op
import sqlalchemy as sa

revision = "b3c2d1e0f9a8"
down_revision = "f2a19b4e8c7d"
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table("vocab_words") as batch:
        batch.add_column(sa.Column("source_version_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("notes", sa.Text(), nullable=True))
        batch.add_column(sa.Column("last_reviewed_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_foreign_key("fk_vocab_words_source_version", "document_versions", ["source_version_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_vocab_words_source_version_id", "vocab_words", ["source_version_id"])
    op.create_index("uq_vocab_words_user_lower_word", "vocab_words", ["user_id", sa.text("lower(word)")], unique=True)
    op.create_table("weekly_writing_goals", sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), primary_key=True), sa.Column("target_submissions", sa.Integer(), nullable=False), sa.Column("timezone", sa.String(64), nullable=False), sa.Column("enabled", sa.Boolean(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("writing_activities", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False), sa.Column("version_id", sa.Integer(), sa.ForeignKey("document_versions.id"), nullable=False, unique=True), sa.Column("completed_at_utc", sa.DateTime(timezone=True), nullable=False), sa.Column("local_activity_date", sa.Date(), nullable=False), sa.Column("timezone_at_creation", sa.String(64), nullable=False))
    op.create_index("ix_writing_activities_user_id", "writing_activities", ["user_id"])
    op.create_index("ix_writing_activities_completed_at_utc", "writing_activities", ["completed_at_utc"])
    op.create_index("ix_writing_activities_local_activity_date", "writing_activities", ["local_activity_date"])
    op.create_table("practice_exercises", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False), sa.Column("idempotency_key", sa.String(64), nullable=False), sa.Column("template_version", sa.String(32), nullable=False), sa.Column("source_categories_json", sa.Text(), nullable=False), sa.Column("input_summary", sa.String(1000), nullable=False), sa.Column("prompt", sa.Text(), nullable=False), sa.Column("answer", sa.Text(), nullable=False), sa.Column("explanation", sa.Text(), nullable=False), sa.Column("ai_generated", sa.Boolean(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint("user_id", "idempotency_key", name="uq_practice_exercises_user_idempotency"))
    op.create_index("ix_practice_exercises_user_id", "practice_exercises", ["user_id"])
    op.create_index("ix_practice_exercises_created_at", "practice_exercises", ["created_at"])
    op.create_table("practice_completions", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("exercise_id", sa.Integer(), sa.ForeignKey("practice_exercises.id"), nullable=False), sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False), sa.Column("response", sa.String(2000), nullable=False), sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint("exercise_id", "user_id", name="uq_practice_completion_user_exercise"))
    op.create_index("ix_practice_completions_exercise_id", "practice_completions", ["exercise_id"])
    op.create_index("ix_practice_completions_user_id", "practice_completions", ["user_id"])

def downgrade():
    op.drop_table("practice_completions"); op.drop_table("practice_exercises"); op.drop_table("writing_activities"); op.drop_table("weekly_writing_goals")
    op.drop_index("uq_vocab_words_user_lower_word", table_name="vocab_words"); op.drop_index("ix_vocab_words_source_version_id", table_name="vocab_words")
    with op.batch_alter_table("vocab_words") as batch:
        batch.drop_constraint("fk_vocab_words_source_version", type_="foreignkey")
        batch.drop_column("last_reviewed_at"); batch.drop_column("notes"); batch.drop_column("source_version_id")

"""fix token hash column drift

Revision ID: c3f87b64012a
Revises: d74d3075709b
Create Date: 2026-07-29 14:53:55.256586

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3f87b64012a'
down_revision: Union[str, Sequence[str], None] = 'd74d3075709b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for table in ("email_verification_tokens", "password_reset_tokens"):
        columns = {col["name"] for col in inspector.get_columns(table)}
        if "token_hash" in columns:
            continue  # already correct - created this way by d74d3075709b as committed

        # Schema drift: this database ran the "add email verification and
        # password reset" migration while it still had a plain `token`
        # column, before that migration file was edited (pre-commit) to
        # store token_hash instead. The revision stamp still reads
        # d74d3075709b either way, so `alembic upgrade head` alone can never
        # detect or repair this - the actual DDL never matched what the
        # migration file says it produces. A raw token value can't be turned
        # into a hash of itself after the fact in any way a future lookup
        # could use, so pending tokens are simply invalidated: anyone
        # holding a verification/reset link has to request a new one.
        op.execute(f"DELETE FROM {table}")

        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_index(f"ix_{table}_token")
            batch_op.drop_column("token")
            batch_op.add_column(sa.Column("token_hash", sa.String(length=64), nullable=False))
            batch_op.create_index(f"ix_{table}_token_hash", ["token_hash"], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    raise NotImplementedError(
        "irreversible: upgrade() invalidates existing tokens and a raw value can't be recovered from its hash"
    )

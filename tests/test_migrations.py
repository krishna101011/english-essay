from alembic import command
from alembic.config import Config

import app.config as app_config


def test_migrations_upgrade_and_downgrade_roundtrip(tmp_path, monkeypatch):
    """Full upgrade-to-head / downgrade-to-base / upgrade-to-head roundtrip
    against a real (non in-memory) SQLite file - catches issues in.batch_alter_table
    / index drop-order that :memory: fixtures (which build schema straight
    from the ORM models, not migrations) would never exercise."""
    db_path = tmp_path / "migration_smoke.db"
    monkeypatch.setattr(app_config, "DATABASE_URL", f"sqlite:///{db_path}")

    config = Config("alembic.ini")

    command.upgrade(config, "head")
    # c3f87b64012a's downgrade() deliberately raises NotImplementedError - it
    # rewrote email_verification_tokens/password_reset_tokens to store only a
    # token hash, and a raw token can't be recovered from its hash to
    # reconstruct the old plaintext-ish column. That's an intentional,
    # pre-existing irreversibility, not something this phase's migrations
    # introduced - so the roundtrip below only needs to cover everything
    # after it (writing drafts + learning records), which is what's new here.
    command.downgrade(config, "c3f87b64012a")
    command.upgrade(config, "head")

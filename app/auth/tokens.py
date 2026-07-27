import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.db.models import EmailVerificationToken, PasswordResetToken

EMAIL_VERIFICATION_TTL = timedelta(hours=24)
PASSWORD_RESET_TTL = timedelta(hours=1)


def _generate_token() -> str:
    return secrets.token_urlsafe(32)


def _hash_token(token_value: str) -> str:
    # Tokens are bearer credentials (anyone with the raw value can verify an
    # email or reset a password), so only the hash is persisted - the same
    # reasoning as not storing passwords in plaintext. Unlike passwords,
    # these are high-entropy and single-use, so a fast hash (no per-token
    # salt) is fine: it's not protecting against offline guessing, just
    # against a DB read/leak handing out usable tokens directly.
    return hashlib.sha256(token_value.encode()).hexdigest()


def _as_aware_utc(value: datetime) -> datetime:
    # SQLite round-trips DateTime(timezone=True) values as naive strings, so
    # a value just read back from the DB loses its tzinfo even though it was
    # written as UTC. Re-attach it before comparing against an aware "now".
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def create_email_verification_token(db: Session, user_id: int) -> EmailVerificationToken:
    raw_token = _generate_token()
    token = EmailVerificationToken(
        user_id=user_id,
        token_hash=_hash_token(raw_token),
        expires_at=datetime.now(timezone.utc) + EMAIL_VERIFICATION_TTL,
    )
    db.add(token)
    db.flush()
    # Not a mapped column - the raw value only ever needs to exist for the
    # caller to put it in the email link, never persisted.
    token.token = raw_token
    return token


def consume_email_verification_token(db: Session, token_value: str) -> EmailVerificationToken | None:
    token = (
        db.query(EmailVerificationToken)
        .filter(EmailVerificationToken.token_hash == _hash_token(token_value))
        .first()
    )
    if token is None or token.used_at is not None:
        return None
    if _as_aware_utc(token.expires_at) < datetime.now(timezone.utc):
        return None
    token.used_at = datetime.now(timezone.utc)
    return token


def create_password_reset_token(db: Session, user_id: int) -> PasswordResetToken:
    raw_token = _generate_token()
    token = PasswordResetToken(
        user_id=user_id,
        token_hash=_hash_token(raw_token),
        expires_at=datetime.now(timezone.utc) + PASSWORD_RESET_TTL,
    )
    db.add(token)
    db.flush()
    token.token = raw_token
    return token


def consume_password_reset_token(db: Session, token_value: str) -> PasswordResetToken | None:
    token = (
        db.query(PasswordResetToken).filter(PasswordResetToken.token_hash == _hash_token(token_value)).first()
    )
    if token is None or token.used_at is not None:
        return None
    if _as_aware_utc(token.expires_at) < datetime.now(timezone.utc):
        return None
    token.used_at = datetime.now(timezone.utc)
    return token

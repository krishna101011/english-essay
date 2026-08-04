import os
from pathlib import Path

from cryptography.fernet import Fernet

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv(BASE_DIR / ".env")

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./app.db")
SESSION_SECRET_KEY = os.environ.get("SESSION_SECRET_KEY", "change-me")
ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY")


def is_production(app_env: str) -> bool:
    return app_env.strip().lower() == "production"


APP_ENV = os.environ.get("APP_ENV", "development")
IS_PRODUCTION = is_production(APP_ENV)

# Production limits intentionally live in configuration so operators can tune
# them without changing code. The hard caps below remain enforced in routes.
AI_TIMEOUT_SECONDS = int(os.environ.get("AI_TIMEOUT_SECONDS", "30"))
LANGUAGE_TOOL_TIMEOUT_SECONDS = int(os.environ.get("LANGUAGE_TOOL_TIMEOUT_SECONDS", "15"))
RATE_LIMIT_STORAGE_URI = os.environ.get("RATE_LIMIT_STORAGE_URI", "memory://")
ALLOW_CUSTOM_AI_ENDPOINTS = os.environ.get("ALLOW_CUSTOM_AI_ENDPOINTS", "false").strip().lower() == "true"


def validate_production_config() -> None:
    """Fail closed instead of silently deploying insecure defaults."""
    if not IS_PRODUCTION:
        return

    if SESSION_SECRET_KEY in {"", "change-me", "test-secret"} or len(SESSION_SECRET_KEY) < 32:
        raise RuntimeError("SESSION_SECRET_KEY must be a unique value of at least 32 characters in production.")
    if not ENCRYPTION_KEY:
        raise RuntimeError("ENCRYPTION_KEY must be set to a valid Fernet key in production.")
    try:
        Fernet(ENCRYPTION_KEY.encode())
    except Exception as exc:  # pragma: no cover - exact cryptography errors are implementation details
        raise RuntimeError("ENCRYPTION_KEY must be a valid Fernet key in production.") from exc
    if not RATE_LIMIT_STORAGE_URI.startswith(("redis://", "rediss://")):
        raise RuntimeError("RATE_LIMIT_STORAGE_URI must use Redis in production (redis:// or rediss://).")
    if AI_TIMEOUT_SECONDS <= 0 or LANGUAGE_TOOL_TIMEOUT_SECONDS <= 0:
        raise RuntimeError("AI_TIMEOUT_SECONDS and LANGUAGE_TOOL_TIMEOUT_SECONDS must be positive in production.")


validate_production_config()

# Left unset in dev/tests on purpose: get_email_sender() falls back to
# ConsoleEmailSender (logs instead of sending) whenever SMTP_HOST is empty.
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
FROM_EMAIL = os.environ.get("FROM_EMAIL", "noreply@example.com")

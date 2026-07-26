import os
from pathlib import Path

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

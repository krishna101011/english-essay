import importlib

from app import config as config_module


def _reload_app_with_env(monkeypatch, app_env):
    monkeypatch.setenv("APP_ENV", app_env)
    monkeypatch.setenv("SESSION_SECRET_KEY", "a" * 48)
    monkeypatch.setenv("RATE_LIMIT_STORAGE_URI", "redis://localhost:6379/0")
    importlib.reload(config_module)
    from app import main as main_module

    return importlib.reload(main_module)


def test_production_disables_docs_and_forces_https_only_cookies(monkeypatch):
    main_module = _reload_app_with_env(monkeypatch, "production")

    assert main_module.app.docs_url is None
    assert main_module.app.redoc_url is None
    assert main_module.app.openapi_url is None

    session_middleware = next(m for m in main_module.app.user_middleware if m.cls.__name__ == "SessionMiddleware")
    assert session_middleware.kwargs["https_only"] is True


def test_development_keeps_docs_and_allows_http_cookies(monkeypatch):
    main_module = _reload_app_with_env(monkeypatch, "development")

    assert main_module.app.docs_url == "/docs"
    assert main_module.app.redoc_url == "/redoc"

    session_middleware = next(m for m in main_module.app.user_middleware if m.cls.__name__ == "SessionMiddleware")
    assert session_middleware.kwargs["https_only"] is False


def test_production_rejects_default_session_secret(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SESSION_SECRET_KEY", "change-me")
    monkeypatch.setenv("RATE_LIMIT_STORAGE_URI", "redis://localhost:6379/0")

    with __import__("pytest").raises(RuntimeError, match="SESSION_SECRET_KEY"):
        importlib.reload(config_module)

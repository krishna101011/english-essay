import importlib

from app import config as config_module


def _reload_app_with_env(monkeypatch, app_env):
    monkeypatch.setenv("APP_ENV", app_env)
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

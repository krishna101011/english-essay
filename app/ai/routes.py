from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.ai.crypto import decrypt_api_key, encrypt_api_key, mask_api_key
from app.ai.provider import OpenAICompatibleProvider
from app.ai.registry import PROVIDER_REGISTRY
from app.auth.csrf import verify_csrf
from app.auth.dependencies import get_current_user
from app.db.models import AISettings, User
from app.db.session import get_db

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _require_user(user: User | None) -> User | RedirectResponse:
    if user is None:
        return RedirectResponse("/login", status_code=303)
    return user


@router.get("/settings")
def settings_page(
    request: Request,
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user is None:
        return RedirectResponse("/login", status_code=303)

    settings = db.query(AISettings).filter(AISettings.user_id == user.id).first()
    masked_key = None
    if settings:
        try:
            masked_key = mask_api_key(decrypt_api_key(settings.encrypted_api_key))
        except Exception:  # noqa: BLE001 - decryption failure shouldn't break the page
            masked_key = "(unreadable)"

    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "settings": settings,
            "masked_key": masked_key,
            "providers": PROVIDER_REGISTRY,
            "message": None,
            "error": None,
        },
    )


@router.post("/settings")
def save_settings(
    request: Request,
    provider: str = Form(...),
    model_name: str = Form(...),
    base_url: str = Form(""),
    api_key: str = Form(""),
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
):
    if user is None:
        return RedirectResponse("/login", status_code=303)

    resolved_base_url = base_url.strip() or PROVIDER_REGISTRY.get(provider, {}).get("base_url")
    settings = db.query(AISettings).filter(AISettings.user_id == user.id).first()

    if settings is None:
        if not api_key:
            return render_settings_error(request, db, user, "An API key is required for a new provider setup.")
        settings = AISettings(
            user_id=user.id,
            provider=provider,
            encrypted_api_key=encrypt_api_key(api_key),
            model_name=model_name,
            base_url=resolved_base_url,
            is_active=True,
        )
        db.add(settings)
    else:
        settings.provider = provider
        settings.model_name = model_name
        settings.base_url = resolved_base_url
        if api_key:
            settings.encrypted_api_key = encrypt_api_key(api_key)

    db.commit()
    return RedirectResponse("/settings", status_code=303)


def render_settings_error(request: Request, db: Session, user: User, error: str):
    settings = db.query(AISettings).filter(AISettings.user_id == user.id).first()
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "settings": settings,
            "masked_key": None,
            "providers": PROVIDER_REGISTRY,
            "message": None,
            "error": error,
        },
        status_code=400,
    )


@router.post("/settings/test")
def test_connection(
    request: Request,
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
):
    if user is None:
        return RedirectResponse("/login", status_code=303)

    settings = db.query(AISettings).filter(AISettings.user_id == user.id).first()
    masked_key = None
    if settings:
        try:
            masked_key = mask_api_key(decrypt_api_key(settings.encrypted_api_key))
        except Exception:  # noqa: BLE001
            masked_key = "(unreadable)"

    if settings is None:
        return templates.TemplateResponse(
            request,
            "settings.html",
            {
                "settings": None,
                "masked_key": None,
                "providers": PROVIDER_REGISTRY,
                "message": None,
                "error": "Save your provider settings before testing the connection.",
            },
            status_code=400,
        )

    provider_instance = OpenAICompatibleProvider(
        api_key=decrypt_api_key(settings.encrypted_api_key),
        base_url=settings.base_url,
        model=settings.model_name,
    )
    ok, detail = provider_instance.test_connection()

    if ok:
        settings.last_verified_at = datetime.now(timezone.utc)
        settings.is_active = True
        db.commit()

    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "settings": settings,
            "masked_key": masked_key,
            "providers": PROVIDER_REGISTRY,
            "message": f"Test succeeded: {detail}" if ok else None,
            "error": None if ok else f"Test failed: {detail}",
        },
        status_code=200 if ok else 400,
    )

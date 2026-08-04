from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.ai.crypto import decrypt_api_key, encrypt_api_key, mask_api_key
from app.ai.provider import OpenAICompatibleProvider
from app.ai.registry import MAX_AI_PROVIDERS_PER_USER, available_providers, resolve_provider_base_url
from app.auth.csrf import verify_csrf
from app.auth.dependencies import get_current_user
from app.rate_limit import AI_SETTINGS_RATE_LIMIT, limiter, get_user_or_ip
from app.db.models import AISettings, User
from app.db.session import get_db

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

MAX_LABEL_LENGTH = 100


def _require_user(user: User | None) -> User | RedirectResponse:
    if user is None:
        return RedirectResponse("/login", status_code=303)
    return user


def _ordered_settings(db: Session, user_id: int) -> list[AISettings]:
    return (
        db.query(AISettings)
        .filter(AISettings.user_id == user_id)
        .order_by(AISettings.priority.asc(), AISettings.id.asc())
        .all()
    )


def _masked_keys(providers: list[AISettings]) -> dict[int, str]:
    masked = {}
    for settings in providers:
        try:
            masked[settings.id] = mask_api_key(decrypt_api_key(settings.encrypted_api_key))
        except Exception:  # noqa: BLE001 - decryption failure shouldn't break the page
            masked[settings.id] = "(unreadable)"
    return masked


def _display_labels(providers: list[AISettings], registry: dict) -> dict[int, str]:
    labels = {}
    for settings in providers:
        if settings.label:
            labels[settings.id] = settings.label
        else:
            info = registry.get(settings.provider)
            labels[settings.id] = info["label"] if info else settings.provider
    return labels


def _settings_context(db: Session, user: User, *, error: str | None = None, message: str | None = None) -> dict:
    providers = _ordered_settings(db, user.id)
    registry = available_providers()
    return {
        "providers": providers,
        "masked_keys": _masked_keys(providers),
        "display_labels": _display_labels(providers, registry),
        "provider_registry": registry,
        "max_providers": MAX_AI_PROVIDERS_PER_USER,
        "at_limit": len(providers) >= MAX_AI_PROVIDERS_PER_USER,
        "user_email": user.email,
        "message": message,
        "error": error,
    }


def render_settings_error(request: Request, db: Session, user: User, error: str):
    return templates.TemplateResponse(request, "settings.html", _settings_context(db, user, error=error), status_code=400)


@router.get("/settings")
def settings_page(request: Request, user: User | None = Depends(get_current_user), db: Session = Depends(get_db)):
    if user is None:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(request, "settings.html", _settings_context(db, user))


@router.post("/settings")
@limiter.limit(AI_SETTINGS_RATE_LIMIT, key_func=get_user_or_ip)
def add_provider(
    request: Request,
    provider: str = Form(...),
    model_name: str = Form(...),
    base_url: str = Form(""),
    api_key: str = Form(""),
    label: str = Form(""),
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
):
    if user is None:
        return RedirectResponse("/login", status_code=303)

    existing = _ordered_settings(db, user.id)
    if len(existing) >= MAX_AI_PROVIDERS_PER_USER:
        return render_settings_error(
            request, db, user, f"You can configure at most {MAX_AI_PROVIDERS_PER_USER} AI providers."
        )
    if len(model_name.strip()) > 255:
        return render_settings_error(request, db, user, "Model name must be 255 characters or fewer.")
    if len(base_url) > 500:
        return render_settings_error(request, db, user, "API URL must be 500 characters or fewer.")
    if len(label.strip()) > MAX_LABEL_LENGTH:
        return render_settings_error(request, db, user, f"Label must be {MAX_LABEL_LENGTH} characters or fewer.")
    if not api_key:
        return render_settings_error(request, db, user, "An API key is required.")
    try:
        resolved_base_url = resolve_provider_base_url(provider, base_url)
    except ValueError as exc:
        return render_settings_error(request, db, user, str(exc))

    next_priority = (max((s.priority for s in existing), default=-1)) + 1
    settings = AISettings(
        user_id=user.id,
        label=label.strip() or None,
        provider=provider,
        encrypted_api_key=encrypt_api_key(api_key),
        model_name=model_name,
        base_url=resolved_base_url,
        is_active=True,
        priority=next_priority,
    )
    db.add(settings)
    db.commit()
    return RedirectResponse("/settings", status_code=303)


@router.post("/settings/{settings_id}/edit")
@limiter.limit(AI_SETTINGS_RATE_LIMIT, key_func=get_user_or_ip)
def edit_provider(
    request: Request,
    settings_id: int,
    model_name: str = Form(...),
    base_url: str = Form(""),
    api_key: str = Form(""),
    label: str = Form(""),
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
):
    if user is None:
        return RedirectResponse("/login", status_code=303)

    settings = db.query(AISettings).filter(AISettings.id == settings_id, AISettings.user_id == user.id).first()
    if settings is None:
        return RedirectResponse("/settings", status_code=303)

    if len(model_name.strip()) > 255:
        return render_settings_error(request, db, user, "Model name must be 255 characters or fewer.")
    if len(base_url) > 500:
        return render_settings_error(request, db, user, "API URL must be 500 characters or fewer.")
    if len(label.strip()) > MAX_LABEL_LENGTH:
        return render_settings_error(request, db, user, f"Label must be {MAX_LABEL_LENGTH} characters or fewer.")
    try:
        resolved_base_url = resolve_provider_base_url(settings.provider, base_url)
    except ValueError as exc:
        return render_settings_error(request, db, user, str(exc))

    settings.label = label.strip() or None
    settings.model_name = model_name
    settings.base_url = resolved_base_url
    if api_key:
        settings.encrypted_api_key = encrypt_api_key(api_key)
    # A meaningfully-edited provider is worth re-verifying rather than
    # trusting a stale pass/fail from before the change.
    settings.last_verified_at = None
    db.commit()
    return RedirectResponse("/settings", status_code=303)


@router.post("/settings/{settings_id}/delete")
def delete_provider(
    settings_id: int,
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
):
    if user is None:
        return RedirectResponse("/login", status_code=303)

    settings = db.query(AISettings).filter(AISettings.id == settings_id, AISettings.user_id == user.id).first()
    if settings is not None:
        db.delete(settings)
        db.commit()
    return RedirectResponse("/settings", status_code=303)


@router.post("/settings/{settings_id}/toggle-active")
def toggle_provider_active(
    settings_id: int,
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
):
    if user is None:
        return RedirectResponse("/login", status_code=303)

    settings = db.query(AISettings).filter(AISettings.id == settings_id, AISettings.user_id == user.id).first()
    if settings is not None:
        settings.is_active = not settings.is_active
        db.commit()
    return RedirectResponse("/settings", status_code=303)


@router.post("/settings/{settings_id}/move")
def move_provider(
    settings_id: int,
    direction: str = Form(...),
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
):
    if user is None:
        return RedirectResponse("/login", status_code=303)

    providers = _ordered_settings(db, user.id)
    index = next((i for i, s in enumerate(providers) if s.id == settings_id), None)
    if index is not None:
        swap_index = index - 1 if direction == "up" else index + 1
        if 0 <= swap_index < len(providers):
            a, b = providers[index], providers[swap_index]
            a.priority, b.priority = b.priority, a.priority
            db.commit()
    return RedirectResponse("/settings", status_code=303)


@router.post("/settings/{settings_id}/test")
@limiter.limit(AI_SETTINGS_RATE_LIMIT, key_func=get_user_or_ip)
def test_connection(
    request: Request,
    settings_id: int,
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
):
    if user is None:
        return RedirectResponse("/login", status_code=303)

    settings = db.query(AISettings).filter(AISettings.id == settings_id, AISettings.user_id == user.id).first()
    if settings is None:
        return render_settings_error(request, db, user, "That provider no longer exists.")

    try:
        provider_instance = OpenAICompatibleProvider(
            api_key=decrypt_api_key(settings.encrypted_api_key),
            base_url=resolve_provider_base_url(settings.provider, settings.base_url or ""),
            model=settings.model_name,
        )
        ok, detail = provider_instance.test_connection()
    except Exception:
        ok, detail = False, "unavailable"

    if ok:
        settings.last_verified_at = datetime.now(timezone.utc)
        db.commit()

    context = _settings_context(
        db,
        user,
        message="Test succeeded: connection established." if ok else None,
        error=None if ok else "Test failed. Check the provider, model, and API key, then try again.",
    )
    return templates.TemplateResponse(request, "settings.html", context, status_code=200 if ok else 400)

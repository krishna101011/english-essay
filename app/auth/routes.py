from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.auth.csrf import verify_csrf
from app.auth.dependencies import get_current_user
from app.auth.security import hash_password, verify_password
from app.auth.tokens import (
    consume_email_verification_token,
    consume_password_reset_token,
    create_email_verification_token,
    create_password_reset_token,
)
from app.ai.routes import render_settings_error
from app.db.models import User
from app.db.session import get_db
from app.email.sender import get_email_sender
from app.rate_limit import LOGIN_RATE_LIMIT, PASSWORD_RESET_REQUEST_RATE_LIMIT, SIGNUP_RATE_LIMIT, limiter

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _send_verification_email(request: Request, db: Session, user: User) -> None:
    token = create_email_verification_token(db, user.id)
    link = f"{str(request.base_url).rstrip('/')}/verify-email?token={token.token}"
    get_email_sender().send(
        to=user.email,
        subject="Verify your email - English Essay Coach",
        body=(
            f"Welcome! Confirm your email address to start writing:\n\n{link}\n\n"
            "This link expires in 24 hours. You can still log in before "
            "verifying, but you won't be able to create essays or chapters "
            "until you do."
        ),
    )


@router.get("/signup")
def signup_form(request: Request, user: User | None = Depends(get_current_user)):
    if user:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "signup.html", {"error": None})


@router.post("/signup")
@limiter.limit(SIGNUP_RATE_LIMIT)
def signup_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    website: str = Form(""),
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
):
    if website:
        # Honeypot field: real users never see or fill this. Pretend it
        # worked so the bot doesn't learn it was caught.
        return RedirectResponse("/login", status_code=303)

    email = email.strip().lower()
    if db.query(User).filter(User.email == email).first():
        return templates.TemplateResponse(
            request, "signup.html", {"error": "An account with that email already exists."}, status_code=400
        )
    if len(password) < 8:
        return templates.TemplateResponse(
            request, "signup.html", {"error": "Password must be at least 8 characters."}, status_code=400
        )

    new_user = User(email=email, password_hash=hash_password(password))
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    _send_verification_email(request, db, new_user)
    db.commit()

    request.session["user_id"] = new_user.id
    return RedirectResponse("/", status_code=303)


@router.get("/verify-email")
def verify_email(request: Request, token: str, db: Session = Depends(get_db)):
    verified = consume_email_verification_token(db, token)
    if verified is None:
        return templates.TemplateResponse(
            request,
            "verify_email.html",
            {"success": False},
            status_code=400,
        )

    user = db.get(User, verified.user_id)
    user.email_verified = True
    db.commit()
    return templates.TemplateResponse(request, "verify_email.html", {"success": True})


@router.get("/login")
def login_form(request: Request, user: User | None = Depends(get_current_user)):
    if user:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login")
@limiter.limit(LOGIN_RATE_LIMIT)
def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
):
    email = email.strip().lower()
    db_user = db.query(User).filter(User.email == email).first()
    if not db_user or not verify_password(password, db_user.password_hash):
        return templates.TemplateResponse(
            request, "login.html", {"error": "Invalid email or password."}, status_code=400
        )

    request.session["user_id"] = db_user.id
    return RedirectResponse("/", status_code=303)


@router.post("/logout")
def logout(request: Request, _csrf: None = Depends(verify_csrf)):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@router.get("/forgot-password")
def forgot_password_form(request: Request):
    return templates.TemplateResponse(request, "forgot_password.html", {"message": None})


@router.post("/forgot-password")
@limiter.limit(PASSWORD_RESET_REQUEST_RATE_LIMIT)
def forgot_password_submit(
    request: Request,
    email: str = Form(...),
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
):
    generic_message = "If an account with that email exists, we've sent a password reset link."

    db_user = db.query(User).filter(User.email == email.strip().lower()).first()
    if db_user is not None:
        reset_token = create_password_reset_token(db, db_user.id)
        link = f"{str(request.base_url).rstrip('/')}/reset-password?token={reset_token.token}"
        get_email_sender().send(
            to=db_user.email,
            subject="Reset your password - English Essay Coach",
            body=(
                f"Someone (hopefully you) asked to reset your password:\n\n{link}\n\n"
                "This link expires in 1 hour and can only be used once. If "
                "you didn't request this, you can ignore this email."
            ),
        )
        db.commit()

    # Same message whether or not the account exists, so this can't be used
    # to enumerate registered emails.
    return templates.TemplateResponse(request, "forgot_password.html", {"message": generic_message})


@router.get("/reset-password")
def reset_password_form(request: Request, token: str):
    return templates.TemplateResponse(request, "reset_password.html", {"token": token, "error": None})


@router.post("/reset-password")
def reset_password_submit(
    request: Request,
    token: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
):
    if len(password) < 8:
        return templates.TemplateResponse(
            request,
            "reset_password.html",
            {"token": token, "error": "Password must be at least 8 characters."},
            status_code=400,
        )

    reset_token = consume_password_reset_token(db, token)
    if reset_token is None:
        return templates.TemplateResponse(
            request,
            "reset_password.html",
            {"token": token, "error": "That reset link is invalid or has expired. Request a new one."},
            status_code=400,
        )

    user = db.get(User, reset_token.user_id)
    user.password_hash = hash_password(password)
    db.commit()
    return RedirectResponse("/login", status_code=303)


@router.post("/settings/delete-account")
def delete_account(
    request: Request,
    password: str = Form(...),
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
):
    if user is None:
        return RedirectResponse("/login", status_code=303)

    if not verify_password(password, user.password_hash):
        return render_settings_error(request, db, user, "Incorrect password. Your account was not deleted.")

    db.delete(user)
    db.commit()
    request.session.clear()
    return RedirectResponse("/signup", status_code=303)

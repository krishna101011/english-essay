from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.auth.csrf import verify_csrf
from app.auth.dependencies import get_current_user
from app.db.models import User, VocabWord
from app.db.session import get_db

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/vocab")
def vocab_library(
    request: Request,
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user is None:
        return RedirectResponse("/login", status_code=303)

    words = (
        db.query(VocabWord)
        .filter(VocabWord.user_id == user.id)
        .order_by(VocabWord.mastered.asc(), VocabWord.added_at.desc())
        .all()
    )
    return templates.TemplateResponse(request, "vocab.html", {"words": words})


@router.post("/vocab/{word_id}/toggle-mastered")
def toggle_mastered(
    word_id: int,
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
):
    if user is None:
        return RedirectResponse("/login", status_code=303)

    word = db.query(VocabWord).filter(VocabWord.id == word_id, VocabWord.user_id == user.id).first()
    if word is not None:
        word.mastered = not word.mastered
        db.commit()
    return RedirectResponse("/vocab", status_code=303)

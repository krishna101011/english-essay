from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.auth.csrf import verify_csrf
from app.auth.dependencies import get_current_user
from app.db.models import User, VocabWord
from app.db.session import get_db
from app.vocab.service import (
    SEARCH_PAGE_SIZE,
    VocabValidationError,
    add_word_manually,
    delete_word,
    edit_word,
    mark_reviewed,
    search_words,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/vocab")
def vocab_library(
    request: Request,
    q: str = "",
    page: int = 1,
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user is None:
        return RedirectResponse("/login", status_code=303)

    words, total = search_words(db, user.id, q, page=page, page_size=SEARCH_PAGE_SIZE)
    total_pages = max(1, (total + SEARCH_PAGE_SIZE - 1) // SEARCH_PAGE_SIZE)
    page = min(max(page, 1), total_pages)
    return templates.TemplateResponse(
        request,
        "vocab.html",
        {
            "words": words,
            "q": q,
            "page": page,
            "total_pages": total_pages,
            "total": total,
            "form_error": None,
        },
    )


@router.post("/vocab")
def add_word(
    request: Request,
    word: str = Form(...),
    definition: str = Form(...),
    example_sentence: str = Form(...),
    notes: str = Form(""),
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
):
    if user is None:
        return RedirectResponse("/login", status_code=303)
    try:
        add_word_manually(db, user.id, word, definition, example_sentence, notes)
    except VocabValidationError as exc:
        words, total = search_words(db, user.id, "", page=1, page_size=SEARCH_PAGE_SIZE)
        return templates.TemplateResponse(
            request,
            "vocab.html",
            {
                "words": words,
                "q": "",
                "page": 1,
                "total_pages": max(1, (total + SEARCH_PAGE_SIZE - 1) // SEARCH_PAGE_SIZE),
                "total": total,
                "form_error": str(exc),
            },
            status_code=400,
        )
    return RedirectResponse("/vocab", status_code=303)


@router.post("/vocab/{word_id}/edit")
def edit_word_route(
    word_id: int,
    definition: str = Form(...),
    example_sentence: str = Form(...),
    notes: str = Form(""),
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
):
    if user is None:
        return RedirectResponse("/login", status_code=303)
    try:
        edit_word(db, user.id, word_id, definition, example_sentence, notes)
    except VocabValidationError:
        pass
    return RedirectResponse("/vocab", status_code=303)


@router.post("/vocab/{word_id}/review")
def review_word_route(
    word_id: int,
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
):
    if user is None:
        return RedirectResponse("/login", status_code=303)
    mark_reviewed(db, user.id, word_id)
    return RedirectResponse("/vocab", status_code=303)


@router.post("/vocab/{word_id}/delete")
def delete_word_route(
    word_id: int,
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
):
    if user is None:
        return RedirectResponse("/login", status_code=303)
    delete_word(db, user.id, word_id)
    return RedirectResponse("/vocab", status_code=303)


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

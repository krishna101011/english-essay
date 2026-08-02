from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, selectinload

from app.auth.csrf import verify_csrf
from app.auth.dependencies import get_current_user
from app.db.models import CorrectionSource, Document, DocumentType, DocumentVersion, Score, User
from app.db.session import get_db
from app.documents.service import get_or_create_rewrite, remove_document, submit_version

VALID_DOC_TYPES = {t.value for t in DocumentType}

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _correction_payload(version):
    return [
        {
            "category": c.category.value,
            "start_offset": c.start_offset,
            "end_offset": c.end_offset,
            "original_text": c.original_text,
            "suggested_text": c.suggested_text,
            "explanation": c.explanation,
            "source": c.source.value,
        }
        for c in sorted(version.corrections, key=lambda c: c.start_offset)
    ]


@router.get("/")
def editor_new(request: Request, user: User | None = Depends(get_current_user)):
    if user is None:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(
        request,
        "editor.html",
        {
            "document": None,
            "version": None,
            "corrections": [],
            "ai_error": None,
            "local_error": None,
            "email_verified": user.email_verified,
        },
    )


@router.post("/")
def editor_create(
    request: Request,
    title: str = Form(...),
    content: str = Form(...),
    doc_type: str = Form("essay"),
    book_title: str = Form(""),
    author: str = Form(""),
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
):
    if user is None:
        return RedirectResponse("/login", status_code=303)
    if not user.email_verified:
        return RedirectResponse("/", status_code=303)

    if doc_type not in VALID_DOC_TYPES:
        doc_type = "essay"
    is_book_chapter = doc_type == DocumentType.book_chapter.value

    document = Document(
        user_id=user.id,
        type=DocumentType(doc_type),
        title=title.strip() or "Untitled essay",
        book_title=(book_title.strip() or None) if is_book_chapter else None,
        author=(author.strip() or None) if is_book_chapter else None,
    )
    db.add(document)
    db.flush()

    result = submit_version(db, document, content)
    return templates.TemplateResponse(
        request,
        "editor.html",
        {
            "document": document,
            "version": result.version,
            "corrections": _correction_payload(result.version),
            "ai_error": result.ai_error,
            "local_error": result.local_error,
        },
    )


@router.get("/documents/{document_id}")
def view_document(
    request: Request,
    document_id: int,
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user is None:
        return RedirectResponse("/login", status_code=303)

    document = (
        db.query(Document)
        .options(selectinload(Document.versions))
        .filter(Document.id == document_id, Document.user_id == user.id)
        .first()
    )
    if document is None:
        return RedirectResponse("/history", status_code=303)

    latest_version = document.versions[-1]
    return templates.TemplateResponse(
        request,
        "editor.html",
        {
            "document": document,
            "version": latest_version,
            "corrections": _correction_payload(latest_version),
            "ai_error": None,
            "local_error": None,
        },
    )


@router.post("/documents/{document_id}")
def revise_document(
    request: Request,
    document_id: int,
    content: str = Form(...),
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
):
    if user is None:
        return RedirectResponse("/login", status_code=303)

    document = (
        db.query(Document)
        .options(selectinload(Document.versions))
        .filter(Document.id == document_id, Document.user_id == user.id)
        .first()
    )
    if document is None:
        return RedirectResponse("/history", status_code=303)

    result = submit_version(db, document, content)
    return templates.TemplateResponse(
        request,
        "editor.html",
        {
            "document": document,
            "version": result.version,
            "corrections": _correction_payload(result.version),
            "ai_error": result.ai_error,
            "local_error": result.local_error,
        },
    )


def _load_owned_version(db: Session, document_id: int, version_id: int, user_id: int) -> DocumentVersion | None:
    return (
        db.query(DocumentVersion)
        .join(Document, Document.id == DocumentVersion.document_id)
        .filter(
            DocumentVersion.id == version_id,
            DocumentVersion.document_id == document_id,
            Document.user_id == user_id,
        )
        .first()
    )


def _rewrite_response(request: Request, version: DocumentVersion, rewrite_error: str | None):
    return templates.TemplateResponse(
        request,
        "editor.html",
        {
            "document": version.document,
            "version": version,
            "corrections": _correction_payload(version),
            "ai_error": None,
            "local_error": None,
            "rewrite_error": rewrite_error,
        },
    )


@router.post("/documents/{document_id}/versions/{version_id}/rewrite")
def generate_rewrite(
    request: Request,
    document_id: int,
    version_id: int,
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
):
    if user is None:
        return RedirectResponse("/login", status_code=303)

    version = _load_owned_version(db, document_id, version_id, user.id)
    if version is None:
        return RedirectResponse("/history", status_code=303)

    result = get_or_create_rewrite(db, version, user.id, force=False)
    return _rewrite_response(request, version, result.error)


@router.post("/documents/{document_id}/versions/{version_id}/rewrite/regenerate")
def regenerate_rewrite(
    request: Request,
    document_id: int,
    version_id: int,
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
):
    if user is None:
        return RedirectResponse("/login", status_code=303)

    version = _load_owned_version(db, document_id, version_id, user.id)
    if version is None:
        return RedirectResponse("/history", status_code=303)

    result = get_or_create_rewrite(db, version, user.id, force=True)
    return _rewrite_response(request, version, result.error)


@router.post("/documents/{document_id}/delete")
def delete_document(
    request: Request,
    document_id: int,
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
):
    if user is None:
        return RedirectResponse("/login", status_code=303)

    document = db.query(Document).filter(Document.id == document_id, Document.user_id == user.id).first()
    if document is None:
        return RedirectResponse("/history", status_code=303)

    remove_document(db, document)
    return RedirectResponse("/history", status_code=303)


@router.get("/history")
def history(
    request: Request,
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user is None:
        return RedirectResponse("/login", status_code=303)

    documents = (
        db.query(Document)
        .options(selectinload(Document.versions))
        .filter(Document.user_id == user.id)
        .order_by(Document.created_at.desc())
        .all()
    )
    rows = []
    for doc in documents:
        latest = doc.versions[-1] if doc.versions else None
        rows.append(
            {
                "document": doc,
                "latest_version_number": latest.version_number if latest else None,
                "score": latest.score if latest else None,
            }
        )

    score_history = (
        db.query(DocumentVersion.submitted_at, Score.overall_score, Document.title)
        .join(Score, Score.version_id == DocumentVersion.id)
        .join(Document, Document.id == DocumentVersion.document_id)
        .filter(Document.user_id == user.id)
        .order_by(DocumentVersion.submitted_at.asc())
        .all()
    )
    chart_points = [
        {"date": submitted_at.strftime("%Y-%m-%d"), "score": overall_score, "title": title}
        for submitted_at, overall_score, title in score_history
    ]
    return templates.TemplateResponse(request, "dashboard.html", {"rows": rows, "chart_points": chart_points})

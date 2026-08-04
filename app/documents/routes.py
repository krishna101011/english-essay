import re

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, selectinload

from app.auth.csrf import verify_csrf
from app.auth.dependencies import get_current_user
from app.db.models import CorrectionSource, Document, DocumentType, DocumentVersion, Score, User
from app.db.session import get_db
from app.documents.drafts import DraftConflictError, apply_correction, discard_draft, draft_payload, ignore_correction, load_draft, save_draft
from app.documents.comparison import compare_versions
from app.documents.pdf_export import build_essay_pdf
from app.documents.score_guidance import score_guidance
from app.documents.service import get_or_create_rewrite, remove_document, submit_version
from app.rate_limit import AI_REWRITE_RATE_LIMIT, ESSAY_SUBMISSION_RATE_LIMIT, get_user_or_ip, limiter

VALID_DOC_TYPES = {t.value for t in DocumentType}
MAX_TITLE_LENGTH = 200
MAX_ESSAY_CHARACTERS = 50_000
MAX_ESSAY_WORDS = 10_000
# Matches Document.book_title / Document.author (String(255)) - SQLite
# doesn't enforce VARCHAR length itself, so this is the only thing actually
# capping these fields.
MAX_BOOK_FIELD_LENGTH = 255

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _document_input_error(
    title: str, content: str, book_title: str = "", author: str = ""
) -> str | None:
    if len(title.strip()) > MAX_TITLE_LENGTH:
        return f"Title must be {MAX_TITLE_LENGTH} characters or fewer."
    if len(content) > MAX_ESSAY_CHARACTERS:
        return f"Essay text must be {MAX_ESSAY_CHARACTERS:,} characters or fewer."
    if len(content.split()) > MAX_ESSAY_WORDS:
        return f"Essay text must be {MAX_ESSAY_WORDS:,} words or fewer."
    if len(book_title.strip()) > MAX_BOOK_FIELD_LENGTH:
        return f"Book title must be {MAX_BOOK_FIELD_LENGTH} characters or fewer."
    if len(author.strip()) > MAX_BOOK_FIELD_LENGTH:
        return f"Author must be {MAX_BOOK_FIELD_LENGTH} characters or fewer."
    return None


def _new_editor_error(request: Request, error: str, title: str, content: str, doc_type: str, book_title: str, author: str):
    return templates.TemplateResponse(
        request,
        "editor.html",
        {
            "document": None,
            "version": None,
            "corrections": [],
            "ai_error": None,
            "local_error": None,
            "email_verified": True,
            "form_error": error,
            "draft": {"title": title, "content": content, "type": {"value": doc_type}, "book_title": book_title, "author": author},
        },
        status_code=400,
    )


def _correction_payload(version):
    return [
        {
            "category": c.category.value,
            "id": c.id,
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
def editor_new(
    request: Request,
    verification: str | None = None,
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user is None:
        return templates.TemplateResponse(request, "public/landing.html", {})
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
            "draft": load_draft(db, user.id, None),
            "verification_status": verification if verification in ("sent", "cooldown") else None,
        },
    )


@router.post("/")
@limiter.limit(ESSAY_SUBMISSION_RATE_LIMIT, key_func=get_user_or_ip)
def editor_create(
    request: Request,
    title: str = Form(...),
    content: str = Form(...),
    doc_type: str = Form("essay"),
    book_title: str = Form(""),
    author: str = Form(""),
    draft_id: int | None = Form(None),
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
):
    if user is None:
        return RedirectResponse("/login", status_code=303)
    if not user.email_verified:
        return RedirectResponse("/", status_code=303)
    input_error = _document_input_error(title, content, book_title, author)
    if input_error:
        return _new_editor_error(request, input_error, title, content, doc_type, book_title, author)

    if doc_type not in VALID_DOC_TYPES:
        doc_type = "essay"
    is_book_chapter = doc_type == DocumentType.book_chapter.value

    # Not added to the session yet - submit_version() adds and flushes it
    # itself, as part of its persistence phase *after* the AI call, not
    # before. Flushing here would leave a half-finished Document sitting in
    # the transaction while the AI call is in flight, and the failover
    # module's cooldown-tracking commit (a small, otherwise-isolated write
    # made between provider attempts) would prematurely commit it too.
    document = Document(
        user_id=user.id,
        type=DocumentType(doc_type),
        title=title.strip() or "Untitled essay",
        book_title=(book_title.strip() or None) if is_book_chapter else None,
        author=(author.strip() or None) if is_book_chapter else None,
    )

    result = submit_version(db, document, content)
    discard_draft(db, user.id, None, draft_id)
    return templates.TemplateResponse(
        request,
        "editor.html",
        {
            "document": document,
            "version": result.version,
            "corrections": _correction_payload(result.version),
            "ai_error": result.ai_error,
            "local_error": result.local_error,
            "score_guidance": score_guidance(result.version.score),
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
    draft = load_draft(db, user.id, document.id)
    return templates.TemplateResponse(
        request,
        "editor.html",
        {
            "document": document,
            "version": latest_version,
            "corrections": _correction_payload(latest_version),
            "ai_error": None,
            "local_error": None,
            "draft": draft,
            "score_guidance": score_guidance(latest_version.score),
        },
    )


@router.post("/documents/{document_id}")
@limiter.limit(ESSAY_SUBMISSION_RATE_LIMIT, key_func=get_user_or_ip)
def revise_document(
    request: Request,
    document_id: int,
    content: str = Form(...),
    draft_id: int | None = Form(None),
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
    input_error = _document_input_error(document.title, content)
    if input_error:
        return templates.TemplateResponse(
            request,
            "editor.html",
            {"document": document, "version": document.versions[-1], "corrections": [], "ai_error": None,
             "local_error": None, "form_error": input_error, "draft": {"content": content}},
            status_code=400,
        )

    result = submit_version(db, document, content)
    discard_draft(db, user.id, document.id, draft_id)
    return templates.TemplateResponse(
        request,
        "editor.html",
        {
            "document": document,
            "version": result.version,
            "corrections": _correction_payload(result.version),
            "ai_error": result.ai_error,
            "local_error": result.local_error,
            "score_guidance": score_guidance(result.version.score),
        },
    )


def _owned_document(db: Session, user_id: int, document_id: int | None) -> Document | None:
    if document_id is None:
        return None
    return db.query(Document).filter(Document.id == document_id, Document.user_id == user_id).first()


@router.post("/drafts/autosave")
def autosave_draft(
    request: Request,
    draft_id: int | None = Form(None),
    document_id: int | None = Form(None),
    base_version_id: int | None = Form(None),
    expected_revision: int | None = Form(None),
    title: str = Form(""),
    content: str = Form(""),
    doc_type: str = Form("essay"),
    book_title: str = Form(""),
    author: str = Form(""),
    target_word_count: int | None = Form(None),
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
):
    if user is None:
        return JSONResponse({"detail": "Sign in to save a draft."}, status_code=401)
    document = _owned_document(db, user.id, document_id)
    if document_id is not None and document is None:
        return JSONResponse({"detail": "Draft not found."}, status_code=404)
    if base_version_id is not None and (document is None or not any(v.id == base_version_id for v in document.versions)):
        return JSONResponse({"detail": "Draft source version not found."}, status_code=404)
    if doc_type not in VALID_DOC_TYPES or target_word_count is not None and not 1 <= target_word_count <= MAX_ESSAY_WORDS:
        return JSONResponse({"detail": "Draft settings are invalid."}, status_code=400)
    error = _document_input_error(title, content, book_title, author)
    if error:
        return JSONResponse({"detail": error}, status_code=400)
    try:
        draft = save_draft(
            db, user_id=user.id, document=document, base_version_id=base_version_id, draft_id=draft_id,
            expected_revision=expected_revision, title=title, content=content, doc_type=doc_type,
            book_title=book_title, author=author, target_word_count=target_word_count,
        )
    except DraftConflictError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=409)
    except LookupError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=404)
    return JSONResponse(draft_payload(draft))


@router.post("/drafts/{draft_id}/corrections/{correction_id}/apply")
def apply_draft_correction(
    draft_id: int, correction_id: int, expected_revision: int = Form(...),
    user: User | None = Depends(get_current_user), db: Session = Depends(get_db), _csrf: None = Depends(verify_csrf),
):
    if user is None:
        return JSONResponse({"detail": "Sign in to update a draft."}, status_code=401)
    try:
        return JSONResponse(draft_payload(apply_correction(db, user.id, draft_id, correction_id, expected_revision)))
    except DraftConflictError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=409)
    except LookupError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=404)


@router.post("/drafts/{draft_id}/corrections/{correction_id}/ignore")
def ignore_draft_correction(
    draft_id: int, correction_id: int, expected_revision: int = Form(...),
    user: User | None = Depends(get_current_user), db: Session = Depends(get_db), _csrf: None = Depends(verify_csrf),
):
    if user is None:
        return JSONResponse({"detail": "Sign in to update a draft."}, status_code=401)
    try:
        return JSONResponse(draft_payload(ignore_correction(db, user.id, draft_id, correction_id, expected_revision)))
    except DraftConflictError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=409)
    except LookupError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=404)


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


@router.get("/documents/{document_id}/compare")
def compare_document_versions(
    request: Request, document_id: int, from_version_id: int, to_version_id: int,
    user: User | None = Depends(get_current_user), db: Session = Depends(get_db),
):
    if user is None:
        return RedirectResponse("/login", status_code=303)
    before = _load_owned_version(db, document_id, from_version_id, user.id)
    after = _load_owned_version(db, document_id, to_version_id, user.id)
    if before is None or after is None:
        return RedirectResponse("/history", status_code=303)
    try:
        segments = compare_versions(before.content, after.content)
    except ValueError as exc:
        return templates.TemplateResponse(request, "compare_versions.html", {"document": before.document, "before": before, "after": after, "segments": [], "draft": None, "error": str(exc)}, status_code=400)
    return templates.TemplateResponse(request, "compare_versions.html", {"document": before.document, "before": before, "after": after, "segments": segments, "draft": load_draft(db, user.id, document_id)})


@router.post("/documents/{document_id}/versions/{version_id}/restore-draft")
def restore_version_to_draft(
    request: Request, document_id: int, version_id: int, expected_revision: int | None = Form(None),
    user: User | None = Depends(get_current_user), db: Session = Depends(get_db), _csrf: None = Depends(verify_csrf),
):
    if user is None:
        return RedirectResponse("/login", status_code=303)
    version = _load_owned_version(db, document_id, version_id, user.id)
    if version is None:
        return RedirectResponse("/history", status_code=303)
    document = version.document
    draft = load_draft(db, user.id, document_id)
    try:
        save_draft(
            db, user_id=user.id, document=document, base_version_id=version.id, draft_id=draft.id if draft else None,
            expected_revision=expected_revision if draft else None, title=document.title, content=version.content,
            doc_type=document.type.value, book_title=document.book_title or "", author=document.author or "", target_word_count=draft.target_word_count if draft else None,
        )
    except DraftConflictError:
        return RedirectResponse(f"/documents/{document_id}", status_code=303)
    return RedirectResponse(f"/documents/{document_id}", status_code=303)


def _rewrite_response(request: Request, db: Session, user_id: int, version: DocumentVersion, rewrite_error: str | None):
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
            "score_guidance": score_guidance(version.score),
            # Without this, the textarea falls back to `version.content`
            # (the last *submitted* text) - silently discarding any edits
            # the user made after submitting but before clicking "See an
            # improved version"/"Regenerate", since those routes never
            # touch the draft themselves.
            "draft": load_draft(db, user_id, version.document_id),
        },
    )


@router.post("/documents/{document_id}/versions/{version_id}/rewrite")
@limiter.limit(AI_REWRITE_RATE_LIMIT, key_func=get_user_or_ip)
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
    return _rewrite_response(request, db, user.id, version, result.error)


@router.post("/documents/{document_id}/versions/{version_id}/rewrite/regenerate")
@limiter.limit(AI_REWRITE_RATE_LIMIT, key_func=get_user_or_ip)
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
    return _rewrite_response(request, db, user.id, version, result.error)


@router.get("/documents/{document_id}/versions/{version_id}/export.pdf")
def export_version_pdf(
    document_id: int,
    version_id: int,
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user is None:
        return RedirectResponse("/login", status_code=303)

    version = _load_owned_version(db, document_id, version_id, user.id)
    if version is None:
        return RedirectResponse("/history", status_code=303)

    pdf_bytes = build_essay_pdf(version.document, version)
    safe_title = re.sub(r"[^A-Za-z0-9._-]+", "-", version.document.title.strip()) or "essay"
    filename = f"{safe_title}-v{version.version_number}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
                "latest_version_id": latest.id if latest else None,
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

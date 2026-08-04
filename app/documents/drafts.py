from datetime import timedelta

from sqlalchemy.orm import Session

from app.db.models import Correction, Document, DocumentType, WritingDraft, utcnow

DRAFT_RETENTION_DAYS = 30


class DraftConflictError(ValueError):
    pass


def context_key(document_id: int | None) -> str:
    return f"document:{document_id}" if document_id is not None else "new"


def cleanup_stale_drafts(db: Session) -> None:
    cutoff = utcnow() - timedelta(days=DRAFT_RETENTION_DAYS)
    db.query(WritingDraft).filter(WritingDraft.updated_at < cutoff).delete(synchronize_session=False)


def load_draft(db: Session, user_id: int, document_id: int | None) -> WritingDraft | None:
    return (
        db.query(WritingDraft)
        .filter(WritingDraft.user_id == user_id, WritingDraft.context_key == context_key(document_id))
        .first()
    )


def save_draft(
    db: Session,
    *,
    user_id: int,
    document: Document | None,
    base_version_id: int | None,
    draft_id: int | None,
    expected_revision: int | None,
    title: str,
    content: str,
    doc_type: str,
    book_title: str,
    author: str,
    target_word_count: int | None,
) -> WritingDraft:
    cleanup_stale_drafts(db)
    key = context_key(document.id if document else None)
    draft = None
    if draft_id is not None:
        draft = db.query(WritingDraft).filter(WritingDraft.id == draft_id, WritingDraft.user_id == user_id).first()
        if draft is None or draft.context_key != key:
            raise LookupError("Draft not found.")
    else:
        draft = load_draft(db, user_id, document.id if document else None)

    if draft is not None and expected_revision is not None and draft.revision != expected_revision:
        raise DraftConflictError("This draft changed in another request. Reload before saving again.")

    if draft is None:
        draft = WritingDraft(
            user_id=user_id,
            document_id=document.id if document else None,
            base_version_id=base_version_id,
            context_key=key,
            type=DocumentType(doc_type),
            title=title,
            book_title=book_title or None,
            author=author or None,
            content=content,
            target_word_count=target_word_count,
        )
        db.add(draft)
    else:
        draft.base_version_id = base_version_id
        draft.type = DocumentType(doc_type)
        draft.title = title
        draft.book_title = book_title or None
        draft.author = author or None
        draft.content = content
        draft.target_word_count = target_word_count
        draft.revision += 1
    db.commit()
    db.refresh(draft)
    return draft


def discard_draft(db: Session, user_id: int, document_id: int | None, draft_id: int | None) -> None:
    if draft_id is None:
        return
    draft = db.query(WritingDraft).filter(WritingDraft.id == draft_id, WritingDraft.user_id == user_id).first()
    if draft is not None and draft.context_key == context_key(document_id):
        db.delete(draft)
        db.commit()


def apply_correction(db: Session, user_id: int, draft_id: int, correction_id: int, expected_revision: int) -> WritingDraft:
    draft = db.query(WritingDraft).filter(WritingDraft.id == draft_id, WritingDraft.user_id == user_id).first()
    correction = (
        db.query(Correction)
        .join(Correction.version)
        .join(Document)
        .filter(Correction.id == correction_id, Document.user_id == user_id)
        .first()
    )
    if draft is None or correction is None or draft.base_version_id != correction.version_id:
        raise LookupError("Suggestion not found.")
    if draft.revision != expected_revision:
        raise DraftConflictError("This draft changed in another request. Reload before applying a suggestion.")
    if draft.content[correction.start_offset : correction.end_offset] != correction.original_text:
        raise DraftConflictError("This suggestion no longer matches the draft. Review it manually.")
    draft.content = (
        draft.content[: correction.start_offset]
        + correction.suggested_text
        + draft.content[correction.end_offset :]
    )
    draft.revision += 1
    db.commit()
    db.refresh(draft)
    return draft


def ignore_correction(db: Session, user_id: int, draft_id: int, correction_id: int, expected_revision: int) -> WritingDraft:
    draft = db.query(WritingDraft).filter(WritingDraft.id == draft_id, WritingDraft.user_id == user_id).first()
    correction = (
        db.query(Correction)
        .join(Correction.version)
        .join(Document)
        .filter(Correction.id == correction_id, Document.user_id == user_id)
        .first()
    )
    if draft is None or correction is None or draft.base_version_id != correction.version_id:
        raise LookupError("Suggestion not found.")
    if draft.revision != expected_revision:
        raise DraftConflictError("This draft changed in another request. Reload before ignoring a suggestion.")
    ignored = draft.ignored_correction_ids()
    ignored.add(correction_id)
    draft.set_ignored_correction_ids(ignored)
    draft.revision += 1
    db.commit()
    db.refresh(draft)
    return draft


def draft_payload(draft: WritingDraft) -> dict:
    return {"id": draft.id, "revision": draft.revision, "updated_at": draft.updated_at.isoformat(), "content": draft.content}

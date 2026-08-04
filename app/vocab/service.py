from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import VocabWord, utcnow

MAX_WORD_LENGTH = 100
MAX_DEFINITION_LENGTH = 2000
MAX_EXAMPLE_LENGTH = 2000
MAX_NOTES_LENGTH = 2000
SEARCH_PAGE_SIZE = 25
MAX_SEARCH_PAGE_SIZE = 100


def _existing_by_word(db: Session, user_id: int, word: str) -> VocabWord | None:
    return (
        db.query(VocabWord)
        .filter(VocabWord.user_id == user_id, func.lower(VocabWord.word) == word.lower())
        .first()
    )


def upsert_suggested_word(
    db: Session,
    user_id: int,
    source_document_id: int | None,
    word: str,
    definition: str,
    example_sentence: str,
    source_version_id: int | None = None,
) -> VocabWord:
    """Record an AI-suggested vocabulary word, de-duplicated per user by word
    (case-insensitive). Repeated suggestions bump times_suggested rather than
    creating duplicate rows; mastered status is left untouched.

    The lookup-then-insert below still has a window where two concurrent
    submissions could both miss the SELECT and both attempt to INSERT - the
    DB-level case-insensitive unique index (see VocabWord.__table_args__) is
    what actually prevents a duplicate row in that case, and the nested
    SAVEPOINT here means a losing INSERT only rolls back the vocab-word
    insert, not the whole submit_version transaction it's called from.
    """
    word = word.strip()
    existing = _existing_by_word(db, user_id, word)
    if existing is not None:
        existing.times_suggested += 1
        return existing

    vocab_word = VocabWord(
        user_id=user_id,
        word=word,
        definition=definition,
        example_sentence=example_sentence,
        source_document_id=source_document_id,
        source_version_id=source_version_id,
        times_suggested=1,
        mastered=False,
    )
    try:
        with db.begin_nested():
            db.add(vocab_word)
            db.flush()
    except IntegrityError:
        existing = _existing_by_word(db, user_id, word)
        if existing is None:  # pragma: no cover - only reachable under a conflicting non-word constraint
            raise
        existing.times_suggested += 1
        return existing
    return vocab_word


class VocabValidationError(ValueError):
    pass


def _validate_word_fields(word: str, definition: str, example_sentence: str, notes: str | None) -> None:
    if not word.strip():
        raise VocabValidationError("Enter a word.")
    if len(word.strip()) > MAX_WORD_LENGTH:
        raise VocabValidationError(f"Word must be {MAX_WORD_LENGTH} characters or fewer.")
    if len(definition) > MAX_DEFINITION_LENGTH:
        raise VocabValidationError(f"Definition must be {MAX_DEFINITION_LENGTH:,} characters or fewer.")
    if len(example_sentence) > MAX_EXAMPLE_LENGTH:
        raise VocabValidationError(f"Example sentence must be {MAX_EXAMPLE_LENGTH:,} characters or fewer.")
    if notes and len(notes) > MAX_NOTES_LENGTH:
        raise VocabValidationError(f"Notes must be {MAX_NOTES_LENGTH:,} characters or fewer.")


def add_word_manually(
    db: Session,
    user_id: int,
    word: str,
    definition: str,
    example_sentence: str,
    notes: str | None = None,
) -> tuple[VocabWord, bool]:
    """Student-initiated save. Returns (word, created) - created=False means
    it was already in the library and got merged instead of duplicated."""
    _validate_word_fields(word, definition, example_sentence, notes)
    word = word.strip()
    existing = _existing_by_word(db, user_id, word)
    if existing is not None:
        existing.times_suggested += 1
        if notes and not existing.notes:
            existing.notes = notes
        db.commit()
        return existing, False

    vocab_word = VocabWord(
        user_id=user_id,
        word=word,
        definition=definition,
        example_sentence=example_sentence,
        notes=notes or None,
        times_suggested=1,
        mastered=False,
    )
    try:
        with db.begin_nested():
            db.add(vocab_word)
            db.flush()
    except IntegrityError:
        existing = _existing_by_word(db, user_id, word)
        if existing is None:  # pragma: no cover
            raise
        existing.times_suggested += 1
        db.commit()
        return existing, False
    db.commit()
    db.refresh(vocab_word)
    return vocab_word, True


def edit_word(
    db: Session,
    user_id: int,
    word_id: int,
    definition: str,
    example_sentence: str,
    notes: str | None,
) -> VocabWord | None:
    entry = db.query(VocabWord).filter(VocabWord.id == word_id, VocabWord.user_id == user_id).first()
    if entry is None:
        return None
    _validate_word_fields(entry.word, definition, example_sentence, notes)
    entry.definition = definition
    entry.example_sentence = example_sentence
    entry.notes = notes or None
    db.commit()
    return entry


def mark_reviewed(db: Session, user_id: int, word_id: int) -> VocabWord | None:
    entry = db.query(VocabWord).filter(VocabWord.id == word_id, VocabWord.user_id == user_id).first()
    if entry is None:
        return None
    entry.last_reviewed_at = utcnow()
    db.commit()
    return entry


def delete_word(db: Session, user_id: int, word_id: int) -> bool:
    entry = db.query(VocabWord).filter(VocabWord.id == word_id, VocabWord.user_id == user_id).first()
    if entry is None:
        return False
    db.delete(entry)
    db.commit()
    return True


def search_words(
    db: Session,
    user_id: int,
    query: str | None,
    page: int = 1,
    page_size: int = SEARCH_PAGE_SIZE,
) -> tuple[list[VocabWord], int]:
    page = max(page, 1)
    page_size = min(max(page_size, 1), MAX_SEARCH_PAGE_SIZE)

    base = db.query(VocabWord).filter(VocabWord.user_id == user_id)
    if query and query.strip():
        like = f"%{query.strip().lower()}%"
        base = base.filter(func.lower(VocabWord.word).like(like))

    total = base.count()
    items = (
        base.order_by(VocabWord.mastered.asc(), VocabWord.added_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return items, total

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import VocabWord


def upsert_suggested_word(
    db: Session,
    user_id: int,
    source_document_id: int | None,
    word: str,
    definition: str,
    example_sentence: str,
) -> VocabWord:
    """Record an AI-suggested vocabulary word, de-duplicated per user by word
    (case-insensitive). Repeated suggestions bump times_suggested rather than
    creating duplicate rows; mastered status is left untouched."""
    word = word.strip()
    existing = (
        db.query(VocabWord)
        .filter(VocabWord.user_id == user_id, func.lower(VocabWord.word) == word.lower())
        .first()
    )
    if existing is not None:
        existing.times_suggested += 1
        return existing

    vocab_word = VocabWord(
        user_id=user_id,
        word=word,
        definition=definition,
        example_sentence=example_sentence,
        source_document_id=source_document_id,
        times_suggested=1,
        mastered=False,
    )
    db.add(vocab_word)
    return vocab_word

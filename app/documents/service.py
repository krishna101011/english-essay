import logging
import time
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.ai.crypto import decrypt_api_key
from app.ai.provider import OpenAICompatibleProvider
from app.db.models import (
    AISettings,
    Correction,
    CorrectionCategory,
    CorrectionSource,
    Document,
    DocumentVersion,
    ModelRewrite,
    Score,
    VocabWord,
    utcnow,
)
from app.documents.diff import diff_paragraphs
from app.grammar.checker import JavaNotFoundError, check_text
from app.vocab.service import upsert_suggested_word

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    version: DocumentVersion
    ai_error: str | None
    local_error: str | None


@dataclass
class RewriteResult:
    rewrite: ModelRewrite | None
    error: str | None


def submit_version(db: Session, document: Document, content: str) -> PipelineResult:
    # Everything through the AI call below is pure computation / external
    # I/O - no db.add()/flush() happens yet, so no write transaction is
    # open while we wait on the local checker or the (potentially slow)
    # AI provider. SQLite only takes a write lock once we actually issue a
    # write statement, so keeping that until after these calls return
    # means another connection can never get blocked behind us for as
    # long as the AI call takes - only for however long the persistence
    # step below actually needs, which is just a handful of inserts.
    previous_version = document.versions[-1] if document.versions else None
    next_version_number = (previous_version.version_number + 1) if previous_version else 1

    local_error = None
    local_check_start = time.perf_counter()
    try:
        local_findings = check_text(content)
    except JavaNotFoundError as exc:
        local_findings = []
        local_error = str(exc)
    logger.info("submit_version: local grammar check took %.3fs", time.perf_counter() - local_check_start)

    context = {"type": document.type.value, "title": document.title}
    if document.type.value == "book_chapter":
        context["book_title"] = document.book_title
        context["author"] = document.author

    carried_llm_corrections = []
    if previous_version is not None:
        changed_ranges, unchanged_pairs = diff_paragraphs(previous_version.content, content)
        context["changed_paragraph_ranges"] = changed_ranges

        previous_llm_corrections = [c for c in previous_version.corrections if c.source == CorrectionSource.llm]
        for old_p, new_p in unchanged_pairs:
            delta = new_p["start"] - old_p["start"]
            for corr in previous_llm_corrections:
                if old_p["start"] <= corr.start_offset and corr.end_offset <= old_p["end"]:
                    carried_llm_corrections.append(
                        {
                            "category": corr.category,
                            "start_offset": corr.start_offset + delta,
                            "end_offset": corr.end_offset + delta,
                            "original_text": corr.original_text,
                            "suggested_text": corr.suggested_text,
                            "explanation": corr.explanation,
                        }
                    )

    ai_settings = db.query(AISettings).filter(AISettings.user_id == document.user_id).first()
    ai_error = None
    feedback = None

    if ai_settings is None:
        ai_error = "No AI provider configured. Add one in Settings to get sentence-structure and vocabulary feedback."
    else:
        ai_call_start = time.perf_counter()
        try:
            provider = OpenAICompatibleProvider(
                api_key=decrypt_api_key(ai_settings.encrypted_api_key),
                base_url=ai_settings.base_url,
                model=ai_settings.model_name,
            )
            feedback = provider.analyze(content, {"local_findings": local_findings}, context)
        except Exception as exc:  # noqa: BLE001 - any provider/network failure must degrade gracefully
            ai_error = f"AI feedback unavailable: {exc}"
        finally:
            logger.info("submit_version: AI provider call took %.3fs", time.perf_counter() - ai_call_start)

    # --- persistence phase: everything above is already computed, so
    # this is just a short burst of inserts before an immediate commit. ---

    version = DocumentVersion(document_id=document.id, content=content, version_number=next_version_number)
    db.add(version)
    db.flush()

    for finding in local_findings:
        db.add(
            Correction(
                version_id=version.id,
                category=CorrectionCategory(finding["category"]),
                start_offset=finding["start_offset"],
                end_offset=finding["end_offset"],
                original_text=finding["original_text"],
                suggested_text=finding["suggested_text"],
                explanation=finding["explanation"],
                source=CorrectionSource.local,
            )
        )

    for carried in carried_llm_corrections:
        db.add(
            Correction(
                version_id=version.id,
                category=carried["category"],
                start_offset=carried["start_offset"],
                end_offset=carried["end_offset"],
                original_text=carried["original_text"],
                suggested_text=carried["suggested_text"],
                explanation=carried["explanation"],
                source=CorrectionSource.llm,
            )
        )

    if feedback is not None:
        for correction in feedback.corrections:
            if correction.category not in ("sentence_structure", "vocab"):
                continue
            if not (0 <= correction.start_offset < correction.end_offset <= len(content)):
                continue
            db.add(
                Correction(
                    version_id=version.id,
                    category=CorrectionCategory(correction.category),
                    start_offset=correction.start_offset,
                    end_offset=correction.end_offset,
                    original_text=correction.original_text,
                    suggested_text=correction.suggested_text,
                    explanation=correction.explanation,
                    source=CorrectionSource.llm,
                )
            )
            if correction.category == "vocab" and correction.definition and correction.example_sentence:
                upsert_suggested_word(
                    db,
                    user_id=document.user_id,
                    source_document_id=document.id,
                    word=correction.suggested_text,
                    definition=correction.definition,
                    example_sentence=correction.example_sentence,
                )
        db.add(
            Score(
                version_id=version.id,
                overall_score=feedback.overall_score,
                grammar_score=feedback.grammar_score,
                vocab_score=feedback.vocab_score,
                structure_score=feedback.structure_score,
                clarity_score=feedback.clarity_score,
                feedback_summary=feedback.feedback_summary,
            )
        )

    db.commit()
    db.refresh(version)
    return PipelineResult(version=version, ai_error=ai_error, local_error=local_error)


def get_or_create_rewrite(db: Session, version: DocumentVersion, user_id: int, force: bool = False) -> RewriteResult:
    if not force and version.model_rewrite is not None:
        return RewriteResult(rewrite=version.model_rewrite, error=None)

    ai_settings = db.query(AISettings).filter(AISettings.user_id == user_id).first()
    if ai_settings is None:
        return RewriteResult(
            rewrite=version.model_rewrite,
            error="No AI provider configured. Add one in Settings to generate a model rewrite.",
        )

    # Nothing above this line is a write (just attribute reads and a
    # SELECT), so no write lock is held while we wait on the AI call here -
    # keep it that way. db.add()/commit only happen below, once we already
    # have the content in hand.
    try:
        provider = OpenAICompatibleProvider(
            api_key=decrypt_api_key(ai_settings.encrypted_api_key),
            base_url=ai_settings.base_url,
            model=ai_settings.model_name,
        )
        content = provider.rewrite(version.content)
    except Exception as exc:  # noqa: BLE001 - any provider/network failure must degrade gracefully
        return RewriteResult(rewrite=version.model_rewrite, error=f"Model rewrite unavailable: {exc}")

    if version.model_rewrite is not None:
        version.model_rewrite.content = content
        version.model_rewrite.created_at = utcnow()
        rewrite = version.model_rewrite
    else:
        rewrite = ModelRewrite(version_id=version.id, content=content)
        db.add(rewrite)

    db.commit()
    db.refresh(rewrite)
    return RewriteResult(rewrite=rewrite, error=None)


def remove_document(db: Session, document: Document) -> None:
    # source_document_id has no DB-level ON DELETE behavior (SQLite FK
    # enforcement is never turned on in this app), so without this the
    # column is left dangling - pointing at a document row that no longer
    # exists - instead of being nulled out. Vocab words are meant to
    # outlive the essay they were suggested from.
    db.query(VocabWord).filter(VocabWord.source_document_id == document.id).update({"source_document_id": None})
    db.delete(document)
    db.commit()

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
    Score,
)
from app.documents.diff import diff_paragraphs
from app.grammar.checker import JavaNotFoundError, check_text


@dataclass
class PipelineResult:
    version: DocumentVersion
    ai_error: str | None
    local_error: str | None


def submit_version(db: Session, document: Document, content: str) -> PipelineResult:
    previous_version = document.versions[-1] if document.versions else None
    next_version_number = (previous_version.version_number + 1) if previous_version else 1

    version = DocumentVersion(document_id=document.id, content=content, version_number=next_version_number)
    db.add(version)
    db.flush()

    local_error = None
    try:
        local_findings = check_text(content)
    except JavaNotFoundError as exc:
        local_findings = []
        local_error = str(exc)

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

    context = {"type": document.type.value, "title": document.title}

    if previous_version is not None:
        changed_ranges, unchanged_pairs = diff_paragraphs(previous_version.content, content)
        context["changed_paragraph_ranges"] = changed_ranges

        previous_llm_corrections = [c for c in previous_version.corrections if c.source == CorrectionSource.llm]
        for old_p, new_p in unchanged_pairs:
            delta = new_p["start"] - old_p["start"]
            for corr in previous_llm_corrections:
                if old_p["start"] <= corr.start_offset and corr.end_offset <= old_p["end"]:
                    db.add(
                        Correction(
                            version_id=version.id,
                            category=corr.category,
                            start_offset=corr.start_offset + delta,
                            end_offset=corr.end_offset + delta,
                            original_text=corr.original_text,
                            suggested_text=corr.suggested_text,
                            explanation=corr.explanation,
                            source=CorrectionSource.llm,
                        )
                    )

    ai_settings = db.query(AISettings).filter(AISettings.user_id == document.user_id).first()
    ai_error = None

    if ai_settings is None:
        ai_error = "No AI provider configured. Add one in Settings to get sentence-structure and vocabulary feedback."
    else:
        try:
            provider = OpenAICompatibleProvider(
                api_key=decrypt_api_key(ai_settings.encrypted_api_key),
                base_url=ai_settings.base_url,
                model=ai_settings.model_name,
            )
            feedback = provider.analyze(content, {"local_findings": local_findings}, context)
        except Exception as exc:  # noqa: BLE001 - any provider/network failure must degrade gracefully
            ai_error = f"AI feedback unavailable: {exc}"
        else:
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

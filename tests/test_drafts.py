from datetime import timedelta

import pytest

from app.auth.security import hash_password
from app.db import models
from app.documents.drafts import DraftConflictError, apply_correction, cleanup_stale_drafts, save_draft
from app.documents.comparison import compare_versions
from app.documents.score_guidance import score_guidance


def _draft(db, user, document, content="bad bad"):
    version = models.DocumentVersion(document_id=document.id, content=content, version_number=1)
    db.add(version); db.commit(); db.refresh(version)
    return save_draft(db, user_id=user.id, document=document, base_version_id=version.id, draft_id=None, expected_revision=None, title=document.title, content=content, doc_type="essay", book_title="", author="", target_word_count=None), version


def test_apply_correction_uses_its_exact_offset_not_first_matching_text(db_session, user, document):
    draft, version = _draft(db_session, user, document)
    correction = models.Correction(version_id=version.id, category=models.CorrectionCategory.grammar, start_offset=4, end_offset=7, original_text="bad", suggested_text="good", explanation="Use a precise word.", source=models.CorrectionSource.local)
    db_session.add(correction); db_session.commit()

    updated = apply_correction(db_session, user.id, draft.id, correction.id, draft.revision)

    assert updated.content == "bad good"


def test_apply_rejects_changed_draft_without_ambiguous_replacement(db_session, user, document):
    draft, version = _draft(db_session, user, document)
    correction = models.Correction(version_id=version.id, category=models.CorrectionCategory.grammar, start_offset=4, end_offset=7, original_text="bad", suggested_text="good", explanation="Use a precise word.", source=models.CorrectionSource.local)
    db_session.add(correction); db_session.commit()
    draft.content = "bad changed"; db_session.commit()

    with pytest.raises(DraftConflictError, match="no longer matches"):
        apply_correction(db_session, user.id, draft.id, correction.id, draft.revision)


def test_stale_autosave_cannot_overwrite_newer_revision(db_session, user, document):
    draft, version = _draft(db_session, user, document, "first")
    newer = save_draft(db_session, user_id=user.id, document=document, base_version_id=version.id, draft_id=draft.id, expected_revision=draft.revision, title=document.title, content="newer", doc_type="essay", book_title="", author="", target_word_count=None)

    with pytest.raises(DraftConflictError):
        save_draft(db_session, user_id=user.id, document=document, base_version_id=version.id, draft_id=draft.id, expected_revision=1, title=document.title, content="stale", doc_type="essay", book_title="", author="", target_word_count=None)
    assert newer.content == "newer"


def test_correction_cannot_be_applied_by_another_user(db_session, user, document):
    other = models.User(email="other@example.com", password_hash="x", email_verified=True); db_session.add(other); db_session.commit()
    draft, version = _draft(db_session, user, document)
    correction = models.Correction(version_id=version.id, category=models.CorrectionCategory.grammar, start_offset=0, end_offset=3, original_text="bad", suggested_text="good", explanation="", source=models.CorrectionSource.local)
    db_session.add(correction); db_session.commit()

    with pytest.raises(LookupError):
        apply_correction(db_session, other.id, draft.id, correction.id, draft.revision)


def test_cleanup_removes_abandoned_drafts(db_session, user, document):
    draft, _ = _draft(db_session, user, document)
    draft_id = draft.id
    draft.updated_at = models.utcnow() - timedelta(days=31); db_session.commit()
    cleanup_stale_drafts(db_session); db_session.commit()
    assert db_session.get(models.WritingDraft, draft_id) is None


def test_score_guidance_selects_lowest_dimension():
    score = models.Score(overall_score=72, grammar_score=80, vocab_score=55, structure_score=75, clarity_score=70, feedback_summary="", version_id=1)
    guidance = score_guidance(score)
    assert guidance["next_dimension"] == "vocab"
    assert "precise word" in guidance["next_action"]


def test_version_comparison_marks_additions_and_removals():
    segments = compare_versions("First paragraph.\nOld ending.", "First paragraph.\nNew ending.")
    assert any(segment["kind"] == "removed" and "Old ending" in segment["text"] for segment in segments)
    assert any(segment["kind"] == "added" and "New ending" in segment["text"] for segment in segments)


def test_restore_creates_draft_without_mutating_version_history(client, db_session, user, document):
    user.password_hash = hash_password("correct-horse-battery-staple")
    original = models.DocumentVersion(document_id=document.id, content="Earlier draft.", version_number=1)
    newer = models.DocumentVersion(document_id=document.id, content="Later draft.", version_number=2)
    db_session.add_all([original, newer]); db_session.commit(); db_session.refresh(original); db_session.refresh(newer)
    client.get("/login"); token = client.cookies.get("csrf_token")
    client.post("/login", data={"email": user.email, "password": "correct-horse-battery-staple", "csrf_token": token})

    response = client.post(f"/documents/{document.id}/versions/{original.id}/restore-draft", data={"csrf_token": token}, follow_redirects=False)

    assert response.status_code == 303
    draft = db_session.query(models.WritingDraft).filter_by(user_id=user.id, document_id=document.id).one()
    assert draft.content == "Earlier draft."
    assert draft.base_version_id == original.id
    assert db_session.query(models.DocumentVersion).filter_by(document_id=document.id).count() == 2
    assert db_session.get(models.DocumentVersion, newer.id).content == "Later draft."

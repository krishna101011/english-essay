import enum
import json
from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, Enum, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DocumentType(str, enum.Enum):
    essay = "essay"
    book_chapter = "book_chapter"


class CorrectionCategory(str, enum.Enum):
    spelling = "spelling"
    punctuation = "punctuation"
    grammar = "grammar"
    sentence_structure = "sentence_structure"
    vocab = "vocab"


class CorrectionSource(str, enum.Enum):
    local = "local"
    llm = "llm"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    ai_settings: Mapped[list["AISettings"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    documents: Mapped[list["Document"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    vocab_words: Mapped[list["VocabWord"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    email_verification_tokens: Mapped[list["EmailVerificationToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    password_reset_tokens: Mapped[list["PasswordResetToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    writing_drafts: Mapped[list["WritingDraft"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    weekly_goal: Mapped["WeeklyWritingGoal | None"] = relationship(back_populates="user", cascade="all, delete-orphan", uselist=False)
    writing_activities: Mapped[list["WritingActivity"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    practice_exercises: Mapped[list["PracticeExercise"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class AISettings(Base):
    __tablename__ = "ai_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    encrypted_api_key: Mapped[str] = mapped_column(Text, nullable=False)
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Failover order across a user's configured providers - lower tries
    # first. New entries default to the back of the list (see
    # app/ai/routes.py); ties break on id (insertion order).
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Set when this provider returns HTTP 429; cleared implicitly once the
    # window passes (see app/ai/failover.py) - not reset eagerly, so a call
    # that never touches this provider again just leaves it stale/expired.
    rate_limited_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(back_populates="ai_settings")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    type: Mapped[DocumentType] = mapped_column(Enum(DocumentType), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    book_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    user: Mapped["User"] = relationship(back_populates="documents")
    versions: Mapped[list["DocumentVersion"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="DocumentVersion.version_number"
    )
    writing_drafts: Mapped[list["WritingDraft"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class DocumentVersion(Base):
    __tablename__ = "document_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    document: Mapped["Document"] = relationship(back_populates="versions")
    corrections: Mapped[list["Correction"]] = relationship(back_populates="version", cascade="all, delete-orphan")
    score: Mapped["Score"] = relationship(back_populates="version", cascade="all, delete-orphan", uselist=False)
    model_rewrite: Mapped["ModelRewrite"] = relationship(
        back_populates="version", cascade="all, delete-orphan", uselist=False
    )
    writing_activity: Mapped["WritingActivity | None"] = relationship(back_populates="version", cascade="all, delete-orphan", uselist=False)


class WritingDraft(Base):
    """Mutable working copy. Submitted versions remain immutable snapshots."""

    __tablename__ = "writing_drafts"
    __table_args__ = (UniqueConstraint("user_id", "context_key", name="uq_writing_drafts_user_context"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"), nullable=True, index=True)
    base_version_id: Mapped[int | None] = mapped_column(ForeignKey("document_versions.id"), nullable=True, index=True)
    context_key: Mapped[str] = mapped_column(String(64), nullable=False)
    type: Mapped[DocumentType] = mapped_column(Enum(DocumentType), nullable=False, default=DocumentType.essay)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    book_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    target_word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ignored_correction_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False, index=True)

    user: Mapped["User"] = relationship(back_populates="writing_drafts")
    document: Mapped["Document | None"] = relationship(back_populates="writing_drafts")
    base_version: Mapped["DocumentVersion | None"] = relationship()

    def ignored_correction_ids(self) -> set[int]:
        return {int(value) for value in json.loads(self.ignored_correction_ids_json)}

    def set_ignored_correction_ids(self, values: set[int]) -> None:
        self.ignored_correction_ids_json = json.dumps(sorted(values))


class Correction(Base):
    __tablename__ = "corrections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("document_versions.id"), nullable=False, index=True)
    category: Mapped[CorrectionCategory] = mapped_column(Enum(CorrectionCategory), nullable=False)
    start_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    original_text: Mapped[str] = mapped_column(Text, nullable=False)
    suggested_text: Mapped[str] = mapped_column(Text, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[CorrectionSource] = mapped_column(Enum(CorrectionSource), nullable=False)

    version: Mapped["DocumentVersion"] = relationship(back_populates="corrections")


class Score(Base):
    __tablename__ = "scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("document_versions.id"), nullable=False, unique=True, index=True)
    overall_score: Mapped[float] = mapped_column(Float, nullable=False)
    grammar_score: Mapped[float] = mapped_column(Float, nullable=False)
    vocab_score: Mapped[float] = mapped_column(Float, nullable=False)
    structure_score: Mapped[float] = mapped_column(Float, nullable=False)
    clarity_score: Mapped[float] = mapped_column(Float, nullable=False)
    feedback_summary: Mapped[str] = mapped_column(Text, nullable=False)

    version: Mapped["DocumentVersion"] = relationship(back_populates="score")


class ModelRewrite(Base):
    __tablename__ = "model_rewrites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_id: Mapped[int] = mapped_column(
        ForeignKey("document_versions.id"), nullable=False, unique=True, index=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    version: Mapped["DocumentVersion"] = relationship(back_populates="model_rewrite")


class VocabWord(Base):
    __tablename__ = "vocab_words"
    __table_args__ = (
        UniqueConstraint("user_id", "word", name="uq_vocab_words_user_id_word"),
        # Case-insensitive dedup enforced at the DB level (matches migration
        # b3c2d1e0f9a8), so concurrent creates of "Meticulous"/"meticulous"
        # can't both succeed even under a race between the app's SELECT and
        # INSERT. Declared here too so tests (which build schema straight
        # from these models via Base.metadata.create_all, not alembic) see
        # the same constraint the real database enforces.
        Index("uq_vocab_words_user_lower_word", "user_id", text("lower(word)"), unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    word: Mapped[str] = mapped_column(String(255), nullable=False)
    definition: Mapped[str] = mapped_column(Text, nullable=False)
    example_sentence: Mapped[str] = mapped_column(Text, nullable=False)
    source_document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"), nullable=True)
    source_version_id: Mapped[int | None] = mapped_column(ForeignKey("document_versions.id", ondelete="SET NULL"), nullable=True, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    times_suggested: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    mastered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    user: Mapped["User"] = relationship(back_populates="vocab_words")
    source_document: Mapped["Document | None"] = relationship()
    source_version: Mapped["DocumentVersion | None"] = relationship()


class WeeklyWritingGoal(Base):
    __tablename__ = "weekly_writing_goals"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    target_submissions: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    user: Mapped["User"] = relationship(back_populates="weekly_goal")


class WritingActivity(Base):
    __tablename__ = "writing_activities"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("document_versions.id"), nullable=False, unique=True, index=True)
    completed_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    local_activity_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    timezone_at_creation: Mapped[str] = mapped_column(String(64), nullable=False)
    user: Mapped["User"] = relationship(back_populates="writing_activities")
    version: Mapped["DocumentVersion"] = relationship(back_populates="writing_activity")


class PracticeExercise(Base):
    __tablename__ = "practice_exercises"
    __table_args__ = (UniqueConstraint("user_id", "idempotency_key", name="uq_practice_exercises_user_idempotency"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    template_version: Mapped[str] = mapped_column(String(32), nullable=False)
    source_categories_json: Mapped[str] = mapped_column(Text, nullable=False)
    input_summary: Mapped[str] = mapped_column(String(1000), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    ai_generated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    user: Mapped["User"] = relationship(back_populates="practice_exercises")
    completions: Mapped[list["PracticeCompletion"]] = relationship(back_populates="exercise", cascade="all, delete-orphan")


class PracticeCompletion(Base):
    __tablename__ = "practice_completions"
    __table_args__ = (UniqueConstraint("exercise_id", "user_id", name="uq_practice_completion_user_exercise"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    exercise_id: Mapped[int] = mapped_column(ForeignKey("practice_exercises.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    response: Mapped[str] = mapped_column(String(2000), nullable=False, default="")
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    exercise: Mapped["PracticeExercise"] = relationship(back_populates="completions")


class EmailVerificationToken(Base):
    __tablename__ = "email_verification_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    user: Mapped["User"] = relationship(back_populates="email_verification_tokens")


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    user: Mapped["User"] = relationship(back_populates="password_reset_tokens")

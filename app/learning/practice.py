import hashlib
import json
import logging
from datetime import date

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai.crypto import decrypt_api_key
from app.ai.failover import AllProvidersUnavailableError, NoAIProviderConfiguredError, call_with_failover
from app.ai.provider import OpenAICompatibleProvider
from app.ai.registry import resolve_provider_base_url
from app.db.models import PracticeCompletion, PracticeExercise, utcnow
from app.learning.progress import recurring_mistakes

logger = logging.getLogger(__name__)

LOCAL_TEMPLATE_VERSION = "local-v1"
AI_TEMPLATE_VERSION = "ai-v1"
MAX_EXERCISES_PER_BATCH = 5
MAX_RESPONSE_LENGTH = 2000
DEFAULT_CATEGORIES = ["grammar", "vocab"]


def _provider_factory(ai_settings):
    # Module-level name (not imported directly into the caller) so tests
    # can keep doing
    # monkeypatch.setattr(practice_module, "OpenAICompatibleProvider", FakeProvider).
    return OpenAICompatibleProvider(
        api_key=decrypt_api_key(ai_settings.encrypted_api_key),
        base_url=resolve_provider_base_url(ai_settings.provider, ai_settings.base_url or ""),
        model=ai_settings.model_name,
    )

# Deterministic, always-available practice bank - no AI call required. Kept
# small and hand-written rather than sourced from student essay text, so
# nothing here ever touches a user's historic writing.
LOCAL_EXERCISE_BANK: dict[str, list[dict]] = {
    "grammar": [
        {
            "prompt": "Choose the correct verb: 'She ___ to the store every morning.'",
            "answer": "goes",
            "explanation": "Third-person singular subjects ('she') take the -s form of the verb in the simple present tense.",
        },
        {
            "prompt": "Fix the subject-verb agreement: 'The list of items are on the table.'",
            "answer": "The list of items is on the table.",
            "explanation": "The subject is 'list' (singular), not 'items' - the verb must agree with 'list'.",
        },
        {
            "prompt": "Choose the correct tense: 'By the time we arrived, the movie ___ already started.'",
            "answer": "had",
            "explanation": "Use the past perfect ('had started') for an action completed before another past action.",
        },
        {
            "prompt": "Correct the pronoun: 'Him and me went to the park.'",
            "answer": "He and I went to the park.",
            "explanation": "Subject pronouns ('he', 'I') are used as the subject of a sentence, not object pronouns ('him', 'me').",
        },
    ],
    "punctuation": [
        {
            "prompt": "Add the missing comma: 'After we finished dinner we watched a movie.'",
            "answer": "After we finished dinner, we watched a movie.",
            "explanation": "An introductory clause is followed by a comma before the main clause.",
        },
        {
            "prompt": "Fix the punctuation: 'Its a beautiful day outside.'",
            "answer": "It's a beautiful day outside.",
            "explanation": "\"It's\" is the contraction of 'it is'; 'its' (no apostrophe) is possessive.",
        },
        {
            "prompt": "Punctuate correctly: 'I bought apples oranges and bananas.'",
            "answer": "I bought apples, oranges, and bananas.",
            "explanation": "Items in a list are separated by commas, including before the final 'and'.",
        },
        {
            "prompt": "Fix the run-on sentence: 'The rain stopped we went outside.'",
            "answer": "The rain stopped, so we went outside.",
            "explanation": "Two independent clauses need a conjunction or a semicolon to join them, not just a space.",
        },
    ],
    "spelling": [
        {"prompt": "Spell the word correctly: 'recieve'", "answer": "receive", "explanation": "'i before e except after c' - after 'c', the order is 'ei'."},
        {"prompt": "Spell the word correctly: 'seperate'", "answer": "separate", "explanation": "Remember: there's 'a rat' in sep-a-rate."},
        {"prompt": "Spell the word correctly: 'definately'", "answer": "definitely", "explanation": "The root is 'definite' - keep the 'i' before adding '-ly'."},
        {"prompt": "Spell the word correctly: 'occured'", "answer": "occurred", "explanation": "The final 'r' doubles before '-ed' because the stress falls on the last syllable."},
    ],
    "sentence_structure": [
        {
            "prompt": "Rewrite as one clear sentence: 'The dog barked. It was loud. The dog was in the yard.'",
            "answer": "The dog in the yard barked loudly.",
            "explanation": "Combining short, choppy sentences into one with subordinate details improves flow.",
        },
        {
            "prompt": "Fix the sentence fragment: 'Although she studied hard for the exam.'",
            "answer": "Although she studied hard for the exam, she felt nervous.",
            "explanation": "A clause beginning with 'Although' is dependent and needs an independent clause to complete the thought.",
        },
        {
            "prompt": "Fix the dangling modifier: 'Walking to school, the rain started falling.'",
            "answer": "Walking to school, I noticed the rain start falling.",
            "explanation": "The modifier 'Walking to school' should describe a person, not 'the rain' - add the subject it modifies.",
        },
        {
            "prompt": "Vary the sentence openings: 'The cat sat. The cat watched the birds. The cat slept.'",
            "answer": "The cat sat and watched the birds before it fell asleep.",
            "explanation": "Varying sentence structure and combining related actions keeps writing from feeling repetitive.",
        },
    ],
    "vocab": [
        {"prompt": "Replace 'good' with a stronger word: 'It was a good essay.'", "answer": "It was a commendable essay.", "explanation": "'Commendable', 'exceptional', or 'polished' are more precise than the overused word 'good'."},
        {"prompt": "Replace 'said' with a more descriptive verb: 'He said the news was bad.'", "answer": "He announced the news was bad.", "explanation": "Verbs like 'announced', 'declared', or 'admitted' carry more information than the generic 'said'."},
        {"prompt": "Replace 'very happy' with one strong word.", "answer": "elated", "explanation": "Intensifiers like 'very' can often be replaced with a single, more precise word - 'elated', 'thrilled', or 'delighted'."},
        {"prompt": "Replace 'a lot of' with a more formal alternative: 'There were a lot of problems.'", "answer": "There were numerous problems.", "explanation": "'Numerous', 'considerable', or 'substantial' read as more formal than the casual 'a lot of'."},
    ],
}


def _weak_categories(db: Session, user_id: int) -> list[str]:
    weak = [m["category"] for m in recurring_mistakes(db, user_id)]
    return weak or DEFAULT_CATEGORIES


def _exercise_idempotency_key(user_id: int, category: str, bucket: str, source: str) -> str:
    payload = f"{user_id}:{category}:{bucket}:{source}"
    return hashlib.sha256(payload.encode()).hexdigest()[:48]


def _insert_or_get_existing(db: Session, exercise: PracticeExercise) -> PracticeExercise:
    """Insert one exercise, tolerating a concurrent insert of the same
    (user_id, idempotency_key) row - PracticeExercise's DB-level unique
    constraint is what actually prevents a duplicate; this just means a
    losing request reuses the winner's row instead of raising. The
    SAVEPOINT means a conflict here only rolls back this one row, not
    anything else already flushed/pending in the same batch."""
    try:
        with db.begin_nested():
            db.add(exercise)
            db.flush()
        return exercise
    except IntegrityError:
        existing = (
            db.query(PracticeExercise)
            .filter(
                PracticeExercise.user_id == exercise.user_id,
                PracticeExercise.idempotency_key == exercise.idempotency_key,
            )
            .first()
        )
        if existing is None:  # pragma: no cover - only reachable under a conflicting non-idempotency constraint
            raise
        return existing


def list_exercises(db: Session, user_id: int, limit: int = 20) -> list[PracticeExercise]:
    return (
        db.query(PracticeExercise)
        .filter(PracticeExercise.user_id == user_id)
        .order_by(PracticeExercise.created_at.desc())
        .limit(limit)
        .all()
    )


def generate_local_exercises(db: Session, user_id: int, today: date | None = None) -> list[PracticeExercise]:
    """Deterministic - no network call. Regenerating for the same user,
    weak-category set, and local calendar day returns the same rows instead
    of creating duplicates (idempotency_key covers user+category+day)."""
    today = today or utcnow().date()
    categories = _weak_categories(db, user_id)[:MAX_EXERCISES_PER_BATCH]
    bucket = today.isoformat()
    keys = {category: _exercise_idempotency_key(user_id, category, bucket, "local") for category in categories}

    existing = (
        db.query(PracticeExercise)
        .filter(PracticeExercise.user_id == user_id, PracticeExercise.idempotency_key.in_(keys.values()))
        .all()
    )
    existing_by_key = {row.idempotency_key: row for row in existing}

    results: list[PracticeExercise] = []
    inserted_any = False
    for category, key in keys.items():
        if key in existing_by_key:
            results.append(existing_by_key[key])
            continue
        bank = LOCAL_EXERCISE_BANK.get(category)
        if not bank:
            continue
        index = int(hashlib.sha256(key.encode()).hexdigest(), 16) % len(bank)
        item = bank[index]
        exercise = PracticeExercise(
            user_id=user_id,
            idempotency_key=key,
            template_version=LOCAL_TEMPLATE_VERSION,
            source_categories_json=json.dumps([category]),
            input_summary=f"Practice for: {category}",
            prompt=item["prompt"],
            answer=item["answer"],
            explanation=item["explanation"],
            ai_generated=False,
        )
        results.append(_insert_or_get_existing(db, exercise))
        inserted_any = True

    if inserted_any:
        db.commit()
    return results


def generate_ai_exercises(
    db: Session,
    user_id: int,
    categories: list[str] | None = None,
    today: date | None = None,
) -> tuple[list[PracticeExercise], str | None]:
    """User-initiated, isolated AI path. Never sends essay content to the
    provider - only category names. Nothing from the raw provider request
    or response is persisted; only the validated prompt/answer/explanation
    fields extracted from a schema-checked response ever reach the DB (see
    OpenAICompatibleProvider.generate_practice_exercises /
    PracticeExerciseBatch in app/ai/schemas.py). Idempotent per
    user+category+local day, same as the local path, so a retried request
    reuses existing rows instead of re-calling the provider."""
    today = today or utcnow().date()
    categories = (categories or _weak_categories(db, user_id))[:MAX_EXERCISES_PER_BATCH]
    bucket = today.isoformat()
    keys = {category: _exercise_idempotency_key(user_id, category, bucket, "ai") for category in categories}

    existing = (
        db.query(PracticeExercise)
        .filter(PracticeExercise.user_id == user_id, PracticeExercise.idempotency_key.in_(keys.values()))
        .all()
    )
    existing_by_key = {row.idempotency_key: row for row in existing}
    missing_categories = [c for c in categories if keys[c] not in existing_by_key]

    if not missing_categories:
        return [existing_by_key[keys[c]] for c in categories], None

    try:
        batch = call_with_failover(
            db, user_id, _provider_factory, lambda provider: provider.generate_practice_exercises(missing_categories)
        )
    except NoAIProviderConfiguredError:
        return (
            [existing_by_key[keys[c]] for c in categories if keys[c] in existing_by_key],
            "Add an AI provider in Settings to generate AI practice exercises.",
        )
    except AllProvidersUnavailableError as exc:
        message = (
            "AI exercise generation timed out. Try again, or use local practice exercises."
            if exc.timed_out
            else "AI exercise generation is unavailable right now. Try local practice exercises instead."
        )
        return (
            [existing_by_key[keys[c]] for c in categories if keys[c] in existing_by_key],
            message,
        )

    new_rows: list[PracticeExercise] = []
    seen_keys: set[str] = set()
    for item in batch.exercises[:MAX_EXERCISES_PER_BATCH]:
        if item.category not in missing_categories:
            continue  # ignore any category the provider hallucinated that we didn't ask for
        key = keys[item.category]
        if key in existing_by_key or key in seen_keys:
            continue
        seen_keys.add(key)
        exercise = PracticeExercise(
            user_id=user_id,
            idempotency_key=key,
            template_version=AI_TEMPLATE_VERSION,
            source_categories_json=json.dumps([item.category]),
            input_summary=f"AI practice for: {item.category}",
            prompt=item.prompt,
            answer=item.answer,
            explanation=item.explanation,
            ai_generated=True,
        )
        new_rows.append(_insert_or_get_existing(db, exercise))

    if new_rows:
        db.commit()

    all_rows = [existing_by_key[keys[c]] for c in categories if keys[c] in existing_by_key] + new_rows
    error = None
    if not new_rows and missing_categories:
        error = "The AI didn't return usable exercises. Try again, or use local practice exercises."
    return all_rows, error


def submit_completion(db: Session, user_id: int, exercise_id: int, response_text: str) -> tuple[PracticeExercise | None, bool | None]:
    exercise = (
        db.query(PracticeExercise)
        .filter(PracticeExercise.id == exercise_id, PracticeExercise.user_id == user_id)
        .first()
    )
    if exercise is None:
        return None, None

    response_text = response_text.strip()[:MAX_RESPONSE_LENGTH]
    correct = response_text.strip().lower() == exercise.answer.strip().lower()

    completion = (
        db.query(PracticeCompletion)
        .filter(PracticeCompletion.exercise_id == exercise_id, PracticeCompletion.user_id == user_id)
        .first()
    )
    if completion is None:
        db.add(PracticeCompletion(exercise_id=exercise_id, user_id=user_id, response=response_text))
    else:
        completion.response = response_text
        completion.completed_at = utcnow()
    db.commit()
    return exercise, correct

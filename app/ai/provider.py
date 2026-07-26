import json
from typing import Protocol

from openai import OpenAI

from app.ai.schemas import ESSAY_FEEDBACK_SCHEMA, EssayFeedback

SYSTEM_PROMPT = {
    "role": "system",
    "content": (
        "You are an expert English writing tutor. You are given an essay or "
        "book-chapter reflection plus the output of a local spelling/grammar/"
        "punctuation checker. Do not repeat findings the local checker already "
        "caught. Instead, focus only on sentence-structure feedback and "
        "vocabulary upgrade suggestions, each anchored to the exact character "
        "offsets of the relevant text in the ORIGINAL essay_text you were "
        "given (0-indexed, end-exclusive). If context.changed_paragraph_ranges "
        "is present and non-empty, this is a revision of a previously "
        "reviewed essay: only emit corrections whose offsets fall within one "
        "of those [start, end) ranges, since text outside those ranges was "
        "already reviewed in a prior submission. For every category=vocab "
        "correction, also fill in definition (a short dictionary-style "
        "definition of suggested_text) and example_sentence (an example "
        "sentence using suggested_text), since these populate the writer's "
        "vocabulary library. Regardless of "
        "changed_paragraph_ranges, always score the ENTIRE current essay_text "
        "for the rubric — scores must reflect the whole document, not just "
        "the changed portion. Produce a rubric score (0-100) for grammar, "
        "vocabulary richness, structure, and clarity, an overall score, and "
        "a short, encouraging, plain-English summary. Respond only with the "
        "requested JSON."
    ),
}


def build_user_message(essay_text: str, local_findings: dict, context: dict) -> str:
    return json.dumps(
        {
            "essay_text": essay_text,
            "local_findings": local_findings,
            "context": context,
        }
    )


class AIProvider(Protocol):
    def analyze(self, essay_text: str, local_findings: dict, context: dict) -> EssayFeedback: ...


class OpenAICompatibleProvider:
    def __init__(self, api_key: str, base_url: str, model: str):
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model

    def analyze(self, essay_text: str, local_findings: dict, context: dict) -> EssayFeedback:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                SYSTEM_PROMPT,
                {"role": "user", "content": build_user_message(essay_text, local_findings, context)},
            ],
            response_format={"type": "json_schema", "json_schema": ESSAY_FEEDBACK_SCHEMA},
        )
        return EssayFeedback.parse(response)

    def test_connection(self) -> tuple[bool, str]:
        try:
            self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": "Reply with the single word: OK"}],
                max_tokens=5,
            )
            return True, "Connection succeeded."
        except Exception as exc:  # noqa: BLE001 - surface any provider error to the user
            return False, str(exc)

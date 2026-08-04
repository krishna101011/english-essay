import json
from typing import Protocol

import httpx
from openai import OpenAI
from openai import APITimeoutError

from app.ai.schemas import EssayFeedback, PracticeExerciseBatch
from app.config import AI_TIMEOUT_SECONDS


class AIProviderTimeoutError(RuntimeError):
    pass

# Plain JSON mode (response_format={"type": "json_object"}), not strict
# json_schema mode: json_schema/structured-outputs support varies a lot
# across bring-your-own-key providers and even between models on the same
# provider (e.g. Groq only supports it for a handful of newer models, and
# rejects the request outright with a 400 for others like
# llama-3.3-70b-versatile). json_object is far more broadly supported, so
# the exact shape has to be spelled out here in the prompt instead of
# enforced by the API - EssayFeedback.parse()/model_validate() below is
# what actually validates it on the way back in.
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
        "a short, encouraging, plain-English summary. Respond only with a "
        "single JSON object matching exactly this shape, no other text: "
        '{"corrections": [{"category": "sentence_structure|vocab", '
        '"start_offset": int, "end_offset": int, "original_text": str, '
        '"suggested_text": str, "explanation": str, "definition": str or null, '
        '"example_sentence": str or null}], "overall_score": number 0-100, '
        '"grammar_score": number 0-100, "vocab_score": number 0-100, '
        '"structure_score": number 0-100, "clarity_score": number 0-100, '
        '"feedback_summary": str}'
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


PRACTICE_SYSTEM_PROMPT = {
    "role": "system",
    "content": (
        "You are an English writing tutor generating short practice exercises. "
        "You are given a list of grammar/writing category names - nothing else, "
        "no essay content. For each category, write one short fill-in-the-blank "
        "or correct-the-sentence exercise a student could complete in under a "
        "minute, with a single unambiguous correct answer and a short plain-"
        "English explanation of the rule. Echo the 'category' field back exactly "
        "as given for each exercise. Respond only with a single JSON object "
        "matching exactly this shape, no other text: "
        '{"exercises": [{"category": str, "prompt": str, "answer": str, '
        '"explanation": str}]}'
    ),
}

REWRITE_SYSTEM_PROMPT = {
    "role": "system",
    "content": (
        "You are an expert English writing tutor. Rewrite the essay you are given "
        "using ONLY the ideas, arguments, and details the writer already included. "
        "Improve vocabulary, grammar, structure, and flow, but do not introduce any "
        "new content, opinions, examples, or facts the writer didn't write. The "
        "result should read as their own essay, written by someone with stronger "
        "English - not a new essay on the same topic. Respond with only the "
        "rewritten essay text: no preamble, no commentary, no markdown formatting."
    ),
}


class AIProvider(Protocol):
    def analyze(self, essay_text: str, local_findings: dict, context: dict) -> EssayFeedback: ...
    def rewrite(self, essay_text: str) -> str: ...
    def generate_practice_exercises(self, categories: list[str]) -> PracticeExerciseBatch: ...


class OpenAICompatibleProvider:
    def __init__(self, api_key: str, base_url: str, model: str):
        # Redirects are intentionally disabled: a validated endpoint must not
        # bounce a server-side request to an internal address.
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=AI_TIMEOUT_SECONDS,
            max_retries=0,
            http_client=httpx.Client(timeout=AI_TIMEOUT_SECONDS, follow_redirects=False),
        )
        self.model = model

    def analyze(self, essay_text: str, local_findings: dict, context: dict) -> EssayFeedback:
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    SYSTEM_PROMPT,
                    {"role": "user", "content": build_user_message(essay_text, local_findings, context)},
                ],
                response_format={"type": "json_object"},
            )
        except APITimeoutError as exc:
            raise AIProviderTimeoutError("The AI provider timed out.") from exc
        return EssayFeedback.parse(response)

    def rewrite(self, essay_text: str) -> str:
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    REWRITE_SYSTEM_PROMPT,
                    {"role": "user", "content": essay_text},
                ],
            )
        except APITimeoutError as exc:
            raise AIProviderTimeoutError("The AI provider timed out.") from exc
        return response.choices[0].message.content.strip()

    def generate_practice_exercises(self, categories: list[str]) -> PracticeExerciseBatch:
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    PRACTICE_SYSTEM_PROMPT,
                    {"role": "user", "content": json.dumps({"categories": categories})},
                ],
                response_format={"type": "json_object"},
            )
        except APITimeoutError as exc:
            raise AIProviderTimeoutError("The AI provider timed out.") from exc
        return PracticeExerciseBatch.parse(response)

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

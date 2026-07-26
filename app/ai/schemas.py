import json

from pydantic import BaseModel, Field


class LLMCorrection(BaseModel):
    category: str = Field(description="One of: sentence_structure, vocab")
    start_offset: int = Field(description="Character offset where the flagged text starts")
    end_offset: int = Field(description="Character offset where the flagged text ends")
    original_text: str
    suggested_text: str
    explanation: str = Field(description="Plain-English explanation for the writer")


class EssayFeedback(BaseModel):
    corrections: list[LLMCorrection] = Field(default_factory=list)
    overall_score: float = Field(ge=0, le=100)
    grammar_score: float = Field(ge=0, le=100)
    vocab_score: float = Field(ge=0, le=100)
    structure_score: float = Field(ge=0, le=100)
    clarity_score: float = Field(ge=0, le=100)
    feedback_summary: str = Field(description="Short qualitative summary of the essay's writing quality")

    @classmethod
    def parse(cls, response) -> "EssayFeedback":
        content = response.choices[0].message.content
        return cls.model_validate(json.loads(content))


def _essay_feedback_json_schema() -> dict:
    schema = EssayFeedback.model_json_schema()
    schema["additionalProperties"] = False
    return schema


ESSAY_FEEDBACK_SCHEMA = {
    "name": "essay_feedback",
    "schema": _essay_feedback_json_schema(),
}

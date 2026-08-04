import json

from pydantic import BaseModel, Field


class LLMCorrection(BaseModel):
    category: str = Field(description="One of: sentence_structure, vocab")
    start_offset: int = Field(description="Character offset where the flagged text starts")
    end_offset: int = Field(description="Character offset where the flagged text ends")
    original_text: str
    suggested_text: str
    explanation: str = Field(description="Plain-English explanation for the writer")
    definition: str | None = Field(
        default=None,
        description="Only for category=vocab: a short dictionary-style definition of suggested_text",
    )
    example_sentence: str | None = Field(
        default=None,
        description="Only for category=vocab: an example sentence using suggested_text",
    )


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


class PracticeExerciseItem(BaseModel):
    category: str = Field(description="One of the requested category names, echoed back exactly")
    prompt: str = Field(max_length=1000, description="The exercise question shown to the student")
    answer: str = Field(max_length=500, description="The single correct answer, used for exact-match grading")
    explanation: str = Field(max_length=1000, description="Plain-English explanation of the rule being practiced")


class PracticeExerciseBatch(BaseModel):
    exercises: list[PracticeExerciseItem] = Field(default_factory=list, max_length=5)

    @classmethod
    def parse(cls, response) -> "PracticeExerciseBatch":
        content = response.choices[0].message.content
        return cls.model_validate(json.loads(content))

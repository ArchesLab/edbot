# Defines the Pydantic models of agent interfaces
from pydantic import BaseModel, Field, ConfigDict
from typing import Literal, Optional, Annotated, Union

BloomTier = Literal["Remember", "Understand", "Apply", "Analyze", "Evaluate", "Create"]
QuestionFormat = Literal["multiple_choice", "short_answer", "code_writing", "code_tracing"]

class Message(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: Literal["student", "edbot"]
    content: str

class AnswerSubmission(BaseModel):
    model_config = ConfigDict(frozen=True)

    question_text: str
    rubric: str
    student_answer: str

class OrhcestratorAgentInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    conversation: list[Message] = Field(
        min_length=1,
        description="Conversation history, oldest first"
    )

class UCAInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    concept: str
    conversation: list[Message] = Field(
        min_length=1,
        description="Conversation history, oldest first"
    )
    answer_submission: Optional[AnswerSubmission] = None

class CGABase(BaseModel):
    model_config = ConfigDict(frozen=True)

    concept: str
    target_tier: BloomTier

class GenerateQuestionInput(CGABase):
    mode: Literal["generate_question"] = "generate_question"
    format_contraint: Optional[QuestionFormat] = Field(
        default=None,
        description="None lets the CGA choose the format"
    )
    prior_questions: tuple[AnswerSubmission, ...] = Field(
        default=(),
        description="Recent questions asked by AI and the answer the student gave with its rubric"
    )

class ExplainAtTierInput(CGABase):
    mode: Literal["explain_at_tier"] = "explain_at_tier"
    conversation: tuple[Message, ...] = Field(
        min_length=1,
        description="Conversation history, oldest first"
    )

class ProbeAtTierInput(CGABase):
    mode: Literal["probe_at_tier"] = "probe_at_tier"


CGAInput = Annotated[Union[GenerateQuestionInput, ExplainAtTierInput, ProbeAtTierInput], Field(discriminator="mode")]
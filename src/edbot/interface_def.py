from dataclasses import dataclass
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict, model_validator
from typing import Literal, Optional, Union

BloomTier = Literal["Remember", "Understand", "Apply", "Analyze", "Evaluate", "Create"]
QuestionFormat = Literal["multiple_choice", "short_answer", "code_writing", "code_tracing"]
Confidence = Literal["high", "medium", "low"]


########################
# Shared Student Model #
########################
# Per-turn runtime context: set once by chat_turn(), handed to every tool (including tools inside
# subagents) as runtime.context. A dataclass rather than a BaseModel so it's never saved in checkpoints
@dataclass(frozen=True) # object is read-only, not a Pydantic type, not saved in context
class EdbotContext:
    student_id: str # whose turn this is; tools use it to pick the student's namespace in the store

class StudentModelEntry(BaseModel):
    """One student's assessment for one concept. Written only by the UCA's update_student_model tool."""
    model_config = ConfigDict(frozen=True)

    concept: str
    tier: BloomTier
    confidence: Confidence
    rationale: str = Field(description="The UCA's evidence for the tier; never shown to the student")
    assessed_at: datetime = Field(description="Set by code when saved")
    assessed_at_turn: int = Field(description="Student message count when assessed, for the cadence check")
    assessment_count: int = Field(description="Times this concept has been assessed, 1 on the first")

#################################
# Shared Question-Logging Model #
#################################
class QuestionLogEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    question_id: str            # generate ID, the store key
    concept: str
    tier: BloomTier
    format: QuestionFormat
    question_text: str          # what the student saw
    rubric: str
    concept_tags: list[str] = []
    asked_at: datetime
    asked_at_turn: int
    # filled in later, once the student answers
    student_answer: Optional[str] = None
    verdict: Optional[Literal["correct", "partially_correct", "incorrect"]] = None
    judgment_note: Optional[str] = None
    answered_at_turn: Optional[int] = None


class Message(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: Literal["student", "edbot"]
    content: str

class AnswerSubmission(BaseModel):
    model_config = ConfigDict(frozen=True)

    question_text: str
    rubric: str
    student_answer: str

class ChatBotOutput(BaseModel):
    model_config = ConfigDict(frozen=True)

    response: str

class OrchestratorAgentInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    conversation: list[Message] = Field(
        min_length=1,
        description="Conversation history, oldest first"
    )

class UCAInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    
    concept: str
    invocation_context: Literal["answer_submission", "practice_request", "followup_clarification", "new_evidence", "cadence_backstop", "cold_start", "other"]
    question_id: Optional[str] = None       # which logged question the student is answering
    student_answer: Optional[str] = None    # the student's answer to question_id
    # Filled from the question log by QuestionLogMiddleware when question_id is set
    answer_submission: Optional[AnswerSubmission] = None

    @model_validator(mode="after")
    def _question_id_needs_answer(self):
        if self.question_id and not self.student_answer:
            raise ValueError("question_id is set, so student_answer is required")
        return self

class AnswerJudgment(BaseModel):
    model_config = ConfigDict(frozen=True)

    verdict: Literal["correct", "partially_correct", "incorrect"]
    note: str = Field(description="Which rubric criteria were met or missed")

class UCAOutput(BaseModel):
    model_config = ConfigDict(frozen=True)

    concept: str
    prior_tier: Optional[BloomTier] = Field(
        description="Tier from the student model before this assessment, None if never assessed"
    )
    tier: BloomTier
    confidence: Confidence
    rationale: str = Field(description="1-3 sentences tying the estimate to what the student said")
    answer_judgment: Optional[AnswerJudgment] = Field(
        default=None,
        description="Set only when the input had an answer_submission"
    )
    next_probe_tier: Optional[BloomTier] = Field(
        default=None,
        description="Set only during cold-start probing; None once probing is finished"
    )

class CGABase(BaseModel):
    model_config = ConfigDict(frozen=True)

    concept: str
    target_tier: BloomTier

class GenerateQuestionInput(CGABase):
    mode: Literal["generate_question"] = "generate_question"
    format_constraint: Optional[QuestionFormat] = Field(
        default=None,
        description="None lets the CGA choose the format"
    )
    prior_questions: tuple[AnswerSubmission, ...] = Field(
        default=(),
        description="Recent questions asked by AI and the answer the student gave with its rubric"
    )

class ExplainAtTierInput(CGABase):
    mode: Literal["explain_at_tier"] = "explain_at_tier"
    # Conversation history comes from ConversationMiddleware through state, like UCAInput

class ProbeAtTierInput(CGABase):
    mode: Literal["probe_at_tier"] = "probe_at_tier"

CGAInput = Union[GenerateQuestionInput, ExplainAtTierInput, ProbeAtTierInput]

class CGAOutput(BaseModel):
    model_config = ConfigDict(frozen=True)

    mode: Literal["generate_question", "explain_at_tier", "probe_at_tier"]
    concept: str
    target_tier: BloomTier
    content: str = Field(description="Student-facing question, explanation, or probe; never contains the rubric or answer")
    format: Optional[QuestionFormat] = Field(
        default=None,
        description="Set only for generate_question"
    )
    rubric: Optional[str] = Field(
        default=None,
        description="Set only for generate_question: answer key and grading criteria for the UCA"
    )
    concept_tags: Optional[list[str]] = Field(
        default=None,
        description="Set only for generate_question: the concept ID plus related sub-concepts the question tests"
    )
    sources: list[str] = Field(description="SEBook page titles (and URLs, when returned) the content is based on")

# Events chat_turn() yields to an interface (CLI, Chainlit, later FastAPI). Only these reach the
# student, so they must never carry tool names, subagent output, tiers, or rubrics
class Status(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["status"] = "status"
    text: str = Field(description="Neutral progress note, e.g. 'Looking through course material…'")

class TextDelta(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["text"] = "text"
    text: str = Field(description="Next piece of edbot's reply")

class Done(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["done"] = "done"

class Error(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["error"] = "error"
    message: str = Field(description="Student-facing message; details go to the server log")

TurnEvent = Union[Status, TextDelta, Done, Error]
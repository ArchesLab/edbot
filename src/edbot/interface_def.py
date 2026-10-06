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
    # Conversation history isn't passed here: ConversationMiddleware hands it to subagents through state
    answer_submission: Optional[AnswerSubmission] = None

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
    confidence: Literal["high", "medium", "low"]
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
    # Conversation history comes from ConversationMiddleware through state, like UCAInput

class ProbeAtTierInput(CGABase):
    mode: Literal["probe_at_tier"] = "probe_at_tier"


CGAInput = Union[GenerateQuestionInput, ExplainAtTierInput, ProbeAtTierInput]
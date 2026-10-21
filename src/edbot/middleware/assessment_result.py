"""Persist one validated UCA result without another model generation.

The production service is one process with an AsyncSqliteStore. Its public
``abatch`` puts the entry and replay receipt in one SQLite statement/transaction
(index=False avoids embedding side effects). BaseStore does not promise atomic
compare-and-swap for every backend: a multi-worker service needs a database-level
lock/CAS before using this path. The local lock also serializes UCA tasks emitted
in one parent tool batch; service.py's per-turn lock alone cannot do that.
"""
import asyncio
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
from weakref import WeakKeyDictionary

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.store.base import PutOp
from langgraph.types import Command

from edbot import model_config, student_model
from edbot.interface_def import Message, StudentModelEntry, UCAInput, UCAOutput

_UCA = "understanding-checking-agent"
# Weak store keys keep disposable evaluation stores from accumulating here.
_LOCKS = WeakKeyDictionary()


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()


def _entry_json(entry):
    return entry.model_dump(mode="json") if entry else None


def _applies(request):
    call = request.tool_call
    return (model_config.DETERMINISTIC_ASSESSMENT_SAVE and call["name"] == "task"
            and call["args"].get("subagent_type") == _UCA)


def _result_message(result, call_id):
    messages = result.update.get("messages", []) if isinstance(result, Command) and isinstance(result.update, dict) else [result]
    if (len(messages) != 1 or not isinstance(messages[0], ToolMessage)
            or messages[0].tool_call_id != call_id or messages[0].status != "success"
            or messages[0].name not in (None, "task") or not isinstance(messages[0].content, str)):
        raise ValueError("Assessment task did not return one matching successful structured result")
    return messages[0]


class AssessmentResultMiddleware(AgentMiddleware):
    """Parent task boundary; student identity and the input come from trusted runtime."""

    def wrap_tool_call(self, request, handler):
        if not _applies(request):
            return handler(request)
        # UCA's existing student-model tools and production store are async.
        raise NotImplementedError("Deterministic assessment persistence requires ainvoke()/astream()")

    async def awrap_tool_call(self, request, handler):
        call = request.tool_call
        if not _applies(request):
            return await handler(request)
        runtime = request.runtime
        student = getattr(runtime.context, "student_id", None)
        thread = runtime.config.get("configurable", {}).get("thread_id")
        call_id = call.get("id")
        if not student or not thread or not call_id or runtime.store is None:
            raise ValueError("Assessment persistence requires a student, thread, task ID and store")
        raw = call["args"].get("description")
        task = UCAInput.model_validate_json(raw) if isinstance(raw, str) else UCAInput.model_validate(raw)
        concept = student_model.normalize_concept(task.concept)
        if not concept:
            raise ValueError("Assessment concept must not be empty")
        conversation = [Message.model_validate(message) for message in request.state.get("conversation", [])]
        turn = sum(message.role == "student" for message in conversation)
        if not turn:
            raise ValueError("Assessment requires the current student conversation")
        latest = next((message for message in reversed(request.state.get("messages", []))
                       if isinstance(message, HumanMessage)), None)
        fingerprint = _digest({"input": task.model_dump(mode="json"),
                               "conversation": [message.model_dump() for message in conversation],
                               "student_message_id": latest.id if latest else None})
        receipt_namespace = ("students", student, "assessment_receipts")
        receipt_key = _digest({"thread": thread, "task_call_id": call_id})
        # A student-level lock also protects accidental reuse of one task ID for
        # two different concepts in a parallel batch. Other students can proceed.
        lock = _LOCKS.setdefault(runtime.store, {}).setdefault(student, asyncio.Lock())
        async with lock:
            prior = await student_model.load_entry(runtime.store, student, concept)
            receipt = await runtime.store.aget(receipt_namespace, receipt_key)
            if receipt is not None:
                saved = receipt.value
                if saved.get("version") != 1:
                    raise ValueError("Unsupported assessment receipt version")
                if saved.get("input_sha256") != fingerprint or saved.get("concept") != concept:
                    raise ValueError("Assessment task identity was reused with different input")
                if _entry_json(prior) != saved.get("entry"):
                    raise ValueError("Assessment replay is stale; a newer assessment exists")
                output = UCAOutput.model_validate(saved["output"])
                if (output.concept != concept or prior is None
                        or any(getattr(output, field) != getattr(prior, field)
                               for field in ("tier", "confidence", "rationale"))):
                    raise ValueError("Assessment receipt output does not match its saved entry")
                return ToolMessage(content=output.model_dump_json(), tool_call_id=call_id, name="task")
            if prior is not None and prior.assessed_at_turn > turn:
                raise ValueError("Assessment task is stale relative to a newer student turn")

            # The UCA still fetches this prior and retrieves evidence normally.
            # Its completion guard must reject truncated/failed/pending tools
            # before DeepAgents serializes the child into the task ToolMessage.
            result = await handler(request)
            message = _result_message(result, call_id)
            output = UCAOutput.model_validate_json(message.content)
            if student_model.normalize_concept(output.concept) != concept:
                raise ValueError("Assessment result concept does not match its task input")
            if output.prior_tier != (prior.tier if prior else None):
                raise ValueError("Assessment result does not match the current prior tier")
            if not output.rationale.strip():
                raise ValueError("Assessment rationale must not be empty")
            if (output.answer_judgment is not None) != (task.answer_submission is not None):
                raise ValueError("Assessment judgment does not match the answer submission")
            if await student_model.load_entry(runtime.store, student, concept) != prior:
                raise ValueError("Assessment prior changed during execution; result is stale")
            output = output.model_copy(update={"concept": concept})
            entry = StudentModelEntry(
                concept=concept, tier=output.tier, confidence=output.confidence, rationale=output.rationale,
                assessed_at=datetime.now(timezone.utc), assessed_at_turn=turn,
                assessment_count=prior.assessment_count + 1 if prior else 1,
            )
            receipt = {"version": 1, "concept": concept, "input_sha256": fingerprint,
                       "output": output.model_dump(mode="json"), "entry": _entry_json(entry)}
            await runtime.store.abatch([
                PutOp(student_model.namespace(student), concept, _entry_json(entry), index=False),
                PutOp(receipt_namespace, receipt_key, receipt, index=False),
            ])
            canonical = message.model_copy(update={"content": output.model_dump_json()})
            return replace(result, update={**result.update, "messages": [canonical]}) if isinstance(result, Command) else canonical


def assessment_prompt(prompt):
    """Keep the baseline prompt exactly intact while the comparison flag is off."""
    if not model_config.DETERMINISTIC_ASSESSMENT_SAVE:
        return prompt
    replacements = {
        '- **`update_student_model(concept, tier, confidence, rationale)`** — saves your assessment, replacing the previous entry. Pass the same `tier`, `confidence`, and `rationale` you return in your output. The time and turn are recorded automatically.':
        'Your validated final `UCAOutput` is saved by application code. There is no write tool; return the assessment once.',
        'You are the **only** agent that writes to the student model. Call `update_student_model` exactly once per assessment, after you decide on an estimate. If the tier and confidence are unchanged, still call it: that records the new assessment turn.':
        'You are the sole assessment author. Code saves the exact final tier, confidence and rationale, including unchanged estimates, and records the time and turn.',
        '8. **Write the student model** by calling `update_student_model`, then return your output.':
        '8. **Return your assessment** as one final `UCAOutput` after all evidence tools finish. Application code validates and saves it.',
        '- While probing, still call `update_student_model` with a provisional entry and confidence `low`.':
        '- While probing, return a provisional estimate with confidence `low`; application code saves it.',
    }
    for old, new in replacements.items():
        if prompt.count(old) != 1:
            raise ValueError("UCA persistence prompt changed; update its deterministic-save instruction mapping")
        prompt = prompt.replace(old, new)
    return prompt

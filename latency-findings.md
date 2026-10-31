# Chat latency: where the time goes and why

Measured 2026-10-25 on the lab Spark (Flash-Next NVFP4, SGLang 0.5.21, MTP on, thinking off, 20 Mamba
states, 2,048-token prefill chunks). Commit `c5eda83` plus the uncommitted edits to `service.py`,
`chainlit_app.py` and `design-doc.md`. All `model_config.py` flags at their current values.

## Update: suggestions 1, 3 and 4 implemented

### What changed

**1. Direct delivery after an ungraded assessment** (`middleware/direct_content.py`)
- `DirectContentMiddleware` now also delivers the CGA's content directly when every earlier `task` this
  turn is a successful UCA assessment that graded no answer: no `question_id` in its input and no
  `answer_judgment` in its output.
- Graded answer turns still get the parent's synthesis, because the UCA's verdict is never passed to the
  CGA and the feedback would otherwise ignore it. Any failed, unknown or earlier CGA task also falls back
  to synthesis, as before.
- The two sentences in `prompts/orchestrator_prompt.md` that describe direct delivery were updated to
  match.

**2. Parent tools left unchanged after assessment** (`middleware/content_after_assessment.py`)
- `RequireContentAfterAssessment` no longer replaces the parent's tools with a narrowed `task` tool. It
  keeps every advertised tool and sets `tool_choice="required"` (with `parallel_tool_calls` still off).
- A named `tool_choice` would not have been enough. Replaying a captured request showed SGLang renders
  only the named tool, which shrinks the prompt from 9,199 to 7,400 tokens and breaks the prefix just the
  same. `"required"` keeps the full 9,199-token rendering.
- `_check` still rejects a text reply, a UCA call, a wrong-concept call or parallel calls. Because
  `"required"` also allows lookup tools, up to two read-only lookups (`search_markdown_sources`,
  `fetch_student_data`, `fetch_recent_questions`) are let through before the CGA call. A third fails the
  turn.
- Trade-off: the grammar no longer *prevents* a UCA call here. A misroute now fails the turn closed, with
  no output leaked, where before it couldn't be generated at all. None occurred in the 24 measured turns
  below.

**3. `prior_questions` hidden from the parent** (`middleware/validate_input.py`)
- The typed `task` schema advertised to the parent no longer contains `prior_questions`.
- Any value the parent sends anyway (for example on the legacy string schema used with Ollama) is dropped
  before validation. `QuestionLogMiddleware` therefore always fills the field from the log.

**Tests.** The tests that asserted the narrowed descriptor, the named `tool_choice` or a parent rewrite
after an ungraded assessment were updated. New tests cover:
- the lookup allowance and its cap
- direct delivery after an ungraded assessment
- fallback to synthesis for a graded, answered or failed assessment
- `prior_questions` absent from the schema and dropped at dispatch

`uv run python -m unittest discover -s tests`: **199 tests, OK** (196 before).

### Re-measured results

Same harness and server as below. Two captures were run:
- the same 4-turn conversation (1 warmup, 3 measured)
- a 2-turn conversation ("Explain information hiding…", then "So information hiding just means making all
  the fields private, right?") built to trigger an ungraded assessment, which the 4-turn rerun never
  produced

Every turn succeeded: 16/16 and 8/8.

**Per-change evidence (like-for-like calls):**

| | Before | After |
|---|---|---|
| Parent call after the UCA returns | Fully uncached in 7 of 11 (5.1–6.7 s, one at 17.6 s); 82–87% cached in the other 4 (2.5–2.8 s). Shares 32 to ~9.3k tokens with earlier parent requests | 97–98% cached in 7 of 7; 1.9–2.1 s. Shares 9.0–11.8k tokens with the previous parent request |
| Parent rewrite after an ungraded assessment | Always present: 5.2–13.5 s in measured turns (mean 9.6 s) | **None.** All 3 ungraded turns ended at the CGA output |
| Parent `task` calls carrying `prior_questions` | 4 of the run's `generate_question` calls set it: 3 as an empty list (79 tokens each), 1 copying a full question and rubric (516 tokens, 17.6 s) | 0; the field is no longer in the schema |

On a turn with an ungraded assessment, that adds up to roughly **12 s saved**: about 9.6 s for the
rewrite and about 2 s for the cached post-UCA call. On a graded answer turn the saving is the cached
post-UCA call (about 2 s, more when it would have missed). The synthesis call remains.

**End-to-end turn times (median of 3 measured):**

| Turn | Before | After |
|---|---|---|
| Explanation | 32.0 s | 28.9 s |
| Follow-up | 67.7 s | 32.3 s |
| Practice question | 56.6 s | 41.5 s |
| Student answer | 63.1 s | 32.1 s |

**Most of this end-to-end drop is not from the three changes.** The parent's routing changed. Before, 7
of 8 measured follow-up and practice turns called the UCA; after, none did. That knocked on to the
answer turn: the concept now had no prior assessment, so the UCA started cold and the CGA ran a short
`probe_at_tier` instead of a full explanation.

Replaying the old run's UCA-routing decisions at temperature 0 showed the decision is fragile. 2 of 4
decision points flipped to the CGA: one with either the new prompt or the new schema alone, the other only
with both together. Treat the end-to-end table as confounded, and the per-change table as the evidence
for these changes.

The fragility is a finding in its own right. Whether a turn is assessed (about 20–30 s, and a
research-relevant event) flips on small, unrelated edits to the prompt and schema. It's worth a
dedicated routing evaluation.

## Method

- **Conversation.** Each run is a 4-turn student conversation through the real `service.chat_turn()`, with
  disposable student state (the `scripts/profile_agent.py` harness). One warmup plus 3 measured
  repetitions, giving 16 turns and 126 model requests. The turns:
  1. explanation: "Explain information hiding… Keep it concise."
  2. follow-up: "I don't get why clients wouldn't break… show a tiny concrete example?"
  3. practice question
  4. student answer
- **Capture.** Every chat-completions HTTP payload and response was recorded via an httpx hook, including
  server-reported `cached_tokens` and MTP acceptance stats.
- **Prefix analysis.** Each payload was rendered with the model's own chat template and tokenizer.
  For every request I computed the longest token prefix it shares with any earlier request, and decoded
  the text at the divergence point. The local count is a constant 60–80 tokens below the server's (the
  tools block renders slightly differently), so divergence positions are offset by that amount.
- Scripts and raw data are in the session scratchpad (`capture.py`, `analyze.py`, `capture1.json`,
  `rows1.json`) and are not committed.

**Caveats**
- The SGLang server is shared: it runs under another user account (`duerschmid`), so other traffic may
  have affected timing and cache eviction during the run. I could not check this.
- Three repetitions of one scripted conversation. Agent paths vary between runs (practice rep 3 skipped
  the UCA).
- I did not evaluate quality. The savings below are arithmetic from the trace, not measured
  before-and-after results.

## Results

| Turn | Total seconds (3 measured) | Model calls |
|---|---|---|
| Explanation | 29.3, 38.6, 32.0 | 4–5 |
| Follow-up | 69.2, 66.4, 67.7 | 9–10 |
| Practice question | 56.6, 59.2, 37.5 | 5–10 |
| Student answer | 40.8, 63.1, 87.8 | 8–9 |

Time by call type across the 12 measured turns (648 s total). Tool execution and framework overhead
together are about 2%. Everything else is model generation.

| Call type | Seconds | Share | Calls | Output tokens |
|---|---|---|---|---|
| CGA content (`CGAOutput`) | 292.7 | 45.2% | 12 | 8,679 |
| Tool-call-only calls (parent, UCA, CGA) | 188.0 | 29.0% | 65 | 3,571 |
| UCA assessment (`UCAOutput`) | 77.8 | 12.0% | 8 | 2,030 |
| Parent final rewrite (after UCA then CGA) | 75.7 | 11.7% | 8 | 2,470 |

Throughput was 29 tok/s for the CGA's JSON output, 26 for the UCA's and 31.5 for the parent's plain
text. MTP mean accepted length was 3.06, 2.91 and 3.91 respectively.

Time is spent in two ways: generating tokens that don't need to be generated, and calls whose only job
is to emit one tool call (median 2.0 s when cached, 3.9 s when not). The sections below take each
in turn.

## Root causes

### 1. The parent regenerates the CGA's text after an assessment (11.7% of time)

`DirectContentMiddleware` only skips the parent's final generation when the turn contains exactly one
`task` call (`direct_content.py`). Any turn that runs the UCA first therefore ends with the parent
writing the reply again.

Compared against the CGA content it received, that rewrite had a similarity ratio of **0.82–1.00**.
Four of eleven were verbatim copies (requests #47, #65, #78 and #97). The rest added an opening line
like "Here's your question:" or lightly reworded the text. Each rewrite cost 3.2–15.9 s.

### 2. The CGA writes long `sources` strings nobody reads (≈40% of CGA output tokens)

Across 12 `CGAOutput` calls the output tokens split as:
- `content` (student-visible): 4,917
- `sources`: 3,479
- `rubric`: 1,451 (needed later for grading)

Each source is a breadcrumb plus a full GitHub URL with a 40-character commit hash, which is copied
from the search result (the prompt says "Preserve returned source URLs exactly, including revision
hashes"). The only consumer in code is the non-empty check at `direct_content.py:86`. The student never
sees them.

At about 29 tok/s, that's roughly 10 s per CGA call. Hash-like strings also tokenize poorly, which
likely lowers MTP acceptance, though I didn't isolate that.

### 3. Delegation-only calls: many serial calls, ~2–4 s each (29% of time)

The flow per turn is:
- **Parent:** `fetch_student_data` or `fetch_recent_questions`, then `task`
- **UCA:** `fetch_student_data`, then `search_markdown_sources`, then `UCAOutput`
- **CGA:** 1–3 searches, then `CGAOutput`

Every arrow is a separate model call because of `SERIAL_CHILD_TOOL_CALLS`. Each call's output is only
30–70 tokens, so its cost is almost entirely the fixed per-request cost of prefilling a 5–13k-token
prompt.

Specific waste:
- **CGA re-searches even when evidence is supplied.** In 4 of 4 explanation turns the parent searched
  first and passed `course_evidence`, and the CGA searched again anyway (#3, #36, #68, #100). Its prompt
  allows this ("search for missing evidence"), and it treats every paraphrase as missing.
- **The UCA's first call is always `fetch_student_data`.** This is a deterministic lookup the code could
  do itself. `PREFETCH_ASSESSMENT_PRIOR` is off because the earlier variant put the prior in a human
  message, which hurt calibration (see `docs/dgx-spark.md`).

### 4. A tool-list swap invalidates the parent's whole prompt cache

After the UCA returns, `RequireContentAfterAssessment` (`content_after_assessment.py:127`) replaces the
parent's 8 tools with a single rewritten `task` tool. Its description embeds the concept name.

Qwen's chat template renders tools at the **start** of the system message, so this request diverges
from every earlier parent request at **token 32**. That is the whole ~7–10k-token prompt. The decoded
divergence for #10 shows `{"name": "task", "description": "Generate student-facing content for assessed
concept \"information-hiding\"…` where earlier requests have `{"name": "ls", …`.

These calls took 5.1–6.7 s uncached against 2.5–2.8 s when a later turn happened to reuse the same
restricted prefix (#53, #62, #84, #93). Since `tool_choice` already forces `task` and `_check` already
validates the subagent and concept, swapping the tool list is what breaks the cache, and it isn't needed
to enforce the constraint.

### 5. Hybrid-model prefix cache: matching prefixes still miss

Flash-Next is a hybrid model with recurrent (Mamba-style) layers. Reusing a prefix needs a saved
recurrent state at the matched position, not just KV entries, and the server keeps 20. Two patterns in
the trace follow from this.

**a. Exact extensions get evicted.** The final parent rewrites #111 and #125, plus #14, #24 and #32 in
the warmup, extend an earlier parent request token for token. The divergence text is exactly the earlier
request's `<|im_start|>assistant\n<think>\n\n</think>\n\n` generation prompt. They still reported no
cached tokens.

Between the two parent calls, 7–8 other requests ran on three other prompt branches: the UCA, the
restricted parent and the CGA. That's enough to evict the parent's state at least some of the time.
The same pattern got cached in other repetitions (#47, #57, #78, #88, #97), so the eviction is
intermittent. Missed rewrites ran at 20–27 tok/s against 34–40 when cached, which is 4–5 s lost each.

**b. Shared static prefixes get no partial reuse.** Each child's first call matches the previous call of
the same child for 4.8–5.3k tokens: system prompt plus tools, up to where the conversation history
starts. Most still get 0 cached tokens (#40, #72, #103 UCA; #44, #76, #107 CGA). When they do hit, the
cached count is a page-aligned checkpoint below the match (2048, 4096, 4800), so a state existed only
when an earlier request happened to save one at a compatible position.

The parent's first call on a new conversation (#66, #98) missed its 6.9k-token static prefix the same
way. Overall, 19 tool-call-only calls were uncached, and they cost about 40 s more than cached calls
would have.

### 6. The parent copies question logs into the CGA input

In #121 the parent generated 516 tokens (17.6 s) because it wrote `prior_questions`, including the full
earlier question and its private **rubric**, into the CGA's input. `QuestionLogMiddleware` already fills
`prior_questions` from the log, but only when the field is empty (`question_log.py:56`). The parent's
copy therefore displaces the code path, and puts the rubric through the parent's own generation, which
the middleware's header comment says should not happen.

The 86 s answer turn in the earlier quick profile has the same shape: right after the UCA, an uncached
parent tool call generated 515 tokens in 16.5 s. Its payload wasn't captured, so the content isn't
confirmed.

### 7. Routing: assessment on follow-ups and practice requests adds ~20–30 s

The UCA path costs 3 UCA calls, the restricted parent call and the final rewrite. The same practice
request took 37.5 s without the UCA and 56.6–59.2 s with it. Whether a clarification or a practice
request should trigger an assessment is a study-design decision, not a performance bug. It's listed
here only because it's the largest single routing cost.

## Suggestions

Estimates are per affected turn, from the trace above. All of these need a check against the
tutoring-quality evaluation before adoption.

| # | Change | Fixes cause | Est. saving | Risk / notes |
|---|---|---|---|---|
| 1 | **Implemented** (ungraded assessments only; see the update above). Allow direct CGA delivery when the only earlier `task` this turn is a successful UCA | 1 | 3–16 s (≈9.5 s avg) per UCA turn; also removes the most-evicted request | UCA output is private, and the CGA already receives the conversation. Keep the fallback to synthesis on any error |
| 2 | Have the CGA emit short source IDs (e.g. chunk numbers from the search result) and expand them to titles and URLs in middleware from the actual tool results | 2 | ~290 tokens ≈ 10 s per CGA call | More exact than copying hashes, since code fills them. The `direct_content` check moves to the IDs |
| 3 | **Implemented** (with `tool_choice="required"`, since a named choice also changes the prompt). Keep the parent's tools unchanged after assessment; enforce with `tool_choice` plus the existing `_check` | 4, 5a | ~3 s per UCA turn, and one fewer cache branch | `_check` already rejects a non-CGA or wrong-concept task |
| 4 | **Implemented.** Hide `prior_questions` from the parent-facing task schema so `QuestionLogMiddleware` always fills it | 6 | Up to ~15 s in turns where the parent copies it; removes rubric copying | Small schema change. Middleware already implements the fill |
| 5 | Code-owned prefetch that writes a synthetic tool call plus result (identical to what the model would produce) before the child's first generation: UCA `fetch_student_data`, CGA's first search | 3 | ~2 s per eliminated call (2–3 per UCA+CGA turn) | Different from the rejected variant: the transcript keeps the tool-result form, so the calibration concern should not apply, but re-check it |
| 6 | Tell the CGA to skip searching when supplied `course_evidence` covers the concept, or skip the parent's search and let only the CGA search | 3 | ~2–4 s per explanation turn | Grounding quality. Measure search-count and coverage-gap rates |
| 7 | Remove `ls`, `read_file`, `glob` and `grep` from the UCA and CGA (and `ls`, `glob` and `grep` from the parent) | 5 | 1,289 tokens (~22%) off each child's static prefix, reducing every uncached prefill | None were called in 126 requests. `docs/dgx-spark.md` says to keep `read_file` where skills or history recovery need it |
| 8 | Raise the Mamba state count beyond 20 (`MAMBA_CACHE_SLOTS_PER_REQUEST`) and re-run this trace; separately, confirm whether other users' traffic shares the server | 5 | Up to ~4–5 s per evicted final call and ~2 s per child first call | Memory: the earlier 10→20 change added ~1 GB of state pool. Fixes 1 and 3 reduce the pressure first |
| 9 | Stream CGA content to the student | (perceived) | First text at ~5–10 s instead of the full turn | Needs the buffered-tool-response parser issue solved, plus streaming the `content` field from partial JSON |
| 10 | Revisit when the parent invokes the UCA (clarifications, practice requests) | 7 | ~20–30 s per avoided assessment | Study-design decision, not an engineering one |

Suggested order: 1, 3 and 4 are now implemented. 2 and 5 are larger but address the two biggest
buckets, CGA output length and tool-call-only calls. Re-run the capture after each, since
removing branches (1, 3) should also reduce the evictions in cause 5a before any server change.

# Course evidence prefetch: tool calls and latency

Measured 2026-11-04 on the lab Spark (Flash-Next NVFP4, SGLang 0.5.21, speculation on, thinking off,
temperature 0). Before: commit `c4f093d`. After: `c4f093d` plus the uncommitted changes below. All other
`model_config.py` flags at their current values.

## Summary

- **Tool calls fell 43% (94 → 54)** and **searches fell 74% (38 → 10)**. The UCA and CGA went from 31
  searches to 1.
- **Model calls fell 27% (117 → 85).**
- **Latency did not change** (570 s → 571 s total, median turn 30.3 s → 31.6 s). Subagents now make half
  as many model calls, but each takes about twice as long, because the supplied evidence makes their
  prompts larger and most of it misses the prompt cache.
- The next step is to shrink the supplied evidence (see "Next steps").

## Why

A traced 6-turn conversation showed the UCA and CGA repeating searches the orchestrator, or each other,
had already made:

- The orchestrator only searched on a new topic. On same-topic turns there was nothing to pass down, so
  both subagents searched again.
- Search results never moved between subagents. Only the orchestrator's own results became
  `course_evidence`, so in an answer turn the UCA searched and the CGA then ran nearly the same query.
- Even when the orchestrator's results were passed down, the CGA usually searched again.
- In the same turn, the orchestrator and the UCA both called `fetch_student_data` for the same concept.

Nothing in code makes the orchestrator search. Only its prompt tells it to (`orchestrator_prompt.md`
constraint 4, its Tools section, and steps 2 and 3).

## What changed

**1. Code searches before each subagent call** (`PrefetchCourseEvidence`, `middleware/course_evidence.py`)
- Before every UCA or CGA `task`, code runs one similarity search and supplies the passages as
  `course_evidence`. The query is the concept plus the student's latest message. For a graded answer, it
  is the logged question and the student's answer.
- It returns 6 chunks (`PREFETCH_CHUNKS`) instead of the tool's 4, since a query built by code is blunter
  than one a model writes.
- It searches at most once per student turn and concept, so a UCA and a CGA in the same turn get the same
  evidence. The orchestrator's own results from the turn are included too.
- It gets its store loader from `edbot_agent`, so the tests that patch `edbot_agent.load_sebook_store`
  also cover it.

**2. Evidence carries across same-concept turns**
- The passages are kept in a private parent state key (`carried_evidence`) until the concept changes.
- The key uses a last-writer-wins reducer, so UCA and CGA tasks in one tool batch can both update it.
- Duplicate chunks are dropped. Everything a subagent receives is capped at 16,000 characters
  (`MAX_SUPPLIED_CHARS`), keeping the newest whole results.

**3. Subagents get one extra search** (`LimitChildSearches`)
- Once evidence has been supplied, a subagent's second search gets a "search limit reached" reply instead
  of results.
- The reply is a normal tool result, not an error. The UCA's completion check treats any tool error as a
  failed assessment.
- The tool itself stays, which keeps the subagent's prompt prefix (and its cache) unchanged.
- The CGA and UCA prompts now say passages are usually supplied, and to search again at most once, only
  for a specific point they don't cover.

**4. `PREFETCH_ASSESSMENT_PRIOR` turned on.** Code reads the UCA's prior assessment, so the UCA no longer
calls `fetch_student_data`.

**Flags:** `PREFETCH_COURSE_EVIDENCE` and `LIMIT_CHILD_SEARCHES` are new, and both are on.
`PREFETCH_ASSESSMENT_PRIOR` is now `True`.

**Prompt file changes**
- `uca_prompt.md` now shows what the UCA reads with the default flags: the prior is supplied by code and
  code saves the result.
- `assessment_prompt` and `tool_prior_prompt` turn the file back into the tool-based wording when a flag
  is off. Under every flag combination, the UCA gets exactly the same prompt as before this change.
- `system_prompt.md` was unused and has been deleted.

**Tests**
- `test_course_evidence.py`: one test now asserts that evidence carries into a later turn on the same
  concept for the same student, and still does not reach another student.
- New `tests/test_evidence_prefetch.py` (9 tests):
  - search once per turn and concept
  - pool reuse within a turn
  - carryover across turns, and reset when the concept changes
  - the query for an answer submission
  - the flag-off path
  - the evidence budget
  - the search limit, including that its refusal isn't a tool error

`.venv/bin/python -m unittest discover -s tests`: **225 tests, OK**.

## Method

- 5 scripted conversations, 19 turns. Topics: information hiding, test doubles, git merge vs rebase,
  observer pattern, TDD.
- Turn types: explanation, follow-up, practice request, answer submission, new topic, off-topic.
- Each condition ran once through `scripts/profile_agent.py`'s `run_profile`, with fresh temporary student
  state per conversation.
- The baseline ran from a clean worktree at `c4f093d`, sharing the SEBook index cache.
- Each tool call was attributed to the agent that made it by following its callback parent chain up to
  the `task` call that started that agent.
- Searches made directly in code (rubric writer, prefetch) were counted by patching
  `InMemoryVectorStore.similarity_search`.
- All 38 turns succeeded.

**Caveats**
- There is one run per condition, and the agents' routing can differ between runs, so single-turn latency
  differences are noisy. Only the totals and the per-agent breakdown are reliable.
- The new unit tests briefly used the embedding server while the baseline was running.
- Answer quality was not measured.

## Results

### Totals

| | Before | After | Change |
|---|---|---|---|
| Tool calls | 94 | 54 | −43% |
| `search_markdown_sources` calls | 38 | 10 | −74% |
| Searches by subagents (UCA + CGA) | 31 | 1 | |
| `fetch_student_data` calls | 22 | 9 | UCA lookups removed |
| `task` calls (subagent runs) | 28 | 31 | routing varies between runs |
| Model calls | 117 | 85 | −27% |
| Searches made in code | 5 (rubric writer) | 23 (18 prefetch, 5 rubric writer) | about 0.2 s each |
| Total latency | 570.2 s | 571.4 s | none |
| Median turn latency | 30.3 s | 31.6 s | none |

The 9 searches the orchestrator still makes are on new topics, where it checks scope and picks a concept.

### Per turn

Search counts are `search_markdown_sources` tool calls.

| Conversation / turn | Latency (s) | Tool calls | Searches | Model calls |
|---|---|---|---|---|
| information-hiding / explanation | 23.1 → 23.7 | 4 → 3 | 2 → 1 | 4 → 4 |
| information-hiding / follow-up | 18.8 → 29.2 | 4 → 3 | 2 → 0 | 4 → 5 |
| information-hiding / practice | 20.5 → 31.8 | 4 → 3 | 2 → 0 | 5 → 5 |
| information-hiding / answer | 45.7 → 49.6 | 6 → 2 | 2 → 0 | 8 → 4 |
| test-doubles / new topic | 24.9 → 31.6 | 6 → 5 | 1 → 1 | 7 → 6 |
| test-doubles / answer | 30.3 → 34.9 | 6 → 3 | 2 → 0 | 8 → 6 |
| test-doubles / follow-up | 32.8 → 33.0 | 5 → 3 | 2 → 1 | 7 → 5 |
| test-doubles / practice | 24.1 → 23.4 | 4 → 1 | 2 → 0 | 5 → 2 |
| git / explanation | 49.2 → 39.7 | 9 → 5 | 4 → 1 | 10 → 6 |
| git / follow-up | 33.8 → 36.4 | 5 → 3 | 1 → 1 | 6 → 5 |
| git / practice | 34.0 → 28.2 | 7 → 3 | 3 → 0 | 9 → 5 |
| git / answer | 42.2 → 39.4 | 4 → 2 | 1 → 0 | 6 → 4 |
| observer / explanation | 33.7 → 20.9 | 6 → 3 | 3 → 1 | 7 → 4 |
| observer / follow-up | 43.3 → 29.3 | 6 → 4 | 3 → 1 | 8 → 6 |
| observer / practice | 24.1 → 22.0 | 4 → 3 | 2 → 1 | 5 → 4 |
| observer / off-topic | 5.7 → 7.1 | 0 → 0 | 0 → 0 | 1 → 1 |
| tdd / explanation | 21.2 → 22.9 | 3 → 3 | 1 → 1 | 3 → 4 |
| tdd / follow-up | 47.3 → 36.5 | 8 → 3 | 4 → 1 | 10 → 5 |
| tdd / practice | 15.5 → 31.8 | 3 → 2 | 1 → 0 | 4 → 4 |

### Median latency by turn type

| Turn type | n | Before (s) | After (s) |
|---|---|---|---|
| explanation | 4 | 28.4 | 23.3 |
| follow-up | 5 | 33.8 | 33.0 |
| practice | 5 | 24.1 | 28.2 |
| answer | 3 | 42.2 | 39.4 |
| new topic | 1 | 24.9 | 31.6 |
| off-topic | 1 | 5.7 | 7.1 |

## Why latency didn't drop

The round trips saved were offset by larger subagent prompts that miss the prompt cache.

| Agent | Model calls | Avg time per call | Avg prompt tokens | Avg cached | Avg output tokens |
|---|---|---|---|---|---|
| Orchestrator | 50 → 52 | 2.71 s → 2.59 s | 9,344 → 9,207 | 8,017 → 7,889 | 62 → 60 |
| CGA | 40 → 19 | 7.06 s → 13.42 s | 6,593 → 8,301 | 4,733 → 3,052 | 175 → 302 |
| UCA | 27 → 14 | 4.73 s → 10.85 s | 6,290 → 8,629 | 4,615 → 2,674 | 111 → 219 |

- **The orchestrator is unaffected.** Its cost per call barely moved.
- **Subagent prompts are uncached.** Uncached prompt tokens across all subagent calls rose from about 119k
  to about 183k:
  - The supplied evidence (up to 16,000 characters, roughly 4k tokens) comes after the conversation in
    each subagent's messages.
  - The conversation changes every turn, so the cache can't reuse the evidence that follows it.
  - The UCA and CGA have different system prompts, so they don't share a cached prefix either.
- **Before, cache reuse looked better than it was.** A subagent's second call reused its first call's
  whole prompt, and search results arrived in smaller pieces (about 1.2k tokens each).
- **Output tokens per call doubled only because there are fewer short calls.** Each subagent call is now
  usually the final answer rather than a short search request. Total output is about the same (CGA ~7.0k →
  ~5.7k, UCA ~3.0k → ~3.1k tokens).
- **The code-side search costs almost nothing:** about 0.2 s per query, 18 times across the run.

## Next steps

1. **Shrink the supplied evidence.** Lower `MAX_SUPPLIED_CHARS` (16,000 → about 6,000–8,000) or
   `PREFETCH_CHUNKS` (6 → 4), then re-run this benchmark. Most of the added prefill comes from this block,
   and it is a one-line change.
2. **Move the evidence before the conversation.** Carried passages from earlier turns would then stay
   cached between turns, with only the conversation and new passages prefilled. This changes the order of
   messages each subagent receives, and some existing tests check that order.
3. **Measure answer quality.** Subagents now write from passages chosen by code instead of their own
   searches. Run `scripts/evaluate_tutoring.py` and `scripts/evaluate_assessment.py` before and after to
   check that answers aren't worse.
4. **Run more than once per condition** before drawing per-turn conclusions.

## Related: design doc out of date

Reviewing the code for this change showed several statements in `design-doc.md` that no longer match the
implementation. `TODO(design-doc)` comments now sit under each one. The largest:

- No control/experimental condition flag exists in code.
- Escalation and research logging exist only as prompt instructions.
- Subagents see raw student text and the full conversation, not the last 3 exchanges.
- Code, not agents, writes the student model and question log.
- The CGA no longer writes rubrics.
- There is no concept taxonomy.
- The doc has no section on retrieval.

## Reproducing

The benchmark scripts are not committed. They are in the session scratchpad:

- `bench.py <edbot root> <output.json>` runs the 5 conversations and attributes each tool call to its
  agent.
- `compare.py <before.json> <after.json>` prints the tables above.

To rerun them later, add them to `scripts/`.

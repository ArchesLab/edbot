# Tutoring candidate v2: semantic review of an incomplete run

This candidate is **not accepted for tutoring quality**. The practice item's private
rubric still rejects a valid implementation, and the parent supplies the selected
Socratic exercise's answer under pressure. Two other turns fail before producing
a complete reply. The shorter recorded run is not a nine-turn speedup.

This is an agent review of synthetic transcripts, retrieved passages, actual
requests, tool results, and stored assessment state. It is not evidence of
learning, retention, transfer, accessibility conformance, or an accurate Bloom
classifier. The report's machine-readable `quality` remains `not_reviewed`; this
document records semantic judgments rather than an automated quality score.

## Evidence identity and scope

- Report: `output/profiling/tutoring-candidate-v2.json`
- SHA-256: `f7041f2329432ce7f4cc8a71af81f3ff10a990b1df4d7c90b572ef5fa5ccd8fb`
- Recorded interval: `2026-10-18T10:47:32.259847+00:00` to
  `2026-10-18T10:52:26.500849+00:00`.
- Six fixed synthetic episodes, one repetition, nine expected turns; eight
  attempted, six successful, two failed, one unattempted. Overall execution is
  `failed`.
- Model: `Qwen3.8-Flash-Next-FP4-Local`, model revision
  `fc694b54fb0174e0913e6adf86691ef85a4ead47`; temperature 0, thinking false,
  context 32768, maximum output 4096. Direct content delivery, reduced tutor
  harness, and course-evidence reuse are enabled in the recorded configuration.
- Retrieved course revision: `24db6bf0d4e4ebfa1331e6c772e1844cbaf2d9aa`.
- Tutoring fixture SHA-256:
  `dfb46e5ee98faa1ff1fa20e55a6d6331a6295e51e0b6b137a2c09b7a23e85649`.

Locators below are zero-based JSON paths. `C[n]` means `cases[n]`, `T[n]` means
`profile.turns[n]`, and `O[n]` means `observations[n]` within that case. Structured
CGA/UCA results are JSON strings in checkpoint tool messages: parse their
`content` to inspect the named field. Repeated checkpoint histories are not new
responses or new assessments. Word counts use whitespace splitting and are
descriptive checks, not measures of learning quality.

The manifest captures the source actually used. Relevant SHA-256 values are:

| Source | SHA-256 |
| --- | --- |
| `src/edbot/prompts/cga_prompt.md` | `d791863e2ff712d8830d2be9bfce53ecad63e6cd751043e612c240db3029be85` |
| `src/edbot/prompts/orchestrator_prompt.md` | `fb52f4f03feb8ca267b59b16a2e0b3fe91c85bb7fe6d7ac2d9f22f4e25919bbf` |
| `src/edbot/prompts/uca_prompt.md` | `dc3ccbf9079a8000e2d4d520cf7ebf2d65ae4c5866e8564660d7ab6731bbea31` |
| `src/edbot/middleware/conversation_history.py` | `cbdcd33608d79c0a345fdabf9c75f269f06afce44c9f5a699a25e0acd2a0c25b` |
| `src/edbot/middleware/course_evidence.py` | `cfaad055d47f77ca810e12bc3a5f02d32b394aec76c1db7c75772d3936b5c557` |

These five local files matched the report hashes at review time. Later edits or
runs need their own evidence identity.

## Case judgments

| Episode | Judgment | Main evidence |
| --- | --- | --- |
| Concise explanation | Revise | Bounds test evidence correctly, but 233 words exceeds the explicit 120-word CGA limit; intentional ordering is treated as a leak. |
| Single practice question | Critical private-rubric defect | Withholds the answer, but requires changing a public tuple-list contract that a dictionary-backed implementation can preserve. |
| Defensive Map copy | Revise for accuracy and source applicability | Accepts the valid proposal; incorrectly limits container isolation to primitives and mixes language-specific APIs. |
| Selected Socratic pressure | Critical contract failure | Parent directly gives the verdict and fix approach; no CGA task occurs on the pressure turn. |
| Missing prerequisite | Revise first reply; follow-up unassessable | Relevant prerequisite support still asks a compound terminology question; requested support change fails before a reply. |
| Spanish and stopping | Execution failure; stop untested | No complete Spanish reply; the stop message is never submitted. |

### 0. Concise explanation

The final reply and raw CGA `content` are identical:
`C[0].T[0].response` and `C[0].O[0].messages[7].content` → `content`.
There is no parent rewrite concealing child verbosity.

The answer correctly says passing tests are “evidence for the cases those tests
exercise, not proof that nothing leaks” and “A failure does not automatically
mean a leak either.” This repairs the earlier failure-implies-leak error. The
retrieved `Test Quality > Oracle Strength` passage is actually present at
`C[0].T[0].metrics.tools[2].output`, Chunk 2. Citations retain the retrieved
revision URLs.

However, the 233-word reply is two long paragraphs rather than two short ones.
The actual CGA system message, `C[0].T[0].metrics.model_calls[3].input_messages[0][0]`,
requires “For a concise explanation, use at most 120 words.” The bound is not
merely a proposed future prompt.

Two claims overgeneralize the source:

> if more than that module needs edits, the secret leaked.

> promises insertion order leaks storage/format/ordering decisions

Changing an intentional public behavior can require client changes without
revealing a private implementation choice. Likewise, an intentional order can
be maintained across storage implementations. The answer needs to distinguish
an accidental dependence on storage order from a promised domain order. Its own
`all_ids() -> list[str]` example already relies on a public collection contract.

The source boundary is material. `C[0].T[0].metrics.tools[1].output`, Chunk 2,
contains the broad five-step diagnostics; Chunk 3 also says public guarantees
should expose “stable, intentional information only.” The reply repeats the
strong diagnostic without applying that qualification. This is more than an
absent citation. A shorter answer should keep the contract distinction and
bounded test claim, dropping the extra leak checklist.

### 1. Single practice question

The 72-word visible question gives one decision and a reason and withholds its
answer. It states that storage changes from a list of tuples to a dictionary
keyed by student ID, while the public signature is
`get_all_records() -> list[tuple[int, str, float]]`. The tuple is explicitly
student ID, name, and GPA. See `C[1].T[0].response`.

The private rubric at `C[1].O[0].messages[5].content` → `rubric` says:

> Correct: The team must change (or has effectively already leaked, so must redesign) the public interface

and:

> Incorrect: Claims the module can switch storage freely with no interface impact

The asserted necessity is false under the question's premises. A dictionary
mapping IDs to name/GPA can return a newly constructed list of the same public
tuples. The question states neither an alias to the internal collection nor an
ordering promise that the dictionary-backed implementation cannot preserve.
For example, `(student_id, name, gpa)` can be constructed from each dictionary
entry without exposing that dictionary to callers. A domain-shaped tuple is not
automatically a raw storage row.

The rubric also rejects claiming clients must change “merely because the
internal container type changed, without identifying the public guarantee that
changes.” That caveat contradicts its own gold answer: the stem identifies no
public guarantee that must change. “What is the one decision” leaves the choice
under-specified and does not rescue the gold boundary.

The 197-word rubric exceeds the prompt's normal 150-word guidance, but that is
secondary to its incorrect decision boundary. The actual CGA request explicitly
contains the new rule to try a same-signature adapter or snapshot before marking
it wrong: `C[1].T[0].metrics.model_calls[2].input_messages[0][0]`. More of the same
instruction is not demonstrated to repair the behavior.

The source was handed over verbatim in that request's message `[2]`, and the
child made no search call. It contains the five-step rule, the leaky
`load_users_sorted_by_internal_id()` example, and the wall-outlet example of a
stable interface across implementation changes. Those examples do not establish
that every returned tuple/list or every changed backing collection forces a
public redesign. Exact source URLs are preserved in the structured result.

This is an observed invalid grading artifact, not an observed student misgrade:
no answer was submitted and no UCA assessment was stored. The repair must make
the question and rubric agree on the public promise. Either accept a
contract-preserving snapshot/adapter, or specify a concrete leak and ask a
decision whose required change follows from it. An instructor-checked
counterexample should be part of acceptance, rather than treating a generated
rubric as its own correctness oracle.

### 2. Defensive Map copy

The final/raw child content at `C[2].T[0].response` and
`C[2].O[0].messages[5].content` → `content` begins:

> Yes — under the contract as you stated it, `return new Map(internalBalances);` satisfies it.

Accepting the stated valid alternative is a retained improvement over baseline.
It correctly distinguishes a snapshot from a live view and warns that shallow
copies can share nested mutable objects. However, it says:

> Your isolation claim only holds because the values are primitive numbers

The learner expressly claims container addition/deletion isolation, not nested
object isolation. A new Map container still isolates additions/deletions when
values are objects; only mutation of shared referenced objects has that extra
limitation. The final recap says “container mutation” again, so the earlier
restriction is not a clear change of scope.

The reply also introduces `put`/`remove`, a “public `Map` interface type,” and
“HashMap vs TreeMap” while discussing `new Map(internalBalances)`. The fixture
does not explicitly name a language. Under its natural JavaScript reading,
`Map` uses `set`/`delete`; Java's interface/implementation example is not that
constructor's type model. If language is uncertain, the tutor should state its
assumption or qualify its conclusion rather than combine incompatible APIs.

A local Node check during review confirmed that `put`/`remove` are undefined,
`set`/`delete` exist, a copied Map's additions/deletions leave the original
container unchanged for both primitive and object values, and nested objects
remain shared. This is a narrow behavior check, not a proof about every copy or
learner outcome. It corroborates the constructive counterexample to the
primitive-only claim.

The retrieval trace explains an applicability risk: `C[2].T[0].metrics.tools[3]`
returns Java collections passages, and tool `[4]` returns Python shallow/deep
copy passages. The sources support those languages' examples and the general
aliasing distinction; they do not establish JavaScript-specific API facts.
The result keeps their revision URLs but reports `coverage_gap: null`, despite
the actual CGA system rule requiring a conditional answer and missing-support
notice when retrieved sources do not establish language-specific behavior.
It even describes defensive copying as “exactly the fix” a passage prescribes
when that anti-pattern passage actually names an immutable view.

The answer should preserve the accepted solution and separate container
identity, nested aliases, public contract, and language-specific operations.
It need not broaden a 295-word reply with Java and Python implementation detail.

### 3. Selected Socratic help and pressure

The first reply, `C[3].T[0].response`, asks the learner to trace what a caller
would need to do after a storage change. It does not state the conclusion or
provide replacement code. It is 67 words and asks two linked operations: trace
the caller and infer what that means about `private`. This is a useful direction
but can be narrowed to one observable prediction. The raw CGA result is at
`C[3].O[0].messages[6]`; the parent rewrites it slightly in message `[9]` after
assessment. Direct forwarding is not universal in this run.

The pressure turn asks for the complete answer or a disguised solved example.
The final reply claims it will not hand over the fix, then says:

> **Verdict:** No. `private` on the field doesn't preserve the abstraction if a public method hands back `internalRecords` itself.

It continues:

> the routine is to stop returning the internal type at all — return domain objects (or expose a domain operation) instead of the raw records.

These supply the exercise's requested conclusion and replacement approach.
Omitting the return statement does not preserve the selected no-answer
contract. The subsequent request to name a type and describe a caller cannot
undo that disclosure. Exact locator: `C[3].O[1].messages[14].content`, also
`C[3].T[1].response`.

This failure occurs in the **parent's own answer path**. The pressure turn has
five model calls with inferred roles parent, UCA, UCA, UCA, parent. Its only
`task` invocation is UCA (`C[3].T[1].metrics.tools[0]`); there is no CGA task.
The final parent request is `metrics.model_calls[4]`, request SHA-256
`bb3e85c66adaf55e21792497108b02f20df32b03ac3bcffb68ac2588bd9ca993`.
Thus improving only the child prompt cannot enforce the contract on this path.
The parent system's existing division of responsibilities also says CS content
belongs to CGA. The repair needs to cover every student-facing output path and
preserve the already selected mode, including after UCA and tool recovery.

The fix advice again overstates a source pattern: copying can satisfy an
appropriate public snapshot contract without changing the public type. In this
episode the original task gives no concrete return type or deep-copy promise.
The tutor should elicit what callers can observe, not choose one replacement
type before that evidence is available.

### 4. Missing prerequisite and requested support change

The first reply (`C[4].T[0].response`, raw CGA in `O[0].messages[6]`) acknowledges
the gap, defines interface/implementation, and supplies a wall-outlet analogy.
It is 105 words, stays on the prerequisite, and avoids solving the student's
original information-hiding exercise. Limited prerequisite explanation is
legitimate scaffolding; explanation alone is not an answer leak.

Its final demand is nevertheless poorly matched to the stated novice:

> which of those two sides is the *interface*, and why do you think the course calls it "permission to assume"?

This combines identification with an explanation of another unexplained phrase.
The analogy also adds voltage/frequency terminology. A smaller support step
would ask for one familiar observable action or choice and check it before
requiring the abstract label or rationale. This is a support-quality revision,
not evidence that the learner learned nothing. The source analogy is actually
present in `C[4].T[0].metrics.tools[0].output`, Chunk 3. The result cites correct
path/section names but omits the available URLs.

On the follow-up, the learner explicitly says they still cannot answer and
requests different support. The parent changes the internal request from
`probe_at_tier`/`Understand` to `explain_at_tier`/`Remember` for
`information-hiding-interface`; see `C[4].T[1].metrics.tools[1].input`.
That is evidence of changed routing, not evidence of improved instruction.
The child performs searches, then the task fails with:

> ValueError: Content generation returned an invalid tool call; no complete reply is available

The exact error is `C[4].T[1].metrics.tools[1].error`. The final response is empty
and `success` is false. The checkpoint retains the earlier reply and current
task request, not a complete new CGA reply. The actual failed-child input does
include the old student request, prior assistant response, and new support
request in their proper chronological roles. This failure cannot be attributed
to a missing follow-up message, and its unseen content cannot be graded.
Both assessment snapshots are empty.

### 5. Spanish accessibility and stop

The first Spanish turn fails with the same invalid-tool-call error at
`C[5].T[0].metrics.tools[5].error`; `response` is empty and `success` is false.
The student message is present in the CGA's human context, but no complete
Spanish question reaches the checkpoint. Language adherence and question
quality are consequently unassessable, not passed.

The episode expects two turns but its profile contains only one. The stop
message in `C[5].case.turns[1]` was **not attempted**. Earlier runs' stop behavior
does not certify this candidate. A successful rerun must include both a usable
Spanish reply and the explicit stop, with no resumed teaching afterward.

An assessment was persisted before the content-generation failure. A failed
reply therefore does not imply an untouched student store; this is relevant to
safe retry behavior, discussed below.

## Actual assessment and failure state

There are three real UCA writes: Socratic select, Socratic pressure, and the
failed Spanish first turn. All store `Understand` with low confidence. The
other four episodes have empty assessment state. This is insufficient evidence
to certify assessment quality for the entire tutor, and no study condition can
be inferred from these routes.

| Turn | Returned UCA result | Stored state | Review |
| --- | --- | --- | --- |
| Socratic select | `C[3].O[0].messages[8]` | `O[0].assessment_state["information-hiding"]` | Recognizes the visibility misconception and labels the estimate provisional. Connecting the topic to a visibility word is not demonstrated conceptual understanding. |
| Socratic pressure | `C[3].O[1].messages[12]` | `O[1].assessment_state["information-hiding"]` | Correctly identifies no new reasoning evidence and carries prior tier/confidence. It inaccurately says the student “reiterated” the misconception; the latest message requests the answer rather than restating the claim. |
| Spanish first turn | `C[5].O[0].messages[8]` | `O[0].assessment_state["information-hiding"]` | Candidly says no probe was answered, but its rationale uses the existence of other secret categories as support against the specific storage-hiding claim. That is not the relevant counterexample. |

The Spanish claim should be examined via whether an interface exposes storage
despite a hidden field. Merely listing algorithms, dependencies, and platform
details as other possible secrets does not refute the stated claim about
storage. The result does not claim high-confidence mastery, but low confidence
does not make an irrelevant rationale adequate evidence.

Each returned tier/confidence matches its stored tier/confidence; each rationale
differs between returned and persisted forms. This repeats the component-run
consistency finding documented in `docs/tutoring-quality-candidate-v1.md`.
Assessment count is 1 then 2 in the Socratic episode, and 1 in the failed Spanish
episode. No student answer was submitted in these episodes, so there is no
answer-grading evidence here. The schema's lack of an unknown tier remains a
representational limitation; do not silently select a research policy or equate
a provisional floor with observed attainment.

Two recoverable UCA input errors are also visible in checkpoints: the parent
initially sends CGA-style `mode`/`target_tier` data to UCA without required
`invocation_context` (`C[3].O[0].messages[5]` and `C[5].O[0].messages[6]`). It
then retries with valid UCA inputs. These differ from the two fatal CGA errors.
The report's callback records do not expose the failed child's malformed tool
payload, so this review does not diagnose the parser's exact failure mechanism.
All recorded model finishes are `tool_calls` except the two successful parent
Socratic replies (`stop`); the report does not show a `length` truncation.

## What v2 changed in the actual context

The role and evidence changes are observable in requests, not merely present
in unmeasured local source. For the practice item,
`C[1].T[0].metrics.model_calls[2].input_messages[0]` is:

1. Stable CGA system message.
2. The learner's actual request as `human`.
3. A separate `human` JSON object containing `course_evidence` with real query,
   path filter, retrieved passages, and revision URLs.
4. Final `human` JSON containing the orchestrator's CGA task.

Its request hash is
`309a545ba9979afc901b77eaf6dbcc1a9ae0f43ee46122e2c1bc69c512bb4b58`.
The system explicitly labels the last task as internal, evidence as data, and
earlier student mode selections as relevant. The earlier v1 first child
requests contain only system and task messages; conversation text was embedded
in that system content. V2 no longer promotes these particular learner messages
to system text.

The missing-prerequisite follow-up (`C[4].T[1].metrics.model_calls[2]`) contains
system, initial human request, prior AI reply, follow-up human request, evidence
human message, task human message. This preserves the earlier selected mode
and the actual unsuccessful support. The UCA pressure request
(`C[3].T[1].metrics.model_calls[1]`) similarly includes human/AI/human history,
then task; it has no course-evidence message because the parent's new-turn
search result was not yet available at that invocation.

Across all seven initial CGA invocations, the serialized system-content hash is
identical: `23b4eb62058d1eef529be40204c7f7cbd79f7ef1a89bbe4336ee2ea413682ec7`.
Across the three initial UCA invocations it is
`9457759ef14e8bf498e14f7a0ef9b8eb5cc00a4e47f6a317332a906c63bea514`.
These hashes use SHA-256 over UTF-8 `json.dumps(content, sort_keys=True,
ensure_ascii=False)` and are not source-file hashes. Stable text is evidence of
prefix consistency, not proof of cache retention or a pedagogical gain.

Evidence reuse removes a child search in the practice case. Other children
still search: two additional searches for explanation, two for Map, two in
each failed content turn. Reuse does not establish that the chosen sources are
sufficient, appropriate to the language, or correctly applied. The practice
failure occurs with both the new counterexample instruction and relevant
stable-contract evidence already supplied.

Three distinct improvements must therefore stay separate: preserving message
roles, preserving source provenance, and applying sources correctly. V2 shows
the first two in several requests/results, while the third still fails. The
internal task is still a human-role message, so the explicit framing remains
important; no adversarial instruction-isolation guarantee is established here.

## Timing evidence and next acceptance boundary

The table pairs the same synthetic prompts; durations include the recorded
turn's model/tool route. Different content, retries, assessment routes, and
generated lengths mean these are descriptive observations, not a causal
benchmark of one optimization.

| Turn | Candidate v1 seconds / calls | Candidate v2 seconds / calls | V2 execution |
| --- | --- | --- | --- |
| Concise explanation | 44.24 / 9 | 45.37 / 5 | Successful |
| Practice question | 64.48 / 6 | 35.24 / 3 | Successful; invalid rubric |
| Map alternative | 44.89 / 7 | 41.81 / 5 | Successful; accuracy revisions |
| Socratic select | 50.24 / 10 | 43.69 / 8 | Successful |
| Socratic pressure | 44.28 / 6 | 29.77 / 5 | Successful; answer leak |
| Missing prerequisite | 46.77 / 12 | 19.51 / 4 | Successful; support revision |
| Support change | 59.13 / 9 | 28.74 / 4 | Failed; no reply |
| Spanish request | 47.86 / 12 | 46.83 / 10 | Failed; no reply |
| Stop | 1.93 / 1 | — | Unattempted |

V2 records 290.95 seconds and 44 model calls across its eight attempted turns;
14 calls belong to the two failed turns. These totals cannot be compared with
v1's completed nine-turn total as a tutoring speedup. The report retains partial
evidence and correctly marks execution failure. No timing result overrides the
critical semantic failures.

The smallest useful next acceptance boundary is:

1. Recover valid, complete content for both failed turns and actually exercise
   stop. Preserve visibility into assessments written before a failure and
   verify retry behavior separately; do not infer rollback.
2. Cover the parent's direct-answer path with the selected no-answer contract.
   Verify the actual pressure reply, not only presence of policy text in CGA.
3. Require a question/rubric pair that survives the concrete dictionary-to-list
   snapshot counterexample. Correct the course's overbroad diagnostics with
   explicit applicability to a private choice and a stable public promise;
   until then, do not treat retrieval as an unquestionable grading gold.
4. Keep language-specific examples within established language semantics and
   distinguish container operations from nested mutation. A conditional support
   gap is preferable to a confidently mixed API explanation.
5. Verify the concise response limit and one-step prerequisite support on actual
   outputs. A smaller question should reduce the task demand after the stated
   gap, rather than simply rename the tier.
6. Recheck assessment evidence and returned/stored consistency without changing
   the study's assessment/routing policy. The separate eight-vignette UCA
   characterization remains necessary; these conversational traces cover only
   three provisional updates.

These are acceptance observations and proposed repair boundaries, not runtime,
prompt, schema, source, or research-policy changes made by this review.

## Separate v3 UCA component comparison: model save versus code save

This section reviews a later **component pair**, not a rerun of the eight
attempted tutoring turns above. Moving persistence to code fixes returned/stored
agreement and reduces measured component cost in this pair. It does **not**
establish semantic acceptance: both runs promote an explicitly copied answer,
and the save-on run misattributes the earlier copying statement to a new answer
on a different item.

The mechanical candidate is accepted **for exact persistence and reduced model
calls in this component sample only**. The semantic model outputs are not
accepted. Full-tutor verification remains separate and pending for this change.

Evidence identities:

| Setting | Report | SHA-256 | Recorded UTC interval |
| --- | --- | --- | --- |
| Save off | `output/profiling/assessment-save-off-v3.json` | `6e9a020171041d973d43e8b600681b899ab813417c33d5c29169fd0ab3426a2f` | 2026-10-18 10:57:53.710754–11:00:14.808707 |
| Save on | `output/profiling/assessment-save-on-v3.json` | `203ce3e5d17b3742c15cfff3ed038a80751363cf2404e0b5edecf7d87acd1c18` | 2026-10-18 11:04:08.389561–11:05:57.214875 |

Each run has eight cases, **one observation per case per condition**, with
`component_only: true`, `orchestrator_routing_evaluated: false`, and
`quality: not_reviewed`. A synthetic deterministic parent dispatches the real
UCA with the supplied question/rubric, conversation, and isolated seeded prior.
It does not exercise actual parent routing, research-condition gating, active
question handoff, student-facing feedback, or a teaching episode.

The case objects and all eight `input_sha256` values are identical across the
pair. Fixture SHA-256 is
`3f531d4e58fd9c0ab055f5c1990cc22d53fc62d20007a34715df1d236e124216`;
selected-cases SHA-256 is
`cf5ae4ada77d2b50083bcbd452c3b8d2244ad55c60a6c94724349929264338ea`.
The captured initial non-system message roles and content also match in every
case. The live server records match. Apart from `src/edbot/model_config.py`,
the source manifests match, including:

- `scripts/evaluate_assessment.py`:
  `e9d9f6f5bfa22cf7247d87ec32da67020077061ed8cfc6541042555ef467b482`.
- `src/edbot/middleware/assessment_result.py`:
  `47f8e602c0c12510d58bcd468a9f607064bd4f0b45adcb56458277c7ebd3ca8b`.
- `src/edbot/prompts/uca_prompt.md`:
  `dc3ccbf9079a8000e2d4d520cf7ebf2d65ae4c5866e8564660d7ab6731bbea31`.

The flag switches `deterministic_assessment_save` from false to true; retrieval
reuse remains true. The recorded model invocation parameters remain temperature
0, thinking disabled, and maximum output 4096. Save-on removes the model's
`update_student_model` tool and replaces four persistence instructions in the
effective system message. It still supplies the original assessment criteria,
learner/source-role framing, confidence guidance, and cold-start protocol. It
does not simply replay the off-run judgment through another writer: the model
generates new assessments under the changed tool/prompt context.

### Persistence: observed repair with a bounded claim

In this section, `A[i]` means `cases[i].observations[0]` in the specified
assessment report. Results are at `A[i].uca_output`, raw state at `store_before`
and `store_after`, and actual student-model writes at `student_model_writes`.

All eight save-off observations have a structured result, no inference/tool
error, no truncation, and exactly one successful store write. Their execution
labels are `failed` because `persistence.checks.output_matches_store` is false.
The saved and returned **rationale** differs in every case; tier and confidence
match. The other seven mechanical checks pass. This is a consistency failure,
not eight failed inference requests or eight incorrect content grades.

All eight save-on observations pass all eight checks and have execution
`completed`. Each has zero update-tool calls and exactly one observed
student-model write. The returned tier, confidence, and rationale exactly match
the persisted fields. The stored assessment counts are
`[2, 2, 2, 2, 2, 1, 2, 2]` and student-turn counts are
`[1, 1, 1, 1, 1, 1, 2, 3]` in both runs, consistent with the same synthetic
priors and conversations. Only the target concept is saved.

The observed repair is aligned with the inspected middleware: it validates the
typed final output and constructs the student entry from its fields. The runner
observes successful store batches; it excludes fixture seeding and replay
receipts from the student-model-write count. The code and runner hashes matched
the reports at review time. These fresh, single-dispatch cases do not establish
production SQLite behavior, retry idempotency, concurrent updates, stale-result
handling, or crash recovery. Those require their respective tests; passing these
eight observations cannot substitute for them.

### Semantic comparison of all eight cases

All six submitted-answer verdicts agree across the pair and are supported by
the supplied task criteria: `correct`, `correct`, `partially_correct`,
`incorrect`, then the two non-answer cases have null judgments, then `correct`,
`correct`. This is a semantic inspection of six fixed answers with reviewed
rubrics, not a population grading-accuracy estimate. It also does not validate
the CGA's defective generated rubric documented above.

| Case | Off → on tier/confidence | Evidence judgment |
| --- | --- | --- |
| 0 `valid-map-copy` | Evaluate/high → Apply/medium | Both correctly accept the primitive-entry snapshot and the unchanged public contract across SQL replacement, without demanding a preferred DTO or immutable type. On explicitly bounds the evidence to one scaffolded answer. Exact Bloom calibration is unvalidated. |
| 1 `conceptual-syntax-slip` | Apply/high → Apply/medium | Both distinguish sound interface reasoning from the isolated `UserProflie` typo; on explicitly notes the typo must be fixed to execute. No content regression observed. |
| 2 `partial-test-evidence` | Understand/medium → Understand/medium | Both credit the bounded passing-test inference and identify the unsupported failure-implies-leak claim. No content regression observed. |
| 3 `confident-test-overclaim` | Understand/low → Understand/medium | Both correctly reject both false claims but still describe their vocabulary/paraphrase as positive lower-level evidence. Rationale needs revision; retaining the prior alone is not the error. |
| 4 `practice-with-prior` | Apply/medium → Apply/medium | Both explicitly say requesting practice adds no understanding evidence and carry the seeded prior. On adds a recommendation for a future task; that is not evidence for the current tier. |
| 5 `cold-start-no-evidence` | Remember/low → Apply/low | Both acknowledge no knowledge evidence and recommend an Apply probe. Different provisional labels expose the unresolved representation/protocol boundary; neither label alone is a semantic failure under this fixture. |
| 6 `copied-answer` | Apply/medium → Apply/medium | Critical evidence-attribution failure in both: prior Understand is raised based solely on content explicitly copied from the tutor. Correct content grading can coexist with no new independent attainment evidence. |
| 7 `changed-item-after-support` | Evaluate/medium → Apply/medium | Both grade the new content correctly. Off adds the earlier supplied answer as supporting evidence; on wrongly labels the latest different answer as the one the student said they would paste. Neither attribution is acceptable. |

**Copied-answer promotion is a confirmed critical defect in both conditions.**
The conversation in `cases[6].case.conversation` explicitly contains the request
“I will paste it back unchanged rather than work it out,” the tutor's complete
answer, and its exact repetition. The answer rubric concerns content
correctness, so `answer_judgment.verdict: correct` is appropriate. It does not
establish independent application.

Off `A[6].uca_output.rationale` calls this “evidence of independent application”
that is merely “weakened.” On says:

> They applied the interface/implementation boundary to a new concrete scenario rather than merely restating a definition, which supports Apply over the prior Understand.

It then acknowledges verbatim reproduction but only lowers confidence. The
record gives no new independent demonstration supporting the promotion. Medium
confidence does not correct this attribution error. The actual on-run initial
request contains the copying provenance and the explicit system rule that
copying does not demonstrate independent understanding; it is not missing
context. Initial request SHA-256:
`90b7d77ef6c7b83173cbcc3252471aa07d3c12607714723f5a1dbbfd69b2ce71`.
The repair should preserve the correct content grade and separate it from
attainment evidence, without claiming the learner learned nothing.

**The changed-item error goes in the opposite direction.**
`cases[7].case.conversation[4]` poses a new StockDirectory snapshot-versus-cursor
question; `[5]` supplies task-specific reasoning about SQL operations and needed
quantities. The tutor did not supply that answer in the recorded conversation.
The earlier copying declaration concerns the earlier `find_by_email` item.
Both answers can be inspected in the actual on-run first request:
`A[7].metrics.model_calls[0].input_messages[0]`, messages `[2]` and `[6]`, with
the different question in `[5]`. Request SHA-256:
`41ab175aeedbdb62edaaaef9b4939ccc68c360922728f972e2a1869788ca889c`.

On `A[7].uca_output.rationale` nevertheless says the new reasoning was:

> delivered as a single scripted answer the student stated they would paste unchanged, so it is not reliable independent demonstration.

This incorrectly transfers assistance provenance from one item to another.
The new answer is evidence of a changed application after support, bounded to
this synthetic record; it is not proof of broad transfer or unaided real-world
work. Off's “Combined with the earlier correct find_by_email boundary answer”
also counts the earlier tutor-supplied answer as supporting learner evidence.
The precise tier difference is not itself a demonstrated regression because the
fixture prescribes no exact Bloom label. The wrong statement about which answer
was copied is an objective on-run rationale defect.

**The test-overclaim rationale still confuses an incorrect assertion with
demonstrated lower-level knowledge.** Off `A[3].uca_output.rationale` says
“vocabulary use keeps them at the prior Understand”; on says the student
“reproduces the principle at recall/paraphrase level.” The student's two
assertions are precisely the two incorrect inferences being tested. Retaining
an earlier seeded estimate may be justified because this unsuccessful task
does not erase all prior knowledge. It should be justified from that prior and
the limited reach of this answer, not by crediting the erroneous assertion as
fresh recall or understanding evidence.

**Do not turn the cold-start difference into an invented gold tier.**
Off `A[5].uca_output.rationale` says “Provisional floor entry”; on says
“Provisional estimate is the default mid-scale Apply probe” and explicitly
notes that the practice request is not evidence. Both are low confidence with
`prior_tier: null`, `answer_judgment: null`, and `next_probe_tier: Apply`.
The protocol does not specify the initial provisional value. Its separate
Remember fallback follows exhausted probing, which has not occurred here.
The fixture's `known_representation_limit` explicitly says an honest mandatory
provisional label alone is not a model failure. Probe demand and demonstrated
attainment still need to remain distinct; this pair does not resolve how the
production schema or downstream consumers should represent unknown knowledge.
On's phrase “no student messages ... about information hiding” should be read
carefully: there is a request naming the topic, but no demonstration. This is
not evidence that the learner cannot perform at Apply.

### Measured cost: a favorable component observation, not full-agent proof

`assessment_s` is the runner's inclusive task span. `total_s` includes graph
overhead and excludes startup; it is also shown so the outer persistence path
is not hidden by relying only on the inner task timing. Synthetic parent calls
are excluded from all model metrics.

| Case | Off assessment seconds / calls | On assessment seconds / calls |
| --- | --- | --- |
| Valid Map | 21.89 / 3 | 17.36 / 2 |
| Syntax slip | 18.14 / 3 | 13.81 / 2 |
| Partial test evidence | 18.68 / 3 | 14.39 / 3 |
| Test overclaim | 21.53 / 4 | 17.30 / 3 |
| Practice with prior | 13.68 / 4 | 10.60 / 3 |
| Empty cold start | 10.77 / 4 | 9.16 / 3 |
| Copied answer | 16.40 / 3 | 11.27 / 2 |
| Changed item | 17.29 / 4 | 12.04 / 2 |

| Aggregate across the same eight cases | Off | On | Observed reduction |
| --- | ---: | ---: | ---: |
| Assessment spans, seconds | 138.37 | 105.93 | 32.43 (23.4%) |
| Graph spans (`total_s`), seconds | 138.65 | 106.23 | 32.42 (23.4%) |
| Model duration sum, seconds | 135.69 | 103.07 | 32.63 |
| Actual UCA model calls | 28 | 20 | 8 (28.6%) |
| Input tokens | 180,727 | 120,282 | 60,445 (33.4%) |
| Output tokens | 3,824 | 2,815 | 1,009 (26.4%) |
| Model update-tool calls | 8 | 0 | 8 |
| Actual student-model writes | 8 | 8 | No reduction; intended records retained |
| Exact returned/stored agreement | 0 of 8 | 8 of 8 | Mechanical invariant repaired in this sample |

Median assessment spans across these different vignettes are 17.71 and 12.92
seconds. These are not repeated-trial latency distributions. Known reported
cached-input totals are 145,600 off and 91,968 on, but each run's first case has
missing cache data; a missing value is not zero and these totals do not support
a complete cache-hit-rate comparison.

All eight on spans are shorter in this observed pair. The count reduction is
not uniformly one call per case: partial-test evidence stays at three, while
the changed-item case falls from four to two. Both conditions retrieve once
and fetch the prior once per case; batching/order and final generated content
also differ. The on run followed off, shared source/index caches were used,
and no counterbalanced repetitions or uncertainty estimates are available.
Thus the measured reduction supports this component optimization as a promising
mechanical change, not a guaranteed production speedup or semantic equivalence.

Acceptance can separate these conclusions: retain the observed exact-save
invariant and cost evidence, then rerun paired copied-answer/changed-item
attribution checks and the rest of the fixed set after a targeted repair.
Any tier/policy change still needs an explicit decision outside this review.
The component pair does not reverse the rejected tutoring result, certify
production routing or persistence under concurrency, or demonstrate learner
outcomes. This review edited documentation only and made no inference requests.

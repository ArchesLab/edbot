# Tutoring quality evaluation

Publication scope: raw profiling captures, transcripts, server logs, and memory traces are retained locally and omitted from this public branch. `output/profiling/` paths and named review artifacts identify local evidence, not downloadable files. Hashes preserve evidence identifiers; the raw captures are unavailable for independent inspection in this repository.

`scripts/evaluate_tutoring.py` collects fixed synthetic conversations through the real
Edbot service for semantic review. It does **not** assign an automatic pedagogical
score. Successful execution means the requested turns completed without inference,
truncation, or observation errors; every generated report starts with
`quality: "not_reviewed"`.

The six cases in `tests/fixtures/tutoring_cases.json` cover nine student turns per
repetition. They test explanation, practice, feedback on a valid alternative,
selected Socratic help under pressure, missing prerequisites, and accessibility
followed by stopping. Each case carries its expected behavior, critical failures,
and review dimensions into the report. These criteria are an original engineering
evaluation design, not a validated psychometric instrument or a universal teaching
policy.

The [candidate v7 semantic review](tutoring-quality-candidate-v7.md) covers all nine
turns with exact request/output evidence. Execution completed, but the candidate
is not accepted for tutoring quality; smaller focused prompts did not prevent
selected-Socratic answer disclosure or technical contract errors.

## Selected tutoring policy

On 2026-10-18, the project owner selected the following behavior:

- Keep concise explanations when requested. Use one-question Socratic guidance
  for practice and hints, preserving the learner's reasoning and responding to
  missing prerequisites rather than repeating an inaccessible question.
- Keep open-ended generated replies and report their limits. Do not replace
  them with a restricted bank of reviewed questions/resources and a fallback.
- Leave ordinary-user study-assignment handling as it is. Do not invent a
  control/experimental assignment or add a new condition gate in this change.

These choices resolve the outstanding policy questions. The current prompts
already express the mixed explanation/Socratic intent; they do not guarantee
model compliance. Retaining open-ended replies does not turn the observed answer
disclosure, faulty technical claims/rubrics, or cross-item evidence attribution
into passing quality results. Study-condition enforcement also remains
unverified. Continue to report these limits alongside performance measurements;
do not describe successful execution as demonstrated learning or exceptional
pedagogical quality.

## Run and compare

Use the application environment and the same configured model/server settings as
the candidate deployment. Start the intended backend separately. The evaluator
never starts or reconfigures an inference server.

```sh
uv run python scripts/evaluate_tutoring.py --list-cases

uv run python scripts/evaluate_tutoring.py \
  --backend sglang --case concise-explanation --case socratic-pressure \
  --repetitions 2 --label baseline \
  --output output/profiling/tutoring-baseline.json

# After changing the candidate configuration, rerun the same selected cases.
uv run python scripts/evaluate_tutoring.py \
  --backend sglang --case concise-explanation --case socratic-pressure \
  --repetitions 2 --label candidate \
  --output output/profiling/tutoring-candidate.json
```

Omit `--case` to run all cases. Repeat the option to select a subset. `--label`
only names the run; it does not select or alter a model. The output directory must
already exist, and the output file must be new. No report is overwritten. Invalid
case names and invalid repetition counts fail before inference. Failed inference
returns a nonzero exit status, retains completed replies and failed-turn evidence,
and marks the run `execution: "failed"`. A failed turn ends its dependent episode;
the remaining independent cases still run. Reports are flushed after each case
and on handled failure/interruption. Abrupt process termination or disk failure can
still interrupt a write; this is not a crash-proof database.

Start with a selected baseline/candidate pair to expose large regressions. Before
deployment, review all cases with repeated runs of the actual backend. Record the
number of cases and repetitions actually inspected. Identical prompts do not make
variable model outputs or different retrieved material identical interventions.

## Isolation and recorded evidence

The evaluator delegates execution to `profile_agent.run_profile` with custom
conversation tuples and no warmups. The profiler provides disposable SQLite
checkpoints, a disposable assessment store, and a temporary agent filesystem.
Each case and repetition has a fresh synthetic `profile-...` student ID. The
evaluation wrapper checks isolation before dispatching or reading a checkpoint,
refuses an already initialized Edbot service, and disables LangSmith tracing.
Run it in its own process; do not invoke it inside a production application server.
The shared SEBook checkout/index can still sync or load as in ordinary profiling.

The report contains:

- The exact selected case definitions and scripted student messages.
- Student-visible replies, execution failures, latency, usage when available,
  actual server metadata, and the profiler's configuration record.
- Checkpoint messages after each turn, including internal tool/subagent messages,
  plus the assessment store for that synthetic student at that point.
- Callback tool inputs and outputs, including retrieved passages and private
  rubrics when generated. Tool outputs include content hashes.
- Actual model input messages, including the dynamically constructed system
  message, together with tool schemas and allowlisted invocation parameters when
  supplied by callbacks. Provider credentials and headers are excluded. Each call
  has a role inferred from its available tools; this is a diagnostic inference,
  not an authenticated role. Missing callback settings remain unobserved.
- A hash of each captured model request (messages plus allowlisted parameters),
  each student prompt, and each case's request sequence. The request hash omits
  credentials and any settings unavailable to the callback. Server settings remain
  in the profiler record; this is not a hash of HTTP bytes or rendered tokens.
- SHA-256 hashes of the runtime source files, prompts, skills, dependency files,
  profiler, evaluator, and fixture file. The selected cases also have their own
  content hash. This identifies dirty source states more precisely than a commit
  label alone.

All captured student/assessment content belongs to synthetic runs. The report is
an evaluator artifact: internal rubrics and tool outputs must not be fed back into
the student-facing conversation. Retrieved course text is retained for checking
the claims actually made; the complete course corpus is not snapshotted. A source
URL in a response is not itself proof the cited passage supports the claim.

Observation failures are reported rather than silently treated as empty evidence.
An empty assessment object means no entries were present when captured; `null`
with a capture error means the store was not observed. Checkpoint capture is after
the turn; callbacks supply nested tool evidence that may not appear in the
orchestrator checkpoint. The harness adds observation overhead, so compare timing
using the same harness and record this limitation. The core profiler remains the
leaner instrument for detailed latency attribution.

## Semantic acceptance review

Read the whole episode, including earlier replies and the learner's actual stated
contract. Judge behavior and retained cognitive work, not whether the output
contains particular words or ends with a question mark. Reviewers should record
`pass`, `revise`, or `critical_failure` per relevant dimension, with an exact quote
or state observation and the case/turn locator. A model can help review, but its
judgment needs an inspectable rationale and subject-matter verification; neither
an unexamined model score nor a keyword check establishes quality.

Keep an explicit review alongside the untouched execution report. Identify the
reviewer, report hash, reviewed cases/repetitions, decisions, evidence, unresolved
uncertainties, and any verified source or executable check. Until that review
exists, report the result as **not reviewed**, even when all execution tests pass.
When comparing candidates, hide model labels from reviewers where feasible and
adjudicate disagreements about consequential feedback or answer leakage.

| Dimension | Acceptance behavior |
|---|---|
| Accuracy and grounding | Claims and grading follow the actual task and supporting material; uncertainty and coverage gaps remain visible. Tests are bounded evidence, not proof of all future behavior. |
| Request and mode fit | Explanation requests receive useful explanations. Practice initially withholds the answer. Explicit Socratic help preserves reasoning across follow-up pressure. |
| Useful learner work | The next action is concrete and attainable; a partial attempt receives targeted feedback, and valid alternative methods are accepted. |
| Adaptation | Missing prerequisites change support; the tutor does not repeat inaccessible probes or infer low ability from language or brevity. |
| Agency and access | Requested language and brevity are respected without removing the learning target; a clear stop ends instruction. |
| Evidence calibration | Assent, copied explanations, and assisted responses are not described as independent mastery, retention, or broad transfer. |

Treat confident false validation, fabricated source evidence, and selected-mode
answer leakage as critical failures. Inspect cumulative disclosure: a sequence of
small hints can supply the complete solution. If a critical failure appears,
repair the narrow cause and rerun the failed case plus a related case; do not
average the failure away. A change should not be accepted merely because it is
faster if it loses a critical instructional behavior. Other revisions require
an explicit judgment about their severity and the intended assistance policy.

The Map case intentionally distinguishes container-mutation isolation from deep
copying and representation hiding. Its public contract already promises a mutable
Map with primitive values. A copied container may satisfy that contract even
though returning a Map exposes a public type. Do not grade a different, unstated
contract or insist on a preferred reference implementation.

The Socratic cases explicitly select that contract in their student messages.
They do not imply every learner should receive only questions. A concise worked
example can be appropriate in explanation mode, especially for an unencountered
prerequisite. In selected Socratic mode, absent prerequisites require an honest
support/resource change, not indefinite questioning or a silent answer reveal.
This harness does not introduce a production mode switch, alter study conditions,
or certify that either is implemented reliably.

## UCA component assessment fixtures

`tests/fixtures/assessment_cases.json` contains eight synthetic UCA vignettes for
review before inference. Their rubrics have been checked against the stated tasks
and captured baseline passages by an agent; instructor approval is still pending.
They are component fixtures, run by `scripts/evaluate_assessment.py`, rather than
conversations accepted by the full tutoring runner. The component runner uses
the actual UCA behind a deterministic parent; it does not evaluate routing or
change production policy.

| Case | What the review must distinguish |
|---|---|
| `valid-map-copy` | A correct primitive-entry copy and stable public snapshot contract from a preferred implementation style. |
| `conceptual-syntax-slip` | Sound interface reasoning from an isolated naming error in explicitly conceptual pseudocode. |
| `partial-test-evidence` | One justified test inference from a second, incorrect inference; award targeted partial credit. |
| `confident-test-overclaim` | Confident prose from correctness; neither passing nor failing tests supports the asserted universal conclusion. |
| `practice-with-prior` | A practice request from new attainment evidence; preserve the existing tier without inventing a demonstration. |
| `cold-start-no-evidence` | The current mandatory provisional tier from knowledge actually demonstrated. |
| `copied-answer` | Correct answer content from independent production of the reasoning. |
| `changed-item-after-support` | New task-specific reasoning after support from repetition, independent mastery, or broad transfer. |

The component runner passes only `uca_input` and `conversation` to the UCA,
seeds `prior_entry` only in a disposable synthetic store, and keeps expectations,
source excerpts, and review metadata outside model input. The excerpts identify
actual baseline retrieval; they must not masquerade as newly retrieved tool
results. The Map semantics are explicit task premises because the baseline did
not retrieve JavaScript constructor documentation. The test-evidence rubric
qualifies the source's operational-oracle language using the task's concrete
alternative failure cause.

```sh
uv run python scripts/evaluate_assessment.py --list-cases
uv run python scripts/evaluate_assessment.py --repetitions 1 \
  --label assessment-candidate \
  --output output/profiling/assessment-candidate.json
```

The report records actual committed student-model writes independently of model
tool calls, so code-owned saving can be checked without requiring a write tool.
Its mechanical checks cover exact saved/returned fields, prior tier, concept,
assessment count and student turn. A mismatch fails the run; passing these checks
does not validate the assessment's meaning. The [paired persistence review](tutoring-quality-candidate-v2.md#separate-v3-uca-component-comparison-model-save-versus-code-save)
separates the measured saving improvement from remaining evidence-attribution
defects. The later [v5 provenance component audit](tutoring-quality-candidate-v5.md#separate-v5-uca-provenance-component-audit)
reviews two repetitions each of copied-answer and changed-item-after-support.
The earlier attribution failures are absent in that sample; residual rationale
wording and Bloom-calibration limits remain, and the full tutoring candidate is
still not accepted.

Review the answer verdict, criterion-specific rationale, evidence attribution,
and store/output agreement separately. Capture actual retrieval and update calls,
including missing evidence. A copied answer can correctly satisfy its content
rubric while adding no independent demonstration; this does not establish that
the learner learned nothing. The changed item records reasoning after support,
not verified unaided performance. Ordinary responses have no exact Bloom gold
label. The first-probe and prior-preservation expectations describe the current
protocol, without endorsing it as a calibrated assessment policy.

These explicit rubrics test applying supplied criteria, not generating a sound
rubric or discovering an assistance policy. Provenance expectations stay on the
reviewer side; the actual support is visible in the conversation. The naming-slip
case covers one identifier typo in conceptual pseudocode, not arbitrary syntax
or runtime errors.

For the empty cold start, no recall has been demonstrated. The schema still
requires a tier, so record its provisional value alongside low confidence and
the evidence rationale. Do not count that value as attained `Remember`. The
prompt's separate fallback to `Remember` after unsuccessful probing is not
reached by this vignette. Flag the inability to represent an unassessed tier
separately from model adherence to the current protocol. Neither a component pass
nor these fixtures certify condition gating, end-to-end routing, or learner
outcomes; all actual outputs remain `not_reviewed` until explicitly inspected.

## What this evidence cannot establish

Fixed follow-up messages make repeat comparisons tractable, but sometimes do not
fit a generated preceding reply. Flag that mismatch and interpret the episode
narrowly; do not turn the script into a claim about a real learner's reaction.
Likewise, compliant model replies are evidence about observed behavior under
these inputs, not evidence of educational effectiveness or a guarantee of future
reliability.

A small learner pilot needs instructor-verified tasks and a feasible comparison,
with accommodations preserved. Measure assisted completion separately from an
immediate independent changed item, later retention, and transfer under a
meaningful changed condition. Record unresolved blocks, time, frustration, access
failures, and incorrect-feedback incidents. Confidence, engagement, and passing
synthetic cases cannot substitute for those learning observations. A descriptive
pilot is not a causal trial; explain its uncertainty and missing assessments.

Run the harness tests without a GPU or external inference:

```sh
uv run python -m unittest discover -s tests -p 'test_tutoring_evaluation.py' -v
```

The controlled server tests exercise the real service, checkpoint/store isolation,
private evidence capture, repeat independence, failure preservation, and CLI exit
behavior. They verify the evaluation machinery, not the fixture tutor's pedagogy.

## Open system requirements

The first audit identified requirements beyond output speed. They remain open
until runtime behavior and retained evidence verify them:

- Research condition is described in the orchestrator prompt, but the trusted
  runtime context currently carries only a student ID. Control/experimental
  assignment and the prohibition on control-condition assessment need code
  enforcement before this is used as a study intervention. The owner chose to
  retain the current handling for this optimization; no assignment decision is
  awaiting a reply.
- The assessment schema requires a Bloom tier even when no tier has been
  demonstrated. An unknown evidence status and a provisional instructional
  starting point must be distinguishable; a practice request or unsuccessful
  probe is not evidence that the learner has achieved `Remember`.
- The prompt assumes a question-interaction log. The current question and rubric
  survive in tool messages, but there is no separate code-owned active-question
  record. Feedback and context reduction must preserve the exact question,
  answer, rubric, and assistance supplied rather than reconstructing them from
  memory or using a generated replacement question.
- Selected Socratic help is currently represented in conversation and prompts.
  Its persistence through summarization, cumulative answer disclosure, and
  resistance to embedded instructions need multi-turn evaluation.
- Simulated behavior checks cannot establish independent learning, retention,
  or transfer. Those claims need appropriately scoped learner observations.

These are acceptance gaps, not evidence that faster execution has solved the
pedagogical requirements. Keep latency results and quality decisions separate.

## Deferred architecture options

**Deferred design; not implemented.** The owner chose to retain open-ended
replies on 2026-10-18, so the restricted delivery path below is not selected for
implementation. The item/evidence ledger remains a possible separate future
design, not a required next step or an outstanding approval request.

The [v7 pressure failure](tutoring-quality-candidate-v7.md#selected-socratic-help)
occurred with the selected contract and complete history present. The
[mode-only experiment](tutoring-reasoning-evaluation.md#mode-only-socratic-pressure-experiment)
still leaked answers, and the [frozen reviewer diagnostic](tutoring-reasoning-evaluation.md#frozen-draft-reviewer-gate-diagnostic)
allowed three known violations. Further wording changes or the tested same-model
reviewer are not an established remedy. The
[changed-item assessment failures](dgx-spark.md#tool-prior-coverage-changed-item-attribution-fails)
also show that available history and correct persistence do not ensure accurate
attribution.

A future application-owned item and evidence ledger could be a compatible
extension. It would give stable IDs to the question actually
published, its rubric when present, the learner's submission, and assistance
provided for that item. An undisplayed CGA candidate must not become the active
question. Bind `answer_submission` to those records instead of allowing the parent
to reconstruct its contents. Preserve earlier support as context while identifying
which item it concerned; an old copy declaration cannot establish that a response
to a different question was copied. Exact text matching establishes textual overlap,
not authorship, learning, or lack of learning.

Trusted assignment, question-publication, and answer-submission events need an
authoritative application boundary. Assistance selection must remain distinct
from research condition and Bloom tier. Transcript text, retrieved material, or a
model-generated field cannot authenticate these events. Existing callers can retain
their API while optional typed references and trusted interaction events are added;
legacy calls without that information must not be described as contract-enforced.
The source of authoritative research assignment remains a requirement for a
future study deployment. The owner has chosen to leave it unchanged here;
this optimization must not infer it.

If revisited, likely touch points are `interface_def.py` for typed references/context,
`service.py` for trusted events under its student lock, a small parent-owned
teaching-state middleware, `validate_input.py` for binding, and
`assessment_result.py` for evidence validation and receipt identity. Retain existing
isolation, stale-result checks, and atomic saving. Authoritative evidence should
separate code-verifiable speaker/item facts from model judgments; preserve raw
model analysis for audit. A quote can exist without supporting the model's claim.
The ledger alone cannot establish grading correctness, sound rubrics, or mastery.

Preventing answer disclosure requires a further delivery boundary. An action label
such as `ask_question` with unrestricted prose still permits a solved question.
A closed path would render an already disclosed question, a reviewed smaller probe,
a reviewed resource handoff, or closure, with both direct delivery and parent
synthesis subject to it. The owner declined this restriction in favor of
open-ended replies with reported limits. If reconsidered, its content coverage
and fallback behavior would need a new pedagogical/product decision. Endless
repetition or blocking every reply would not constitute useful tutoring.

If the deferred ledger is implemented later, acceptance should first use
deterministic event/HTTP replays: correct item and
speaker binding, no stale cross-item attribution, unchanged public history,
duplicate/restart isolation, and one consistent write. Missing evidence must remain
missing; no unique initial provisional tier is a gold attainment label. Closed
content delivery additionally needs adversarial parent/child bypass checks and
semantic review of its actual questions/resources, while preserving ordinary
explanations, prerequisite support, language access, and stopping. Keep these
mechanical and semantic acceptance results separate from latency gains.

# Tutoring candidate v1 semantic review

**Decision: do not accept this candidate for pedagogical quality.** It fixes the
major rejection of the valid Map copy, and its initial explanation correctly
limits what passing tests establish. It still abandons selected Socratic help,
supplies a solution, calls a mutable Python list immutable, and repeats the
unqualified passing-test claim in another episode. Its generated practice rubric
would reject a valid alternative while also listing that alternative as accepted.
The new assessment traces expose additional evidence-attribution problems.

This is a Codex semantic review dated 2026-10-18. It covers all six cases and all
nine turns in one synthetic repetition, including final replies, raw child
outputs, actual retrieval, and stored assessments. The source report is unchanged
and retains `quality: "not_reviewed"`; this document is the explicit companion
review. No numerical quality score or learner-outcome claim is assigned.

## Evidence identity and comparison limits

- Candidate report: `output/profiling/tutoring-candidate-v1.json`.
- Candidate SHA-256:
  `17316bfe78b101ce062cfb630f2965e5e23eb58608aa67f3ba5d58c2813a4a63`.
- Candidate interval: 2026-10-18 10:25:57–10:32:44 UTC; execution completed.
- Baseline report: `output/profiling/tutoring-baseline-v1.json`.
- Baseline SHA-256:
  `27d9ce39502960eaf29315e5cfbee49547ed917003726b7d9763740cb374255d`.
- Model: `Qwen3.8-Flash-Next-FP4-Local`, revision
  `fc694b54fb0174e0913e6adf86691ef85a4ead47`; temperature 0; thinking disabled.
- Candidate requested settings include `direct_content_delivery: true` and
  `reduced_tutor_harness: true`. Baseline direct delivery was false.
- Retrieved course revision:
  `24db6bf0d4e4ebfa1331e6c772e1844cbaf2d9aa`.
- The manifest identifies the precise dirty source state. In particular, the
  candidate CGA prompt hash is
  `2cc2a98fb1bdfeb8a31f1bc511303b9e195a3b38eeea15900bf75bce4fa4c84f`,
  and its conversation middleware hash is
  `a4988f6aef1ce0cb51556a67982e9684062a9a9ed7cbc16c9deab419443bd869`.
  Later local changes are not evidence about this run.

| Whole nine-turn script | Baseline | Candidate v1 |
|---|---:|---:|
| Sum of recorded turn durations, excluding startup | 430.95 s | 403.82 s |
| Logical model calls | 56 | 72 |
| Actual student-model writes | 0 | 4 |

The observed total duration is about 6.3% lower, but the routes and work differ.
The candidate invokes UCA in three episodes and recovers from three malformed
subagent requests. This is not an isolated causal estimate of the direct-delivery
optimization, a reliability estimate, or quality acceptance. The first three
candidate final replies exactly equal their raw CGA content. Removing the rewrite
therefore makes child quality directly consequential.

All locators below are zero-based paths into the candidate report. Parse a task
checkpoint message's `content` once to inspect its structured CGA or UCA fields.
Historical messages repeated in later observations are not new generations.
Word counts use whitespace splitting, not a semantic brevity metric.

| Case | Judgment | Principal evidence |
|---|---|---|
| `concise-explanation` | Revise | Passing tests are bounded; response remains long and overstates universal change impact. |
| `single-practice` | Visible answer boundary passes; critical private-rubric defect | Signature, storage shape, and internal aliasing are conflated; accepted alternatives contradict rejection criteria. |
| `map-defensive-copy` | Major repair observed; revise precision and grounding | Valid alternative accepted; method-level change claim and citation provenance remain too strong. |
| `socratic-pressure` | Critical failure | Target conclusion and replacement code disclosed; mutable list called immutable; test-proof overclaim returns. |
| `missing-prerequisite` | Critical selected-mode failure; assessment limitations | Solved analogy and direct lecture replace the selected contract; provisional floor is not demonstrated recall. |
| `accessibility-stop` | Revise initial probe; stopping passes | Spanish maintained, but probe is long and compound; no instruction continues after stop. |

## Concise explanation

The response correctly answers the test question:

> "No — passing the existing client tests after swapping storage is only evidence for the cases those tests exercise."

The baseline's explicit assertion that a failed swap definitely proves a leak is
absent in this turn. That is an observed improvement, not evidence that the rule
is robust across contexts: the pressure response below still makes a passing-test
overclaim.

The explanation still says a storage change "now ripples into every caller" and
ends by asking whether "only this module would need editing." A revealed private
type creates dependence, but the presented examples do not establish that every
caller must change for every storage replacement. The change-impact check needs
its scope: a selected private decision changes while the intended public contract
is preserved. Public requirement changes and ordinary implementation bugs are
different reasons for edits.

There are two paragraphs, but 206 words and many competing examples: SQLite,
dicts, GPA policy, email lookup, user ordering, raw rows, collection types, error
details, and mutable aliases. This does not meet the intended concise explanation
well. The captured prompt asks for at most 120 words unless correctness requires
more; this breadth is not necessary to answer the question accurately.

Evidence: `cases[0].profile.turns[0].response`; identical child
`cases[0].observations[0].messages[7].content`. The overbroad source check appears
in `cases[0].profile.turns[0].metrics.tools[1].output.content`, chunk 2. The
implementation-swap wording is in that tool's chunk 4.

## Single practice question

The visible question asks for one decision with a reason, and withholds the
answer. However, its target is imprecise. The code returns `_records`, the actual
internal list, but the question asks whether to retain the function's **signature
and return type**. Changing an implementation's aliasing behavior and changing
its public type are different decisions.

The private rubric says:

> "incorrect — Says the signature should stay as is because the module can just swap SQLite in behind it"

It also accepts:

> "return an immutable/copy view rather than the internal list"

A SQLite implementation can construct a new `list[dict]` containing intentional
domain fields such as `gpa` and `major`. That can preserve the displayed client
and signature while eliminating the internal-container alias. Whether callers
are promised a live view, a detached snapshot, or mutation through the return
value needs to be stated; a return annotation alone does not settle it. The
rubric's unconditional rejection therefore conflicts with a defensible answer
and with its own accepted-alternatives paragraph.

The rubric also claims that "every client that reads dict keys or relies on the
returned list must change too." A private storage replacement does not entail
changing intentionally stable public keys. This repeats the underlying baseline
Map error inside assessment material, despite fixing the direct Map response.

This is a critical private-rubric defect and a concrete misgrading risk. No answer
was submitted against it, so this report does not claim an observed misgrade.
The correct repair is to align the stem's decision with the rubric: ask about the
internal alias, or accept a preserved signature backed by a suitable stable
adapter/snapshot. Appending another generic "accept alternatives" sentence will
not reconcile contradictory grading conditions.

Evidence: `cases[1].profile.turns[0].response`; child and parsed rubric
`cases[1].observations[0].messages[5].content`. Relevant source distinctions are
the `List<Order>` versus `MySQLResultSet` and internal-list examples at
`cases[1].profile.turns[0].metrics.tools[7].output.content`, chunk 3. The
one-module heuristic appears in the same turn's `tools[1].output.content`,
chunk 3. The recorded assessment is `{}`.

## Map defensive copy

The candidate now accepts the stated contract:

> "Yes — for the contract as you stated it, `new Map(internalBalances)` does the job."

It explains the separate outer container, distinguishes nested object references,
and accepts the intentionally public Map interface while keeping private storage
replaceable. This repairs the principal baseline error.

Two qualifications remain. "Your isolation claim holds only because of that
premise" overstates the role of primitive values: inserting or deleting entries
in the copied container is isolated even if values are objects; primitives avoid
the additional nested-value mutation path. Also, replacing storage need not
change "only this method." It can require edits elsewhere inside the module while
preserving its public contract. The defensible claim concerns client independence,
not an exact count of internal methods or classes edited.

The retrieved passages support information hiding and Python shallow copying;
they do not establish the JavaScript Map constructor behavior. That behavior was
separately checked locally during this review work, including the nested-object
counterexample, but that check is not model retrieval evidence. The candidate
reports `coverage_gap: null`. All four generated source URLs also substitute
`HEAD` for the actual retrieved revision. These are provenance and grounding
issues even though the central technical answer is correct.

Evidence: final `cases[2].profile.turns[0].response`; identical child, sources,
and gap at `cases[2].observations[0].messages[6].content`. Python copying is in
`cases[2].profile.turns[0].metrics.tools[5].output.content`, chunks 2–3; intentional
contract information is in `tools[7].output.content`, chunks 2 and 4. Actual
retrieved URLs in these results are revision-pinned.

## Socratic pressure

The initial response offers a change-impact probe. It retains some reasoning work
but is 81 words and asks both how many places change and how to decide. Its
one-class heuristic inherits the source qualification problem. The UCA assessment
from this turn is examined below.

The pressure turn is a clear failure of the selected assistance contract:

> "Understood — here's the conclusion directly, with the reasoning so you can reuse it."

It gives "Your idea isn't enough," a diagnosis, and replacement code. The learner
had selected no-answer Socratic help, and the fixed pressure turn explicitly
tries to extract a repair or equivalent solved example. The captured CGA prompt
already says to preserve that contract under such pressure. Both child and final
response violate it; this is not merely a parent rewrite defect.

The response also promises a "fresh, immutable collection" but returns:

```python
return [Record(r.id, r.value) for r in self._internalRecords]
```

That expression creates a mutable list. It says nothing about whether `Record`
is immutable or whether `r.value` shares mutable objects. Finally, the response
states:

> "If the client still compiles and passes, the secret is hidden."

This again promotes a bounded implementation-swap check into an unqualified
conclusion. It shows that the initial explanation's repair does not generalize to
this pressure context.

Evidence: first child `cases[3].observations[0].messages[9].content`; pressure
child `cases[3].observations[1].messages[15].content`; final pressure reply
`cases[3].profile.turns[1].response`. The task input at that turn's
`metrics.tools[1].input` chooses `explain_at_tier` despite the earlier selected
contract. Course heuristics and internal-alias material recur in
`metrics.tools[3].output.content`, chunks 1–4; they do not make a Python list
immutable.

## Missing prerequisite

The first reply says "I won't hand you the solution," then supplies the central
outlet analogy: socket shape and voltage are the visible guarantees; the power
source may change behind them. It asks the learner to restate what the analogy
has already supplied. This changes support compared with the baseline's guess
request, but it is a worked conceptual explanation under a selected no-solution
contract, not an unsolved prerequisite check.

The next reply explicitly changes the interaction:

> "Fair — let's drop the questions for a moment and just name the terms."

It defines module, interface, implementation, and information hiding, then maps
the outlet and iceberg to the answer. Direct instruction could be appropriate in
an explanation mode; this episode did not explicitly change the selected
assistance contract. The fixture permits an honest resource/support change, not
an unannounced target explanation. This remains a critical selected-mode failure.
It is not a claim that explaining prerequisites is inherently poor teaching.

The definitions and analogy have real retrieved course support. The defect is
their use under the selected contract, together with overclaims about what the
learner demonstrated. Source consistency does not establish compliance with an
assistance boundary.

Evidence: `cases[4].profile.turns[0].response` and `turns[1].response`; children at
`cases[4].observations[0].messages[10].content` and
`cases[4].observations[1].messages[16].content`. The second child starts "Sure"
where the parent says "Fair"; the substantive lecture remains. The first turn's
`metrics.tools[8].output.content` includes the module anatomy and outlet analogy;
the second turn's `metrics.tools[5].output.content` and `tools[6].output.content`
support the definitions and summary. Actual assessment evidence follows below.

## Accessibility and stopping

The first reply stays in Spanish and supplies a concrete Java getter example.
It is 84 words, with an introductory assurance, a scenario, and a compound query
about edit count and cause. The final contrast between the private field and the
public method type strongly cues the expected reasoning. This is more leading
and longer than the requested single short question, but it does not explicitly
state the final conclusion as the pressure response does. Review it as a
revision, without equating all hints with a complete answer.

The source scenario also changes the public requirement from an integer ISBN to
one containing hyphens. That is not automatically the same test as replacing
private storage while preserving public requirements. The source's universal
one-class diagnostic needs this distinction before being used as a grading rule.

The second reply begins:

> "Entendido — paramos aquí. No hay más preguntas ni ejercicios."

It imposes no question, reflection, or further task; `metrics.tools` is empty.
Stopping passes. The low-confidence stored assessment remains unchanged, and the
stop request does not trigger a further update.

Evidence: `cases[5].profile.turns[0].response`; child
`cases[5].observations[0].messages[10].content`; stop reply
`cases[5].profile.turns[1].response`. The Java getter example is retrieved at
the first turn's `metrics.tools[8].output.content`, chunk 3.

## What the actual UCA state establishes

Four update calls persist real synthetic assessment entries. All have low
confidence and no `answer_judgment`; these are not graded answer submissions.
They demonstrate execution and persistence, not calibrated assessment accuracy.

| Episode and turn | Stored tier | Update locator | Structured UCA checkpoint |
|---|---|---|---|
| Socratic 0 | Understand | `cases[3].profile.turns[0].metrics.tools[5]` | `cases[3].observations[0].messages[7].content` |
| Prerequisite 0 | Remember | `cases[4].profile.turns[0].metrics.tools[5]` | `cases[4].observations[0].messages[8].content` |
| Prerequisite 1 | Remember | `cases[4].profile.turns[1].metrics.tools[3]` | `cases[4].observations[1].messages[14].content` |
| Spanish 0 | Remember | `cases[5].profile.turns[0].metrics.tools[5]` | `cases[5].observations[0].messages[8].content` |

For each row, the actual persisted entry is also present at
`cases[i].observations[j].assessment_state["information-hiding"]`. The prerequisite
entry advances from assessment count 1 to 2; the other two remain at 1. The first
three episodes still have empty assessment state.

**Task framing is not an explanatory demonstration.** The Socratic UCA says the
student frames the exercise as an abstraction question, "showing they grasp the
concept at an explanatory level." The learner stated the assigned task and the
misconception that a private field suffices; they did not give an explanation of
the boundary. The estimate is explicitly provisional and low confidence, but its
positive evidence attribution remains unsupported.

**A provisional floor is not demonstrated recall.** The prerequisite UCA records
`Remember` while saying no probe has been answered. On the second turn the saved
rationale says "no demonstration above bare recall of the task vocabulary."
Neither turn demonstrates a correct definition or recalled fact. The rationale
can truthfully say there is no usable demonstration yet; it cannot turn the
mandatory floor label into observed attainment. The Spanish rationale similarly
draws positive attainment evidence from naming the concept inside a misconception.
It does not establish a correct account of the principle.

The schema requires a tier in both `StudentModelEntry` and `UCAOutput`, and the
prompt requires provisional writes during probing. The model's low-confidence
floor is therefore partly a representational limitation, not simply an invented
high-confidence diagnosis. Initial provisional labels are not specified by the
prompt; the later forced `Remember` fallback after unsuccessful probing is a
different rule. This report does not treat protocol compliance as evidence that
the learner attained that tier.

**Recommended and delivered probes are confused.** In prerequisite turn 0 the
UCA recommends `Apply`; the actual CGA task and output use `Understand`. In turn 1
the UCA rationale says "the Apply probe was not answerable." That describes the
recommendation rather than the delivered probe. It is an observable assessment
provenance error. The same returned rationale also says the learner could not
answer the analogy "a second time," although the record contains only one analogy
and one response to it. A code-owned question/probe record should preserve the actual
question, task demand, rubric when present, and support supplied; later assessment
must not reconstruct these from a recommendation.

**Stored and returned rationales diverge.** All four updates preserve the same
tier/confidence as their structured output, but the saved rationale and final
UCA rationale differ. For example, Socratic storage says "showing some grasp of
abstraction," whereas the returned UCA says "grasp the concept at an explanatory
level." The current prompt explicitly requires the same rationale. These are
not evidence of different tier values, but they leave two assessment accounts
where one consistent record is intended.

**Study routing remains unverified.** The context schema in this candidate carries
only `student_id`, while the orchestrator prompt demands trusted condition gating.
The run cannot establish whether these UCA invocations were authorized by a real
research assignment. The baseline/candidate difference in invocation is not a
controlled manipulation of a represented condition. Three initial requests also
send CGA-shaped JSON to UCA and recover from validation errors, visible at
`cases[3].observations[0].messages[5]`, `cases[4].observations[0].messages[6]`, and
`cases[5].observations[0].messages[6]`.

## Repairs and boundaries to evaluate next

1. **Align question and rubric decisions.** Distinguish public type/guarantees,
   internal aliasing, and private storage. Challenge a proposed gold decision with
   a valid same-signature implementation before emitting a categorical rejection.
   Keep all grading conditions consistent with accepted alternatives. Then submit
   a valid alternative against an actual generated rubric to observe grading.
2. **Qualify source heuristics.** The course's representation-leak table and
   one-module/class check must be applied to designated private decisions under a
   preserved public contract. Stable domain collections are not internal aliases.
   The canonical source passages themselves merit correction; another generic
   prompt warning cannot guarantee that an overbroad source will be used narrowly.
3. **Keep the selected assistance contract across routing.** An `explain_at_tier`
   task must not silently override selected no-answer help. Recheck both the raw
   child and student-visible reply under pressure and absent prerequisites. A
   correct explanation is not automatically appropriate in that mode.
4. **Separate evidence from labels.** A quoted task, tentative vocabulary, and
   assisted repetition are not independent demonstrations. Represent unassessed
   knowledge separately from an instructional starting tier once the assessment
   policy is decided. Until then, report the limitation; do not certify mastery.
5. **Preserve provenance.** Copy returned source URLs exactly, report uncovered
   language semantics, retain the actual delivered probe, and return the same
   assessment rationale that was persisted. Mechanical checks can validate these
   relationships, but cannot establish semantic rubric quality.

The primary agent has since implemented local source-evidence handoff and is
considering role-separated conversation injection. Neither change is measured by
this candidate report. The following is a design review, not a claim of a repair.

The candidate's `InjectConversationMiddleware` interpolates student and tutor
text into the system message. Preserving actual `HumanMessage` / `AIMessage` roles
is preferable to promoting that history into system text. It can also keep the
fixed child instruction prefix stable. The migration must preserve chronology,
selected help mode, language, stopping, and the distinction between supplied tutor
answers and student work. Apply it only to outgoing requests, without duplicating
history across tool rounds or writing the injected history into graph state.

The current child task is itself delivered as a human message containing typed
JSON. A static system explanation must distinguish that internal task from the
student-history messages; otherwise the model may treat the final JSON as the
"most recent student message" or evidence of the learner's knowledge. Preserve
the validated task and actual assistant/tool exchanges intact. Student-authored
text labels must not create additional roles. Existing UCA/CGA instructions that
locate history at the end of the system prompt must be updated together with the
representation.

Check actual serialized request roles/order, one complete retrieval round,
multi-turn history without duplication, and copied-answer attribution. Source
evidence is also dynamic data: moving history alone will not stabilize a system
message if another middleware still appends retrieval there. Role separation is
not proof of resistance to embedded instructions, a cache-speed improvement, or
preservation of the Socratic contract; those require the corresponding observed
behavior checks.

These fixed scripts remain narrow information-hiding scenarios. One successful
execution and isolated repairs cannot establish reliability across the curriculum,
sound generated rubrics, calibrated tiers, real novice uptake, retention, or
transfer. The assessment fixtures provide a separate component characterization
path, but they do not resolve research-condition policy or prove learner benefit.

## Separate UCA component baseline follow-up

This section reviews `output/profiling/assessment-baseline-v1.json`, **not** the
tutoring candidate report used above. Its SHA-256 is
`692d7e8620cdd2d669cc01554fd999c2764abcda1413386631497cb8a1ee0452`.
The run covers all eight reviewed assessment fixtures, one repetition each, from
2026-10-18 10:36:27–10:38:59 UTC. Its fixture hash is
`3f531d4e58fd9c0ab055f5c1990cc22d53fc62d20007a34715df1d236e124216`.
The captured UCA prompt and conversation-middleware hashes match those recorded
above. Subsequent local repairs have not been measured by this report.

The report explicitly sets `component_only: true` and
`orchestrator_routing_evaluated: false`. A deterministic parent dispatches the
existing UCA with synthetic conversation, a supplied task/rubric, and a disposable
prior where applicable. The captured initial human task for every case equals
its `uca_input`; reviewer expectations are not part of that task. History is still
in the captured system message in this run. No control or experimental assignment
can be inferred from these component calls.

**The run fails a real consistency contract, not inference execution.** Each case
has a structured UCA result and exactly one successful persisted update. The
stored tier and confidence match the structured output, but the rationale is
regenerated with different wording. For all eight observations,
`persistence.checks.output_matches_store` is false, while the other seven recorded
checks are true: one update, saved entry, present output, only target concept,
correct assessment count, correct student turn, and correct prior tier. No model
error or output truncation is recorded. All eight `execution: "failed"` labels
must remain visible; they do not mean that all eight answers were misgraded.

The same-rationale requirement is explicit in the UCA prompt. Even where the two
versions are close paraphrases, different saved and returned accounts undermine a
single auditable assessment record. A narrow repair is to have one finalized
assessment object supply both persisted and returned fields, with raw generated
evidence retained for inspection. Silently loosening the check would conceal the
current mismatch; changing Bloom policy is not required to fix this bookkeeping.

The following zero-based locators now refer to the **assessment baseline**. For
case `i`, the reviewed output is `cases[i].observations[0].uca_output`; its actual
before/after state is in `store_before` and `store_after` at that same observation.

| Index / case | Content judgment | Evidence review |
|---|---|---|
| 0 / `valid-map-copy` | Correct verdict supported | Accepts both copied-container isolation and preserving the public snapshot across SQL replacement; no preferred-container penalty. |
| 1 / `conceptual-syntax-slip` | Correct verdict supported | Distinguishes the conceptual domain interface from the `UserProflie` naming error, which it says must be fixed to execute. |
| 2 / `partial-test-evidence` | Partial verdict supported | Credits the bounded passing-test inference and identifies the unsupported definite-leak diagnosis. |
| 3 / `confident-test-overclaim` | Incorrect verdict supported; revise rationale | Identifies both false inferences, but claims accurate vocabulary use as positive evidence despite its use inside false conceptual statements. |
| 4 / `practice-with-prior` | No answer judgment, as expected | Preserves Apply and explicitly reports no new demonstration; lowers confidence to low while carrying the prior. |
| 5 / `cold-start-no-evidence` | No answer judgment; protocol behavior observed | Records provisional Remember/low with next probe Apply, explicitly saying the request carries no evidence. Unassessed-tier representation remains unresolved. |
| 6 / `copied-answer` | Correct content verdict supported; revise recall claim | Recognizes copying, preserves the prior, and rejects independent application, but still calls the copy evidence of recall. |
| 7 / `changed-item-after-support` | Correct verdict supported | Credits the changed snapshot/cursor reasoning and excludes the earlier supplied answer as new evidence. |

The six submitted-answer verdicts match the explicit criteria on inspection; this
is not a general grading-accuracy estimate. These are deliberately supplied
rubrics with task premises, not independently generated rubrics. The component
success on valid alternatives does not repair the contradictory generated rubric
in the tutoring episode. The typo case concerns one identifier spelling error in
conceptual pseudocode, not arbitrary syntax or runtime errors.

**Correct evidence distinctions are visible.** Case 2's note separates the two
criteria: the answer "rejects universal proof from a finite passing suite" but
"claims failure 'definitely proves' a leak." Case 1 explicitly treats the typo
separately from interface reasoning. Case 7 credits the new response's explanation
that the domain snapshot can be constructed from either storage and that quantity
is needed public information; it excludes the earlier verbatim answer. These are
useful observed assessment behaviors.

**Copied content still is not demonstrated recall.** Case 6 correctly assigns the
content verdict `correct`, recognizes the earlier supplied answer, and does not
raise the seeded Understand tier. But its rationale says:

> "it evidences recall of the correct distinction, not independent application."

The answer is visibly available to copy; recall from memory has not been tested.
The saved rationale similarly says it "demonstrates recall/copying." Replace this
inference with the observation that the content is correct but no fresh
independent demonstration is available. Do not infer either learning or nonlearning
from the copy. This is an evidence-calibration revision, not an observed upgrade
to independent mastery or an incorrect content grade.

**Terminology inside an error is not a demonstrated explanation.** Case 3's
rationale says the learner "uses the correct leak vocabulary accurately" while
the quoted answer makes both false universal claims. Keeping the seeded prior
may be reasonable because one unsuccessful higher-demand task does not establish
absence of lower knowledge. The rationale should rely on that prior and the
limited diagnostic reach of this answer, rather than treating its terminology as
fresh positive evidence of conceptual understanding.

**The empty cold start is candid about missing evidence.** Case 5 says:

> "the student's only message is a practice request ... which carries no evidence of understanding."

The omitted text is the quoted request, not a qualification. Its provisional
Remember value and low confidence follow the current representational constraint;
the first-probe recommendation is Apply. There is no claim here that recall was
demonstrated. Case 4 also states the prior is a synthetic seed rather than observed
in this vignette. Neither behavior validates the broader policy for staleness,
confidence decay, or a forced tier when knowledge is unassessed.

Cases 0, 1, and 7 update the prior Understand tier to Evaluate with medium
confidence. The output ties those labels to criterion-based design reasoning and
limits confidence because evidence is a single answer. The fixtures intentionally
do not specify exact Bloom gold labels for these responses. These traces permit
review of the rationale, not certification that the tier transition or confidence
scale is calibrated.

Relevant actual retrieval is preserved, rather than replaced by the fixture's
reviewer snippets. Case 1's domain-interface example appears in
`cases[1].observations[0].metrics.tools[2].output.content`, chunk 1. The test cases
retrieve the implementation-swap passage at cases 2 and 3, tool 2, chunk 1, while
their rubrics and task counterexample supply the explicit bounded-inference
criteria. Case 7's tool 3, chunks 1–4, supports intentional public contract facts.
Map constructor behavior is stipulated in the task, so no JavaScript retrieval
claim is needed for this component question. These distinctions are narrower
than the original tutoring Map request, which asked to review the learner's claim.

Across these eight different vignettes, the observed inclusive assessment spans
sum to 147.84 seconds, with 29 actual UCA model calls. Their median is 18.57 seconds
and range is 10.32–26.00 seconds. Synthetic parent calls and startup are excluded
from those figures. This is one descriptive baseline with different task lengths,
not a comparative speed result or evidence of educational effectiveness. Fixing
consistency and rerunning targeted cases can establish whether that invariant
holds; repeated blinded review and learner evidence remain separate work.

The component findings do not reverse the tutoring candidate's rejection, certify
production routing, or choose a research condition. They isolate useful grading
behavior, a systematic save/return mismatch, and narrower evidence-calibration
problems that can now be checked independently.

# Tutoring candidate v7 semantic review

**Not accepted for tutoring quality.** All nine turns complete, the focused CGA
prompts are present in the actual requests, and the observed assessment writes
match their typed outputs. Nevertheless, answer pressure still produces the
target conclusion and repair directions. The explanation teaches an overbroad
sufficiency rule, Map feedback confuses public representation with private
storage, and the practice rubric has overlapping grading categories. Successful
execution and a smaller prompt do not resolve these semantic defects.

This is an explicit Codex review dated 2026-10-18, using the unchanged synthetic
fixture criteria, actual public replies, child outputs, private rubrics,
retrievals, requests, and stored assessment state. The execution report remains
untouched with `quality: "not_reviewed"`; this document records the review.
No inference or runtime edits were performed during review.

## Evidence identity and scope

- Canonical report: [tutoring-candidate-v7.json](../output/profiling/tutoring-candidate-v7.json).
- SHA-256: `0fc763d19028500f784b49b57c311c50f1832d19851a76fb52d59290dd7b2f0e`.
- Six episodes, nine turns, one repetition each; execution completed for all nine.
  The report starts at `2026-10-18T12:32:50.618831+00:00`.
- The first four cases are parsed-equal to the earlier reviewed partial report,
  whose byte SHA-256 is
  `b00917952d64efd083c73f274a61ba3c7aeba15c16fff8d1e2efc899a4e828ba`.
- Actual configuration: Flash-Next revision
  `fc694b54fb0174e0913e6adf86691ef85a4ead47`, SGLang 0.5.21, temperature zero,
  thinking disabled, 32,768 context, 4,096 output limit, buffered responses.
  The server reports 20 recurrent-state cache slots and MTP configuration.
- Reduced tutor harness, direct content delivery, source reuse, deterministic
  assessment persistence, required content after assessment, and serial child
  tool calls are enabled. The run includes typed task descriptions, focused CGA
  prompts, and the parallel-context compatibility repair. These co-occurring
  changes prevent attributing outcomes to prompt selection alone.
- Retrieved URLs identify course revision
  `24db6bf0d4e4ebfa1331e6c772e1844cbaf2d9aa`; the full corpus is not snapshotted.

Selected hashes from `manifest.source_sha256`:

| File | SHA-256 |
|---|---|
| `tests/fixtures/tutoring_cases.json` | `dfb46e5ee98faa1ff1fa20e55a6d6331a6295e51e0b6b137a2c09b7a23e85649` |
| `src/edbot/prompts/cga_prompt.md` | `a828e109e329986f945d78b864c7f69444f059c5c0812847286cb0974c4ecca9` |
| `src/edbot/prompts/uca_prompt.md` | `f945b6811ba4adfcd1268090253b11a1e7b59ffbf344330dcabf29fcdfff7e47` |
| `src/edbot/prompts/orchestrator_prompt.md` | `fb52f4f03feb8ca267b59b16a2e0b3fe91c85bb7fe6d7ac2d9f22f4e25919bbf` |
| `src/edbot/interface_def.py` | `8fac60f005addc370727dffe2a523ff2a5e78005e61736a277db57f79bcc69cf` |
| `src/edbot/middleware/focused_cga_prompt.py` | `dfa9117ed5260cecbbfcb854fac86aef4cc46dbdf1359f954c75521472279f56` |
| `src/edbot/middleware/conversation_history.py` | `b0e560feeb00a0441c934ce5cd6ccee9eb2315d75efcb1fae2d33197548075c5` |
| `src/edbot/middleware/direct_content.py` | `f296f6087dc32b20a2eedb014ca1d6c4123bcb765fe529c71aabfa11b47fad01` |
| `scripts/evaluate_tutoring.py` | `0d197350b3ad63dea337a7639139521a2196fda2aa10ea06eb664ac6a2a27f2b` |

The selected-case hash is
`ea74220aa4b5826cffd5dcb986e16f1ed43ce5e423ebe3d9adb203a4a8057220`.
Both fixture and selected-case hashes match the baseline. Criteria were not
changed to accommodate these outputs.

All locators below are zero-based. `T(i,j)` denotes
`cases[i].profile.turns[j]`; `M(k)` and `R(k)` denote that turn's
`metrics.model_calls[k]` and `metrics.tools[k]`. CGA/UCA fields are the matching
output tool call's `args` in `output_message.tool_calls`. Assessment snapshots
are `cases[i].observations[j].assessment_state`. Request hashes identify captured
messages and allowlisted callback parameters, not separately recorded wire bytes.

## Judgments

| Turn | Seconds | Model calls | Final words | Judgment |
|---|---:|---:|---:|---|
| Explanation | 35.338 | 5 | 208 | Critical accuracy overclaim; revise brevity. Bounded test claim passes. |
| Practice | 39.843 | 5 | 128 | Revise private rubric and stated guarantees; visible answer boundary passes. |
| Map feedback | 82.849 | 9 | 282 | Revise technical accuracy and source applicability; scoped isolation verdict passes. |
| Socratic selection | 36.096 | 7 | 50 | Revise chained reasoning; answer boundary passes. |
| Socratic pressure | 34.286 | 5 | 199 | Critical answer/repair disclosure originating in CGA. |
| Prerequisite gap | 58.655 | 12 | 95 | Revise the two-part probe and support fit. |
| Still stuck | 41.937 | 8 | 171 | Support change, source grounding, and answer boundary pass in this observation. |
| Spanish question | 24.653 | 4 | 78 | Revise brevity and focus; Spanish and answer boundary pass. |
| Stop | 1.877 | 1 | 21 | Pass: brief Spanish closure with no further instruction. |

Words are counted by whitespace splitting. These counts describe outputs; they
are not a quality score. One question mark does not establish one reasoning step.
The explanation's critical classification follows its fixture's explicit false-
claim criterion. The Map's important technical error is recorded without claiming
that it triggered the fixture's distinct invalid-rejection or deep-copy failures.

## Explanation and practice

**Explanation.** `T(0,0).M(4)` says:

> “As long as nothing in those signatures or return values names the backing container, the storage decision lives in exactly one place”

It then guarantees that swapping storage edits only that module. This treats
absence of a storage name as sufficient for hiding the decision. An interface
can omit that name while exposing backend-specific errors, ordering, aliases,
or other guarantees. The response's own second paragraph recognizes untested
ordering and mutability concerns, so the earlier universal claim is also
internally inconsistent. The necessary condition is preservation of the relevant
public promises, not merely names and signatures.

`R(0)`, chunks 2–3, explicitly covers errors, ordering guarantees, flags, and
stable intentional information. The retrieved material does not support this
narrowed sufficiency rule. The finite-test statement is sound: passing tests is
“evidence for the cases they actually exercise”; a failure can reflect a leak,
implementation bug, or intentional contract change. Source URLs are returned
URLs. The 208-word final is exactly the child content, with two long paragraphs
despite the captured 120-word concise-explanation instruction. There is no parent
rewrite to blame for either defect.

**Practice.** `T(1,0).M(3)` presents a `StudentRecords` API with domain-level
operations and asks whether moving a private dict to SQLite forces client edits.
The intended “need not force edits” answer is defensible; the question is not
classified as impossible or contradictory. The learner still makes the decision.
The child has 125 visible words and a private 150-word rubric; parent `M(4)` adds
only “Here's your question”.

The rubric expands the signature listing into an unconditional guarantee that
clients “observe the same results.” Specify the relevant behavioral promises
or accept the condition that they must be preserved. `R(3)`, chunk 3, supports
implementation freedom only while the interface keeps its promises.

The grading categories also overlap. Partially correct includes a “wrong choice
with a correct observation that no storage detail appears in the signatures”;
incorrect includes choosing client changes because storage becomes a database.
A response saying that the signatures do not expose storage but the database
change nevertheless forces client edits fits both descriptions. This is a
counterexample to rubric consistency, not an observed student misgrade. Keep
credit for a correct observation separate from the erroneous conclusion and
make the categories mutually consistent.

## Map feedback

`T(2,0).M(7)` correctly accepts the stated mutation-isolation contract and correctly
distinguishes a fresh container with primitive values from shared nested mutable
objects. It does not reject the solution because Map is mutable or falsely claim
a deep copy.

It nevertheless states:

> “switching your internals to something else means the public signature changes too.”

This is false: the public Map can be constructed from different private storage.
The response first says that storage can change without callers seeing it, then
claims the opposite because callers see a public Map type. The intentional public
representation and private backing storage are distinct. Its preference for domain
operations does not justify grading a stricter contract than the learner stated.
Parent `M(8)` retains this claim in the 282-word final; the 287-word child already
contains it.

The source evidence also needs calibration. `R(1)` and `R(4)` discuss Java and
information hiding; `R(6)` discusses Python shallow copies. Those passages do not
establish the language-specific `new Map(...)` constructor behavior. The child
sets `coverage_gap: null` and presents that behavior as established. A conditional
answer can recognize the learner's scoped reasoning while stating which language
premise is not verified by the returned sources. These sources do not establish
that private storage changes necessarily change the public type.

The UCA at `M(4)` gives a correct content verdict and saves Evaluate/medium under
`encapsulation-information-hiding`. Its rationale cites the learner's actual
criteria-based reasoning and acknowledges the single observation. This is not
proof of durable independent mastery. The concept ID differs from the other
episodes' `information-hiding`; this run does not test cross-ID continuity.

## Selected Socratic help

**Selection.** `T(3,0).M(5)` asks what adding/removing through the returned list
does to module state **and** what that means for storage abstraction. The mutation
prediction is a relevant next step, and the target conclusion is withheld. Asking
for its abstraction-level interpretation in the same turn adds a second demand.
Parent `M(6)` reproduces the 50-word child exactly. Unlike v5, this version does
not introduce an ambiguous later replacement of the returned object's backing field.

**Pressure.** `T(3,1).M(3)` begins:

> “Short answer: no — `private` on the field is not enough”

It supplies the target conclusion, explains the alias/mutation mechanism, and
suggests “a copy, or better, domain operations like `recordCount()` / `findRecord(id)`”.
Not providing one literal replacement statement does not preserve the boundary:
the conclusion and repair direction have already been supplied. Across both
replies, the learner is no longer responsible for the requested reasoning.

The same child also says every such caller breaks when private storage changes.
A compatible adapter is not ruled out by the task or retrieved passages, so the
inevitability claim is overbroad. `R(1)` and `R(2)` support concerns about exposing
mutable internals; they do not prove that every replacement must change clients.

The original Socratic request, the previous probe, and the pressure message are
all present as real human/assistant history. The actual focused system retains
the selected-mode contract and explicit explain-to-probe precedence. This is not
a missing-history or inactive-middleware failure. Request SHA:
`e534054bafd370e74be9921ee4375063b3f63b01b7756a9806c2531f0e518474`.
The child has a non-null `coverage_gap`, so parent synthesis remains available.
Parent `M(4)` reproduces the child exactly; both content hashes are
`35949728d269b2acee925e44f80c4a47043300a2c4d83eb8cd63aca5ac460d96`.

The first-turn UCA rationale at `T(3,0).M(3)` says the learner “correctly recall[s]
the private/encapsulation mechanism.” The available evidence is a false sufficiency
claim, not demonstrated correct recall of that mechanism. The low-confidence
provisional Remember value itself is not the defect: the schema requires a tier.
The pressure turn leaves this saved assessment unchanged.

## Missing prerequisites, accessibility, and stopping

**Initial prerequisite gap.** `T(4,0)` executes two CGA tasks without an intervening
learner response. The first output, `M(7)`, uses a control-panel/wiring analogy and
asks what goes wrong when the panel exposes the wiring; it is not shown to the
learner. Parent `M(8)` requests another `probe_at_tier`/Understand task with the
same input. It has the normal tool set, not the forced post-assessment-only tool
set. The trace shows repetition but does not reveal a reliable reason for it.

The delivered output is `M(10)` and is reproduced exactly by parent `M(11)`.
It defines interface/implementation, then asks which part a caller needs to know
**and why** the other part is hidden. This is a 95-word, two-part conceptual probe
for a learner who has explicitly reported absent prerequisites. Revise the next
action into a smaller attainable step or a clearly offered introductory resource.
Brief prerequisite explanation is not inherently wrong; the defect is not simply
that the response contains definitions. The definitions are supported by `R(4)`
and `R(7)`.

**Still stuck.** `T(4,1).M(6)` explicitly says “let's drop the questions for a
moment and just build the vocabulary,” then provides a source-grounded introductory
explanation and the book's outlet analogy. It finishes with an invitation to
resume when ready, without another exercise. Parent `M(7)` repeats the 171-word
child exactly. The analogy is actually present in `R(4)`, chunk 1.

This is a real support change. Unlike v5, the tutor does not explain the analogy's
answer and then ask the learner to reproduce that same answer. The original
learner has not supplied a specific module problem whose solution is revealed
here; do not invent one to classify this as a critical disclosure. The support-
change, source-grounding, and answer-boundary observations pass. This does not
prove the explanation is sufficient, retained, or understood, and 171 words is
not evidence of attainability. A shorter accessible resource could still be a
reasonable design improvement without redefining this fixture after the run.

Both prerequisite UCA outputs acknowledge no demonstrated conceptual reasoning.
The first also attributes “interface/implementation” vocabulary awareness even
though the learner mentioned only interface. The second recommends a worked
example/analogy inside the assessment rationale. These are evidence-attribution
and role-discipline concerns; there is no observed mastery promotion. The saved
Remember/low values and assessment counts 1 then 2 match the typed outputs.

**Spanish help.** `T(5,0).M(3)` is forwarded exactly, in Spanish, and withholds the
answer. Its 78 words introduce a private names field, a public `list[str]`, lowercase
normalization, a future storage change, and ask both what becomes invisible and
what remains visible. This is too diffuse for the requested one short question.
It should isolate one observation without presuming that the public list is the
backing container. The retrieved public-contract and private-field material in
`R(0)`/`R(2)` is real. No assessment is saved and no ability inference from Spanish
is observed.

**Stop.** `T(5,1)` gives a 21-word Spanish closure beginning “Entendido, lo paramos
aquí.” It uses one parent generation, no tools, no assessment, no required reflection,
and no further exercise. This boundary passes.

## Prompt-selection and execution evidence

All 18 actual CGA system messages match the locally rendered mode/tier variants
exactly. Shared rules, source constraints, output instructions, and history framing
survive. Explanation variants retain probe behavior. The following system hashes
identify the six variants actually used; these are text hashes, not token hashes.

| Mode / tier | Characters | SHA-256 |
|---|---:|---|
| explain / Apply | 12,102 | `b393f8f1d7f0ccd2281adc008519c417923c37d3e9f9f99292ce17b52fad6054` |
| generate / Apply | 12,945 | `dce88c0b7745a53057c226a03dc6f2654a11fd4cd740c78f1d5bbe760f7b56b0` |
| explain / Evaluate | 12,120 | `05815e8a72d914832d7f7a2113c728e2d961ca0d1950d464beda4edcdf7bf1fb` |
| probe / Apply | 10,434 | `8c97eb301f0a8174995eb6d6aaa76eac8b5776c49d33e9efaefefc1dfdef3d50` |
| probe / Understand | 10,443 | `66e4a6d1315a6c3be458f82bd1dfafe2be357aab096ebddf15f905bffb2f33a1` |
| explain / Understand | 12,160 | `9bc5f9da039221a193c4f3aa0a679b1af0546ffaa1b522d655d97fb47566168d` |

The Apply explanation variant is 4,804 characters (28.42%) smaller than the
16,906-character canonical prompt. This verifies selection and reduction, not
teaching quality or a causal latency improvement.

All nine captured checkpoints reproduce exactly the scripted student turns and
recorded final replies when processed by the application's public-history extractor.
All four UCA outputs match their observed saved concept, tier, confidence, and
rationale: `T(2,0).M(4)`, `T(3,0).M(3)`, `T(4,0).M(5)`, `T(4,1).M(3)`.
This establishes consistency of the captured writes, not correctness of the model's
evidence interpretation or complete research-policy compliance.

| Nine-turn run | Aggregate seconds | Model calls | Input tokens | Output tokens |
|---|---:|---:|---:|---:|
| Baseline v1 | 430.952 | 56 | 462,762 | 10,300 |
| Candidate v5 | 350.785 | 59 | 427,218 | 8,731 |
| Candidate v7 | 355.534 | 56 | 391,130 | 9,113 |

These are descriptive sums from one run each. Startup is excluded; the evaluation
wrapper adds observation overhead. Outputs, routes, retrievals, cache state, and
runtime versions differ. V7's lower total than baseline and smaller token count
cannot be attributed solely to prompt selection, and v7 is not faster than v5
on this aggregate. Nested tool/model span sums are not independent latency stages.

## Architectural finding and next discriminating experiment

The demonstrated failure is at the semantic content boundary. The request reaches
the correct content specialist, contains the public history, validates the task,
and uses the intended focused prompt, yet still supplies the prohibited answer.
The typed output's `content` remains unconstrained prose. Routing/completeness
checks cannot establish whether that prose leaves meaningful work to the learner.
Parent synthesis also provides no independent semantic protection: the critical
pressure text is copied verbatim. A second generation alone is not a review gate.

One unresolved conflict is observable, but its causal role is not proven: the
pressure task remains `explain_at_tier`, so a legitimate explanation branch and
Apply worked-example style remain available. The model must recover the prior
assistance contract and suppress that branch on every call. The first pressure
search already requests “defensive copy”; the next requests “unmodifiable copy.”
The earlier selected-Socratic turn uses `probe_at_tier` and withholds the conclusion,
but those turns differ in other ways and are not a controlled comparison.

**Recommended next experiment: change only the explicit task mode in the frozen
final pressure request.** This pre-run recommendation has now been tested:
[mode-only replay and blind review](tutoring-reasoning-evaluation.md#mode-only-socratic-pressure-experiment).
All six completed drafts failed the selected boundary; changing the mode alone
was insufficient in this captured context. The original experiment specification
follows for traceability. Compare the exact recorded request
`e534054bafd370e74be9921ee4375063b3f63b01b7756a9806c2531f0e518474` with a copy whose
actual internal task at human-message index 4 changes only
`mode: explain_at_tier` to `mode: probe_at_tier`. Keep the existing focused
explain-plus-probe system, supplied Apply tier, complete conversation, both retrieved
tool results and their call history, tools/output schema, model, and generation
settings identical. That system already contains both mode sections, making this
a task-label/action-selection ablation rather than another instruction reminder.
Changing the system variant at the same time would confound this narrower question
with removal of explanation instructions.

Use paired repetitions with alternating order and blinded semantic review against
the same boundary and attainable-question criteria. Record actual requests, outputs,
calls, tokens, and latency; if a run requests another source, retain it as incomplete
until its controlled continuation is captured, including that cost. A valid probe
label alone is not a pass. Leakage in both arms would argue against task selection
alone as a sufficient intervention. Better boundary behavior in the probe arm would
justify testing the complete mode-selection package on further selected-Socratic,
prerequisite, ordinary-explanation, and stop cases; it would not establish efficacy.

This is an offline diagnostic proposal, not a production routing policy. Existing
`probe_at_tier` has a cold-start role; silently repurposing it could alter assessment
or research behavior. Assistance selection and cognitive tier should remain distinct.
The runtime context still has no explicit study-condition field, so observed UCA
calls do not certify or identify an assigned experimental condition.

A new self-reported planning field would add structure but would not itself verify
that the resulting question is unsolved. An independent draft reviewer could enforce
a fail-closed release boundary, but it adds a generation and can reject useful
explanations or prerequisite support. Before deploying such a reviewer, evaluate
its false negatives on frozen known leaks and false positives on independently
accepted questions, ordinary explanations, resource changes, and closures. Blocking
everything or obtaining a model's self-certification is not tutoring quality.

That proposed reviewer check has now been run on ten frozen drafts; see the
[reviewer-gate diagnostic](tutoring-reasoning-evaluation.md#frozen-draft-reviewer-gate-diagnostic).
It allowed three of the five known reject cases while adding a median 10.964
seconds per review. All five allow controls were accepted, but the missed
conclusions, answer-bearing choice, and false learner attribution rule out
adopting this tested reviewer as a release gate.

The specific unresolved issues remain technical contract reasoning, grading
consistency, no-answer compliance, brevity, and evidence attribution. Another
general reminder is not a demonstrated repair. This run establishes neither
retention, transfer, student learning, reliable condition gating, nor safety across
the full tutoring system.

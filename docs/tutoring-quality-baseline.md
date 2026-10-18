# Tutoring baseline semantic review

Publication scope: raw profiling captures, transcripts, server logs, and memory traces are retained locally and omitted from this public branch. `output/profiling/` paths and named review artifacts identify local evidence, not downloadable files. Hashes preserve evidence identifiers; the raw captures are unavailable for independent inspection in this repository.

The baseline completes the nine scripted turns, but it does not satisfy the
instructional acceptance criteria. It produces consequential false diagnoses about
information hiding and abandons explicitly selected Socratic help under answer
pressure. The single practice question preserves the answer boundary, and the
Spanish stop request is respected. These are observations of one synthetic run,
not estimates of learning effectiveness or future failure rates.

This is an explicit Codex semantic review dated 2026-10-18. It evaluates the final
student-facing replies, raw content-agent outputs, retrieved passages, private
rubrics, and captured assessment state. It assigns qualitative judgments with
evidence; it does not calculate a quality score. The original execution report is
unchanged and retains its automatic `quality: "not_reviewed"` field. This document
is its companion review.

## Evidence identity and scope

- Report: `output/profiling/tutoring-baseline-v1.json`.
- Report SHA-256: `27d9ce39502960eaf29315e5cfbee49547ed917003726b7d9763740cb374255d`.
- Run interval: 2026-10-18 10:08:28–10:15:43 UTC.
- Scope inspected: all six cases, all nine turns, one repetition per case.
- Reported model: `Qwen3.8-Flash-Next-FP4-Local`, model revision
  `fc694b54fb0174e0913e6adf86691ef85a4ead47`, temperature 0, thinking disabled.
- Baseline setting: `direct_content_delivery: false`. A parent generation can
  rewrite or replace content-agent text before it reaches the student.
- Course retrieval in these episodes points to repository revision
  `24db6bf0d4e4ebfa1331e6c772e1844cbaf2d9aa`.
- Every captured assessment snapshot is `{}`. No claim about grading accuracy,
  assessment updates, mastery calibration, or research-condition enforcement can
  be established from these episodes.

Locators below are zero-based JSON paths into this exact report. For checkpoint
messages, `content` is a JSON string: parse it once to inspect the CGA `content`,
`rubric`, `sources`, and `coverage_gap` fields. Retrieval locators refer to the
numbered chunks inside a tool's output. Repeated checkpoint messages in a later
observation represent history, not an additional generation.

| Case | Student-facing judgment | Additional evidence |
|---|---|---|
| `concise-explanation` | Critical accuracy failure; revise brevity | Child and parent share the false failure diagnosis; parent shortens the child. |
| `single-practice` | Pass for the visible question and answer boundary | Private rubric needs revision before use for grading. |
| `map-defensive-copy` | Critical accuracy failure despite a correct initial verdict | Both child and parent confuse a stable public snapshot contract with private storage. |
| `socratic-pressure` | Critical selected-mode answer leakage | Child and parent supply the conclusion and replacement code. |
| `missing-prerequisite` | Critical selected-mode boundary failure; revise diagnosis | Support changes, but becomes direct teaching of the target without an authorized mode change. |
| `accessibility-stop` | Revise the initial probe; stop response passes | An earlier undisplayed child candidate creates a stronger answer-leak risk if forwarded directly. |

These categories preserve the distinction between a sound explanatory response
and a violation of explicitly selected Socratic help. Direct instruction is not
inherently a failure. The Socratic cases expressly requested a different contract.

## Concise explanation

**What works.** The parent answers the requested question and correctly says:

> "No — it's good evidence, not proof."

It distinguishes a stable interface from the hidden implementation and notes that
unexercised client assumptions can escape tests.

**Critical accuracy failure.** It also says:

> "if clients break when storage moves from SQLite to a dict, the secret definitely leaked."

The child makes the same assertion. A defective replacement implementation can
break client tests while the intended public contract and abstraction remain
unchanged. A failed swap requires diagnosis; it does not uniquely identify a
leaked assumption. This meets the case's critical criterion of confidently
teaching a false claim, even though the answer handles the passing-test direction
correctly.

The final statement, "more than this module means something's leaking," also needs
a scope condition: it applies to changing a designated hidden design decision
while preserving intended public behavior. Changed requirements, public
guarantees, or ordinary replacement bugs are not the same observation.

**Request fit.** The requested maximum was two short paragraphs. The child has
374 whitespace-delimited words, an interface code block, several paragraphs, and
a follow-up question. The parent has 259 words and still adds a third block for
the follow-up. The parent rewrite masks some verbosity; forwarding this original
child directly would not satisfy the request.

**Source consistency.** Retrieved *A Five-Step Method for Applying Information
Hiding* encourages a one-module change test, so the universal change-impact
language partly mirrors an oversimplified source rule. The retrieved *Interfaces
Are Permission to Assume* passage also says to expose the stable facts clients
genuinely need. Source adherence alone does not justify an unconditional causal
diagnosis from a failed test.

Evidence: final `cases[0].profile.turns[0].response`; child
`cases[0].observations[0].messages[6].content`; the one-module rule in
`cases[0].profile.turns[0].metrics.tools[0].output`, chunk 3; contract boundary in
the same turn's `tools[6].output`, chunk 1.

## Single practice question

**Visible response passes.** The question asks:

> "do you accept this interface as the way clients will read student records, or do you reject it and use something else? State your decision and give the reason"

It presents one application decision with a connected reason, provides enough
context, and withholds the answer. The parent preserves the child's substance.
The SQLite-specific return type makes the intended change-impact issue concrete.

**Private rubric needs revision.** Its source note describes
`UserDirectory.find_by_email` as "returning `sqlite3.Row`." The retrieved table
actually shows `UserDirectory.find_by_email(email) -> UserProfile` as the **safer**
alternative to `DatabaseWrapper.execute_sql(sql)`. This is an incorrect
attribution inside an otherwise relevant source reference.

The rubric says "every client ... now compiles against the storage technology"
and demands reasoning that the change would ripple into "the three client
modules." Dependence on SQLite is the relevant issue; proving that every client
must change is unnecessary and not established by the stem. "Compiles against" is
also an imprecise description of this Python example. Its restriction on a
dictionary replacement needs the actual abstraction contract: an intentionally
stable domain-facing dictionary need not expose the internal database row.

No learner answer was submitted in this case. These are inspectable rubric
defects and future grading risks, not an observed misgrade.

Evidence: final `cases[1].profile.turns[0].response`; child and rubric
`cases[1].observations[0].messages[4].content`; actual safer-interface table in
`cases[1].profile.turns[0].metrics.tools[0].output`, chunk 3, and `tools[4].output`,
chunk 4.

## Map defensive copy

**The initial judgment is correct.** Both outputs accept that `new Map(...)`
satisfies the stated container-mutation-isolation contract with string keys and
primitive numeric values. They distinguish this from deep copying arbitrary
objects. The primary agent separately checked primitive-container isolation and
shared nested objects with Node; that execution evidence is outside this report
and does not establish the model's source grounding.

**Critical accuracy failure.** The final answer then asserts:

> "If the internal representation later changes — different storage, balances moved behind a service, a richer money type — every caller that iterates the Map or depends on its shape breaks."

The child makes the same assertion. A module can change to a database or service
and continue producing the promised independent Map snapshot. Changing the public
Map/value contract can affect callers; changing private storage need not. The
response conflates those changes and undermines a correct, carefully bounded
learner explanation.

It invokes the source's "a getter returns an internal mutable collection" rule,
but a defensive copy is not the internal mutable collection. The learner
explicitly excluded secrecy about the public Map type. The response acknowledges
that scope, then criticizes the contract using a stronger requirement that the
exercise did not impose.

**Source consistency.** The retrieved material contrasts `MySQLResultSet` with
`List<Order>` and warns against hiding facts clients genuinely need. It does not
establish that every public collection is an implementation leak. The shallow-copy
passage retrieved here concerns Python; no inspected retrieval specifically
establishes JavaScript Map construction semantics. The JavaScript claim can be
correct while its asserted course grounding remains incomplete.

The parent retains the conceptual error and leads with "The weaker part is the
contract itself." Direct delivery does not create this error; it exposes a
child error already present. The child is 417 words; the parent is 386.

Evidence: final `cases[2].profile.turns[0].response`; child
`cases[2].observations[0].messages[5].content`; exposed-internals distinction in
`cases[2].profile.turns[0].metrics.tools[5].output`, chunks 1–2; stable public facts
in `tools[6].output`, chunk 4; Python copy passage in `tools[8].output`, chunk 3.

## Socratic help under answer pressure

**First turn needs narrowing.** The learner asks for one short question about
whether returning `internalRecords` preserves storage abstraction and supplies a
specific misconception about `private`. The tutor responds with a plausible
change scenario, but asks for multiple things: internal edits, effects of
`getRecords().add(x)`, and ordering assumptions. Meaningful learner work remains,
but the question is broader than the requested next step.

**Second turn critically violates the selected boundary.** Under pressure for the
answer and replacement statement, the parent starts:

> "Fair enough — here's the straight answer."

It supplies "Verdict: no" and:

```java
return List.copyOf(internalRecords);   // or Collections.unmodifiableList(internalRecords)
```

It then explains the distinction between a snapshot and view and supplies further
domain operations. The raw child supplies the same conclusion and repair. The
final question does not undo the disclosure. This is a completed answer and
decisive solution step, not a bounded question that preserves the selected task.

**Source consistency.** Retrieved material supports the exposed-internals concern
and coding against interface types. The recorded passages do not establish every
specific claim about `List.copyOf` and `unmodifiableList`; those details would need
separate language-level verification if accepted as instruction. Regardless of
their accuracy, source-grounded solution content would still breach this selected
assistance contract.

Evidence: final replies `cases[3].profile.turns[0].response` and
`turns[1].response`; first child
`cases[3].observations[0].messages[6].content`; answer-bearing child
`cases[3].observations[1].messages[10].content`; exposed internals in
`cases[3].profile.turns[1].metrics.tools[3].output`, chunk 2; interface-type example
in `tools[4].output`, chunk 1.

## Missing prerequisite

**The initial diagnosis is poorly used.** The learner says they have never learned
what an interface means. The tutor asks them to distinguish "interface" from
"implementation" and adds:

> "just take a guess with what the words suggest to you"

This asks for terminology the learner has explicitly reported never encountering.
Warmth does not make that question attainable. A verified introductory resource or
a smaller unsolved task should change the opportunity to learn, not merely ask for
a guess.

**Support changes, but the selected boundary is abandoned.** After the learner
again reports the gap, the tutor says:

> "let's drop the questions for a moment and just put the words down plainly"

It provides definitions, a fully explained outlet analogy, and the target
conclusion:

> "information hiding means keeping the implementation behind the interface, so other code only depends on the contract."

The closing question asks whether the already identified socket shape and voltage
are the interface or implementation. The tutor has just supplied that answer.
The child contains the same teaching sequence. The student requested a support
change, not an end to the explicitly selected no-solution Socratic contract.

This is a critical boundary failure in this mode, not a claim that definitions
and worked analogies are generally inappropriate for novices. They could be
legitimate direct instruction under an explanatory contract. Here the needed
repair is an honest resource/support handoff or an authorized change of mode.

**Source consistency.** The definitions, iceberg, and outlet analogy are present
in the retrieved *Anatomy of a Module* passages. No resource fabrication is
observed. The main failure is adaptation within the selected assistance contract,
not absence of retrieval.

Evidence: finals `cases[4].profile.turns[0].response` and `turns[1].response`;
children `cases[4].observations[0].messages[5].content` and
`cases[4].observations[1].messages[9].content`; prerequisite material already
available in `cases[4].profile.turns[0].metrics.tools[4].output`, chunks 1–2;
repeated source in turn 1 `tools[2].output`, chunks 1–2.

## Accessibility and stopping

**Language is respected; the initial probe needs revision.** The final response
is in Spanish and asks about the supplied misconception. However, it begins
"Buena intuición para empezar" after the learner claims that hiding a field
always hides storage. That risks praising incorrect content. Its 53-word prompt
asks both what is hidden and what remains exposed, followed by a request to
describe the distinction. It is a leading, compound task rather than the smallest
short question requested. The premise that something "sigue expuesta" also
partly supplies the conclusion being investigated. The severity of that implicit
disclosure warrants reviewer adjudication under the strict answer-boundary rule;
this review flags it for revision rather than equating it with the explicit
solution disclosure in the pressure case.

**Undisplayed child content creates a direct-delivery risk.** The parent requested
three CGA probes before producing the visible reply. The first candidate says:

> "Explícame con tus palabras por qué el hecho de que el campo sea privado no responde esa pregunta."

That embeds the decisive conclusion that private visibility does not answer the
storage-hiding question. Under the selected strict contract it would be an
answer-bearing prompt if delivered. The baseline did not display that exact child
text. A direct-delivery candidate can expose the first valid structured output
without the parent's later regeneration, so that first-child behavior needs an
explicit candidate check. It cannot be inferred from this baseline that the new
prompt will repeat or eliminate the failure.

**Stopping passes.** The second final reply starts:

> "Entendido, lo dejamos aquí."

It asks no more questions, assigns no reflection or exercise, and invokes no tools.
The additional invitation to return later is optional closure, not continued
instruction. A shorter closing would suffice, but the stopping boundary is met.

**Source consistency.** The retrieved *Common Misconceptions* and information-hiding
material are relevant to the private-field distinction. A source-supported
conclusion can still be revealed too early. The generic public `List<Item>`
scenario also needs care: the distinction between an internal alias and an
intentional public collection contract cannot be erased merely because both use
a List type.

Evidence: final `cases[5].profile.turns[0].response`; successive child probes at
`cases[5].observations[0].messages[4].content`, `messages[6].content`, and
`messages[8].content`; stop reply `cases[5].profile.turns[1].response`, whose
`metrics.tools` is empty.

## Candidate checks and unresolved issues

Prompt repairs are not measured by this baseline. The primary agent reports
local changes targeting brevity, bounded test claims, valid alternatives,
selected Socratic help, and stopping. Their effectiveness remains unresolved until
the candidate runs these cases. In particular:

1. Check both directions of the test claim: passing tests are bounded evidence,
   and failed tests do not uniquely diagnose a leaked secret.
2. Preserve the distinction between an intentional public snapshot contract and
   changeable private storage. Grade against the stated contract before proposing
   an optional design alternative.
3. Check the raw first child as well as the final student text. Parent rewriting
   shortened some baseline outputs; one Spanish turn used three child attempts.
4. Maintain the selected assistance contract through answer pressure and absent
   prerequisites. Change support without either indefinite guessing or an
   unannounced target-answer reveal.
5. Correct the private practice rubric and add a submitted-answer episode before
   making grading claims. These six cases do not exercise a real UCA update.
6. Review retrieval guidance that overstates one-module change rules or confuses
   purposeful public types with hidden representation. A precise source citation
   does not cure an overbroad source claim or a misapplied passage.

The full run's completion is execution evidence only. One repetition does not
establish reliability, and a future improvement on these fixed scripts would not
establish real learner benefit. The cases remain narrow, centered on information
hiding. They do not cover the whole curriculum, long-term memory, real novice
uptake, delayed retention, broad transfer, or causal learning effects. A learner
pilot must separately measure assisted performance and relevant independent
outcomes, retain accessibility support, and report uncertainty and missingness.

# CGA reasoning evaluation: blinded practice-question review

Neither condition in the initial default-xhigh comparison receives quality
acceptance. The blind review found a critical
private-rubric defect in off sample A and a critical question/rubric constraint
mismatch in on sample E. The other four outputs need narrower revisions. The
completed on trajectories cost more in this small diagnostic, without resolving
the observed grading problems. This is not evidence of a statistical failure
rate, general model superiority, or learner benefit.

## Evidence and scope

This replays one captured **CGA request at the end of a tutor turn**, for the
`single-practice/question` fixture. It is not a full tutor turn or an assessment
of orchestrator routing, UCA judgment, persistence, Socratic behavior, or actual
student learning. All data is synthetic. Report `quality` remains `not_reviewed`;
the semantic judgments below are an agent review, not an automated score.

| Evidence | SHA-256 |
| --- | --- |
| `output/profiling/cga-thinking-replay-v1.json` | `256ae68e2a1600e4da1b694142d5d8db220427e75500a01d4d0637be68dac761` |
| `output/profiling/cga-thinking-continuation-v1.json` | `c8396dac093bfba25b354fa8e542645ef2c2f1e6559d85421357308368e67cef` |
| Initial anonymous A–D file, `/tmp/edbot-cga-blind-review.json` | `e048394558359cbe17a88199f1f532d72d6bf2cfe189e03213aed0716f210dff` |
| Anonymous E–F follow-up, `/tmp/edbot-cga-blind-review-followup.json` | `c5db0153a8eb6d2b897ff8045324b0514d3948d4e567fd482bbabcefd51e1de2` |
| `output/profiling/template-controls-flash-next.json` | `ecae302b8ed26a7f80b5f01f657dbd655f9facff032c93bb04ce0183b0c8db3d` |

The replay's input report is `tutoring-candidate-v2.json`, SHA-256
`f7041f2329432ce7f4cc8a71af81f3ff10a990b1df4d7c90b572ef5fa5ccd8fb`.
Its selected request hash is
`309a545ba9979afc901b77eaf6dbcc1a9ae0f43ee46122e2c1bc69c512bb4b58`;
every initial replay has restored-input hash
`4ca20f54f18adae09ff83bf4d311a8ae460563c862ef9fe1aee8b0194118db09`.
All six captured initial HTTP payloads match exactly after removing
`chat_template_kwargs.enable_thinking`.

The pinned model is `nvidia/Qwen3.8-Flash-Next-NVFP4`, revision
`fc694b54fb0174e0913e6adf86691ef85a4ead47`, served as
`Qwen3.8-Flash-Next-FP4-Local`. Both conditions use temperature 0, 4096 maximum
completion tokens, required tool calling, and buffered HTTP responses. Both
reports verify the live model and strict tool level 2. The original graph had
streamed; this comparison holds buffered transport constant.

The on requests omit `reasoning_effort`. The separately captured pinned
`chat_template.jinja` has SHA-256
`c3cf9e34abf4f9e36c2d72165aa9c132d3e2a725b6c2586aaa3a8af9d7a81041`;
line 47 resolves missing effort to `xhigh`, and lines 51–52 supply its instruction.
Thus “on” here means **thinking enabled at the pinned template's default xhigh**,
not a generic statement about every reasoning setting. The evidence record
identifies the exact revision URL and source lines rather than a current online
template.

## Blind workflow and unchanged judgments

The reviewer first received A–D with shared request/source evidence, then E–F
with their actual additional retrieval results. Conditions, underlying reports,
and timing were not examined until both reviews were returned. Timing fields in
the follow-up were excluded from the inspection output. Only then was the
mapping disclosed and verified against the complete structured outputs. Every
anonymous output matches its mapped final output exactly; no initial search-only
result was treated as a completed practice question.

Locators below are zero-based. `R` is the replay report and `K` the continuation
report. Direct results are `R.runs[i].final_message.tool_calls[0].args`; continued
results are `K.cases[j].final_cga_output`. Quotes come from their `content` or
`rubric` fields.

| ID | Condition and locator | Blind judgment |
| --- | --- | --- |
| A | Off, `R.runs[4]` | Critical private-rubric defect |
| B | On/xhigh, `R.runs[1]` | Revise narrowly; core decision defensible |
| C | Off, `R.runs[0]` | Revise; correct central answer, overbroad rationale |
| D | Off, `R.runs[3]` | Revise; genuine vendor dependency, incomplete decision criterion |
| E | On/xhigh, `R.runs[2]` → `K.cases[0]` | Critical question/rubric constraint mismatch |
| F | On/xhigh, `R.runs[5]` → `K.cases[1]` | Revise narrowly; central technical decision sound |

**A:** The question says `get_all()` returns the internal list of dictionaries
directly, a real alias to examine. But the rubric says the interface “must stop
exposing the list-of-dictionaries representation” and marks keeping that return
representation incorrect, while also accepting a “view/copy” and any alternative
preserving the contract. An implementation can materialize a detached list of
domain-shaped dictionaries from SQLite. Removing an internal alias and changing
the public return type are different decisions. If liveness or mutation-through-
the-result was promised, that additional contract must be stated. The existing
contradictory grading boundary repeats the earlier tutoring practice failure.

**B:** “Returned in storage order” explicitly couples the public behavior to a
private choice, so changing that promise to an intentional domain order is
defensible. However, the rubric groups “the storage row shape and the storage
ordering” as the replaced secret. `[sid, name, grade]` can be stable public domain
data and can be materialized from a dictionary. Explicitly accept retaining the
method/return shape while defining the public order independently of storage.
An adapter preserving current observations does not itself eliminate a contract
that still names storage order.

**C:** Keeping the public tuple/list returns across a dictionary-backed
implementation is a correct central answer. The rationale nevertheless says
exposing the new structure forces “every caller to change when the storage
changes again.” An intentional public dictionary snapshot can also remain
stable across later private changes. The exception allowing a `StudentRecord`
replacement needs its own purpose and compatibility explanation; choosing a
preferred domain class does not automatically preserve the existing contract.

**D:** `sqlite3.Row` genuinely names a vendor-specific public dependency. The
ordinary name “rows” alone does not establish that dependency, and GPA ordering
can be intentional domain behavior. The rubric rejects every unchanged-signature
answer while saying the storage simulation should edit only the module. A public
type redesign may require client edits now to permit later local migrations.
State whether the criterion is eliminating public SQLite dependence or retaining
compatibility during this migration; those are different goals.

**E:** The question requires the migration to force edits in “only one module.”
Its correct answer removes or reshapes `all_rows()` **and** requires
“`GradeReporter` uses that domain-level operation instead.” That changes the
client too. If a separate preparatory refactor is intended, the question must
say so rather than exclude that cost silently. A compatible adapter is another
possibility whose validity depends on the unspecified `row_index`, alias, and
liveness promises. The private alias is a real concern; it does not make the
gold answer satisfy the one-module constraint as written.

**F:** The question expressly promises `list[Student]` in **enrollment order**,
then contrasts preserving that promise with returning the underlying dictionary.
The correct answer accepts a freshly built list. This distinguishes public
contract, backing container, and alias well. The rubric still assigns overlapping
categories: partially correct includes exposing the dictionary while keeping
order, whereas incorrect includes “return the underlying dict.” An ordered
underlying-dictionary answer can meet both descriptions. Also, “a different public
container” is acceptable only if it preserves the full promised list-compatible
behavior, not merely iteration order.

All six leave the answer private and ask one main decision with a reason. The
rubrics have 157/164/171/222/156/163 whitespace-delimited words for A–F; exceeding
the normal 150-word guidance is secondary to the grading defects. These are
artifact findings, not observed student misgrades.

## Sources and completion paths

Every initial request contains the same four course chunks: the five-step
method, interface-as-permission-to-assume examples, the tutorial's operational
swap-test oracle, and the stable-interface/wall-outlet explanation. All output
source URLs retain revision `24db6bf0d4e4ebfa1331e6c772e1844cbaf2d9aa`.
The evidence supports examining specific dependencies and preserving deliberate
public promises. It does not establish that every public container is the private
backing representation or that every migration necessarily changes every client.

E and F initially request two searches each. The continuation executes those
searches against the existing read-only course store and performs one additional
generation per case. No source synchronization or index rebuild is part of the
continuation. Recorded store SHA-256 is
`4c2127ecb26414270b97b81f1e714ca685ade81731c319e259191e7900bc2096`.

E's actual extra source results are `K.cases[0].tools[0:2]`: change-impact
analysis and mostly unrelated follow-up snippets. The change-impact passage says
to count the affected modules and “Ideally one”; it does not justify omitting
the client edit required by E's proposed redesign. F's extra results are
`K.cases[1].tools[0:2]`: change-impact/module-guide material and stable-interface
examples. The module-guide excerpt explicitly distinguishes absorbed changes
from changes that legitimately affect the interface or neighboring modules.
The exact queries, returned passages, and their SHA-256 values remain in those
tool records and matched the evidence reviewed blind.

All eight model generations finish with valid tool calls; no recorded error,
truncation, or invalid tool call occurs. There is one HTTP attempt per generation,
so this pair contains no retry cost. Initial replay `execution: completed`
describes those six requests; only four initially supply final CGA outputs.
E and F become complete only after their continuations.

## Observed cost to a complete CGA output

| ID | Condition | Initial seconds | Complete tail seconds | Model calls / searches | Input tokens | Output tokens |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| C | Off | 23.77 | 23.77 | 1 / 0 | 6,889 | 702 |
| B | On/xhigh | 98.35 | 98.35 | 1 / 0 | 6,925 | 2,541 |
| E | On/xhigh | 6.24 | 97.72 | 2 / 2 | 15,502 | 2,689 |
| D | Off | 29.95 | 29.95 | 1 / 0 | 6,889 | 739 |
| A | Off | 20.65 | 20.65 | 1 / 0 | 6,889 | 615 |
| F | On/xhigh | 5.57 | 61.48 | 2 / 2 | 15,812 | 1,744 |

For E/F, complete tail time is initial generation plus continuation wall time,
including searches. It **excludes the shared 1.533-second continuation setup and
the idle interruption between initial replay and continuation**. These are
combined active trajectory spans, not continuous learner waiting times. They
also exclude all earlier parent/child work in a full tutoring turn.

Across the three completed outputs per condition, off records 74.37 seconds,
3 model calls, 20,667 input tokens, and 2,056 output tokens. On records 257.55
seconds, 5 model calls, 38,239 input tokens, and 6,974 output tokens. Medians are
23.77 and 97.72 seconds respectively. Output tokens are the provider's complete
generation counts, not student-visible word counts; no separate reasoning-token
breakdown is reported. Missing cache-detail fields must not be read as zero.

The initial order is off/on, on/off, off/on. Cache occupancy is uncontrolled,
the two search continuations occur later, and each condition has only three
replays of the same fixture. Later source evidence differs because on requests
additional retrieval. Therefore the observations characterize this controlled
initial request and its completed tails; they do not isolate every latency cause
or establish performance across the tutor.

## Decision boundary

The completed default-xhigh outputs do not justify enabling that setting as a
quality remedy on this evidence. A sound candidate must first produce coherent
question/rubric pairs: distinguish public promises from private representations,
check a compatible-adapter counterexample, count preparatory client edits
honestly, and give partial/incorrect categories disjoint boundaries. These
criteria apply to both conditions.

Any subsequent reasoning configuration needs its actual completed outputs and
costs reviewed under the same criteria. This report makes no claim about an
unmeasured setting, full-agent behavior, learner retention, or transfer, and
changes no production prompt, code, schema, or research policy.

## Separate low-effort comparison

The later low-effort comparison uses the same captured practice request and
shared source evidence. Its anonymous G–L outputs were reviewed before their
condition mapping, raw report, or timings were opened. The blind judgments
below remain unchanged after unblinding, and every anonymous output matches its
mapped final structured output exactly.

- Report: `output/profiling/cga-low-thinking-replay-v1.json`, SHA-256
  `4db6b86508f44007a3ed0bce16db19454898954e6a4f44f9edd62bbfa1b33427`.
- Anonymous review input: `/tmp/edbot-cga-low-blind-review.json`, SHA-256
  `3932eceb66fb4464b6fd925f123dfbe6b35716d510646fbd520f4140ff2325fa`.
- Replay script SHA-256:
  `a807de3e691b75d7acd1202788e2f1a05170aa2aaaba74f8494314c95b550154`.
- Recorded interval: 2026-10-18 11:29:29.991045–11:33:37.718011 UTC.

The original request and restored-input hashes match the earlier comparison.
All six actual HTTP payloads match after removing the two experimental template
controls. Off sends `enable_thinking: false` and no effort field. On sends
`enable_thinking: true` and `reasoning_effort: low` **inside
`chat_template_kwargs`**, not as a top-level OpenAI reasoning parameter. The
pinned template evidence above supports that setting; lines 53–54 instruct
brief reasoning. The verified model, temperature 0, 4096-token limit, required
tools, strict tool level 2, and buffered transport are otherwise unchanged.

All six calls return only a complete `CGAOutput`. There are no pending searches,
continuations, errors, invalid calls, truncations, or HTTP retries. Each output
therefore has one model generation and one HTTP attempt. The relevant raw
locator is `runs[i].final_message.tool_calls[0].args` in this low-effort report.

| ID | Condition / run | Blind judgment | Main evidence |
| --- | --- | --- | --- |
| G | On/low, run 5 | Critical constraint/grading mismatch | Removing or replacing an operation used by clients is counted as a change contained within the storage module. |
| H | Off, run 0 | Critical private-rubric defect | Says the row-shaped signature cannot survive a storage swap, although the stated data and client needs remain the same. |
| I | Off, run 4 | Critical private-rubric ambiguity | Conflates retaining a public method with retaining its internal alias and invents a storage-order guarantee. |
| J | On/low, run 2 | Pass | Stable domain operation and result across a private-container change; one decision and reason with coherent grading. |
| K | Off, run 3 | Critical private-rubric defect | Accepts an invented premise that public ID sorting reveals an ID-ordered internal structure. |
| L | On/low, run 1 | Revise | Correctly distinguishes a public list from an internal alias, but a fresh copy cannot guarantee compatibility for every possible existing caller. |

**G** asks for a migration contained within the module that does not break
clients. Its rubric removes/replaces `students_sorted_by_rowid()` and claims
“once that leak is closed, swapping list for dict only edits this module.” The
existing clients explicitly call that method and rely on its order. A
compatibility layer or preparatory client migration must be accounted for;
identifying a storage-dependent promise does not erase the transition cost.

**H** says “the current signature cannot survive the swap as-is.” Its
`StudentRow` is a raw row *shape*, not a specified live cursor or SQLite-specific
runtime object. Tree-backed code can preserve those identifiers and construct
the same shape. Redesigning exposed storage concepts may be desirable, but the
rubric incorrectly treats it as necessary for the stated backing-storage change
and would reject a compatible adapter.

**I** asks whether `get_all_rows()` should remain public, while its rubric says
“No — the method should not stay as-is.” A method can remain public and construct
a detached list of tuples instead of returning the private collection directly.
The rubric does not separate those cases. It also reasons from “list ordering”
although the question specifies no ordering guarantee. The private alias and
any actual storage-dependent guarantee should be the assessed properties.

**J** confines callers to `find_by_id(student_id) -> StudentRecord`, stipulates
that the domain result and signature stay the same, and changes only the private
list to a dictionary. Under that stated scenario, “No” with a stable-contract
explanation is supported. The question withholds the decision, asks for one
reason, and its 143-word rubric has coherent categories. Stating “same observable
behavior” would make the premise even more precise, but no substantive defect
was identified under the ordinary reading of the supplied scenario.

**K** accepts changing `get_all_names_sorted_by_id()` because it allegedly
exposes “an ID-ordered internal structure.” The stem never says the internal list
is ID-ordered. A method can compute deliberate domain sorting independently of
its backing container. The rubric incorrectly generalizes the source's
*internal-ID* example to an ID not designated internal. Accepting a correct
keep-interface answer elsewhere does not repair accepting this invented premise.

**L** correctly says “a public list type is not itself the leak — aliasing the
private backing list is.” But its question promises a swap “without editing any
caller,” and the gold accepts a fresh copy. A caller may mutate the previously
returned list to affect module state or retain it expecting a live view. A copy
changes those observations. Specify snapshot/read-only client usage or require
preservation of the stated mutation/liveness semantics; hiding the alias alone
does not prove universal compatibility.

All six preserve the supplied source URLs and keep answers private. The blind
review found **1 of 3 low-effort outputs passed versus 0 of 3 off outputs** in
this one scenario. These are descriptive counts of the reviewed artifacts,
not estimated pass probabilities or statistical evidence of a reliable gain.
Neither condition is accepted for adoption on this evidence. A passing generated
question is also not evidence of student learning or successful downstream
grading.

| ID | Condition | Complete CGA-tail seconds | Input tokens | Output tokens |
| --- | --- | ---: | ---: | ---: |
| H | Off | 24.29 | 6,889 | 706 |
| L | On/low | 64.48 | 6,913 | 1,612 |
| J | On/low | 44.74 | 6,913 | 1,245 |
| K | Off | 24.66 | 6,889 | 647 |
| I | Off | 20.14 | 6,889 | 644 |
| G | On/low | 68.90 | 6,913 | 1,718 |

Off totals **69.09 seconds, 20,667 input tokens, and 1,997 output tokens**.
Low totals **178.12 seconds, 20,739 input tokens, and 4,575 output tokens**.
Both use three model calls. Median times are 24.29 and 64.48 seconds. Low is
substantially slower in this pair: summed tail time is 2.58 times off, despite
no additional tool round trips. Reported completion-token counts include the
whole generation; they are not student-facing word counts and have no separate
reasoning breakdown.

The order again alternates off/on, on/off, off/on. Cache occupancy is uncontrolled
and some cache-detail fields are absent. This is three replays per condition of
the same initial prompt, not three independent curricular tasks. These are
complete final-request tails, not full tutoring-turn latencies. Comparing this
pair's low outputs with the earlier xhigh outputs is also descriptive: the runs
occurred at different times and the latter requested additional retrieval.

## Smallest contract correction supported by these findings

The existing CGA prompt already says public types differ from private storage
and asks for an adapter counterexample. Repeating that general advice is not a
demonstrated remedy. The following proposed question/rubric decision-boundary
correction was implemented in a subsequent, unmeasured candidate, scoped to
implementation/interface-change questions:

> State whether the question asks to preserve current client behavior during a
> private change or to redesign a public contract for future changes. Specify
> the public promises needed to decide it. Before grading a client change as
> necessary, identify a concrete permitted client action whose observable result
> the proposed implementation cannot preserve; a public shape or storage-like
> name alone is insufficient. Check whether an adapter can preserve that promise
> before requiring a public-interface change. A snapshot must not be credited as fully compatible
> when the current contract permits mutation through the result or a live view.
> Count client edits required by a preparatory interface redesign separately
> from later private changes. If the premises do not determine the answer, repair
> the question or accept an explicitly qualified answer instead of inventing a
> necessary redesign.

This implemented contract/evidence requirement is not a new output schema or an
instruction to always keep the interface. It permits a genuine alias, vendor,
or storage-order diagnosis while requiring the claimed consequence to follow
from the actual scenario. The retrieved five-step heuristic also needs that
applicability qualification: naming an intentional public representation is not
by itself proof that a private backing choice has leaked or that callers must
change.

Keep the existing semantic acceptance criteria. Check both a contract-preserving
adapter and a genuinely incompatible caller observation, including mutation or
liveness where relevant. Continue rejecting invented storage assumptions,
uncounted client migrations, and overlapping grading categories. Do not hardcode
the student-records answer, infer correctness from keywords, or relax the fixture
because a more expensive reasoning setting produced it. The subsequent candidate
remains unmeasured; these reasoning comparisons do not validate the prompt change.

### Separate selected-mode conflict found in the v4 targeted trace

The runtime trace `output/profiling/tutoring-candidate-v4-targeted.json`, SHA-256
`3148c3754319917f10f2a93f453f2b693f5646651402d3e5cbbce24f55d2c6ac`,
provides a separate diagnostic; it is not part of either reasoning comparison.
At `cases[0].profile.turns[1]`, a CGA `explain_at_tier` task produces a pressure
reply beginning “The verdict: no, `private` on the field is not enough.” The
child's initial request is `metrics.model_calls[2]`, hash
`8ce169b5c121e4477e1303b278f7284c06a9b3093aba5e68d0ab1099477696e2`.
Its actual human history includes the original selected Socratic/no-answer
instruction and the later answer-pressure message. This is not missing history.

The captured prompt has conflicting unqualified instructions: the teaching
contract preserves selected no-answer help, but `explain_at_tier` says to use
the tier's explanation style and to “correct it directly ... and explain why
it's wrong.” The Apply explanation style is a worked example. The minimal
priority repair is to **scope that existing section**: when the selected
Socratic/no-answer contract remains active, use the existing single-question
behavior at the supplied tier while retaining the required output mode; the
section's ordinary direct-correction, explanation-style, and worked-example
instructions apply only outside that contract. This avoids adding another
competing general reminder or changing the supplied tier.

That scope correction alone cannot fix the Spanish first reply at
`cases[1].profile.turns[0]`, which already uses `probe_at_tier`. It gives a
96-word scenario, asks what callers must do, then asks the learner to infer
whether hiding succeeded, then requests an explanation. Replace the existing
probe's redundant one-question wording with a tier-aware constraint: one
reasoning step appropriate to `target_tier`, without chaining a prediction,
interpretation, and further justification in one turn. The caller-change
prediction is sufficient for this Apply probe. Do not use a literal
question-mark test or a universal prohibition on asking for reasons; either
would distort other tiers. These prompt repairs were implemented in a subsequent,
unmeasured candidate. The cited v4 trace does not validate them.

## V5 Socratic pressure: low-effort reasoning remains insufficient

The [v5 full tutoring review](tutoring-quality-candidate-v5.md) subsequently
found answer leakage even with the scoped prompt repair. An isolated diagnostic
on 2026-10-18 replayed its exact pressure-turn CGA request, alternating three
thinking-off/on-low pairs. It preserved messages, tools, temperature zero,
4,096 output-token limit, buffered transport, serial tool calls, required tool
choice, client versions, and the resident twenty-state server configuration.
Only `chat_template_kwargs.enable_thinking` and the on condition's
`reasoning_effort: "low"` changed. Production thinking remains disabled.

Evidence:

- Original [v5 report](../output/profiling/tutoring-candidate-v5.json), SHA-256
  `fd8364af4bb69e53cd748bb22921213c33676086f38af5c9629f8d3a400158da`.
- Original pressure request: `socratic-pressure/pressure`, CGA call 2, SHA-256
  `6595f03770451411805abd4f37ba5a00fc53a3731e0b4a7055ea36a6e031aab1`.
- [Six exact replays](../output/profiling/socratic-low-thinking-replay-v5.json),
  SHA-256 `401fb37b700b111e2d824f64721e3b4d2b87105590a1296a49359debb005814d`.
- [Bounded off-path continuations](../output/profiling/socratic-low-thinking-continuation-v5.json),
  SHA-256 `9d98b69ba679e8133041a8b46dad2e658653d8cb632c6edbd46f13e195e652ac`.

All six first generations completed without invalid tool calls or truncation.
The three on-low generations returned `CGAOutput`; all three off generations
requested another source search. A separate continuation executed only validated
course searches against the existing read-only store at course revision
`24db6bf0d4e4ebfa1331e6c772e1844cbaf2d9aa`, without syncing or rebuilding it.
It allowed at most three additional generations per off path. Two paths produced
content; the third still requested a search at the bound and failed explicitly.
No agent graph, student store, or parent synthesis ran in this diagnostic.

| Original run | Condition | Content outcome | Model calls including continuation | Seconds including continuation | Output tokens including continuation |
| --- | --- | --- | ---: | ---: | ---: |
| 0 | Off | Complete | 4 | 37.115 | 941 |
| 1 | On, low | Complete | 1 | 71.901 | 1,846 |
| 2 | On, low | Complete | 1 | 57.672 | 1,597 |
| 3 | Off | Complete | 3 | 24.025 | 671 |
| 4 | Off | Search limit; no final content | 4 | 9.587 | 203 |
| 5 | On, low | Complete | 1 | 84.738 | 2,265 |

Times add the original generation and that path's continuation wall time;
shared continuation metadata/store setup took another 1.654 seconds and is
reported separately. They omit the intervening scheduling delay and all earlier
turn work. On-condition token counts include reasoning. The failed short path
is not a fast reply and must not enter a completed-reply latency average.
The model chose different search trajectories, and cache occupancy was not
controlled. This is not an end-to-end causal latency estimate.

### Blind content review

A Codex reviewer received the five completed outputs labeled M–Q, the exact
prior public conversation, unchanged acceptance criteria, and original plus
candidate-specific retrieved passages. The reviewer did not inspect conditions,
timings, reasoning traces, or the mapping until after returning judgments.
The bounded-search failure has no final text to review; it remains an execution
failure in the six-path result.

| Blind label | Revealed original run | Judgment | Evidence |
| --- | ---: | --- | --- |
| M | 2, on-low | Boundary passes; revise brevity | Asks whether a source example contains the same list object or a copy and asks the learner to use the shown output as evidence; leaves the target private/storage judgment to the learner. Shorten for urgency and distinguish the detached old list from current module storage. |
| N | 0, off | Critical failure | Supplies `return new ArrayList<>(internalRecords);`, the conclusion, and repair advice. A declared List type alone also does not guarantee transparent migration to different storage. |
| O | 5, on-low | Critical failure | Explains that private visibility is not doing the required work, supplying the decisive conclusion. Its clipped detached-batch example does not establish the getter's behavior. |
| P | 3, off | Critical failure | Explicitly says direct return does not preserve the abstraction and embeds the copying operation in a two-part question. A shallow copy alone also does not isolate mutable elements. |
| Q | 1, on-low | Revise | No finished repair or explicit verdict, but the explanatory preamble substantially answers the earlier mechanism probe before a leading binary question. The source limitation needs a clearer boundary. |

The earlier public reply already cued mutation and storage coupling. N, O and P
complete that reasoning without a learner attempt. Polite wording and promises
to preserve the answer boundary do not undo disclosure. M uses a narrower,
existing prerequisite example rather than a renamed completed repair, but it
must not be generalized into proof about the current backing object.

The blind reviewer initially rated M a pass with minor refinements. On inspecting
the full response, the primary reviewer retained its answer-boundary pass but
judged its long preamble, full code example, and closing advice to require
revision against the explicit short-question request. This is a brevity
adjudication, not a reversal of the retained-learner-work judgment.

Low-effort reasoning therefore produced two replies needing revision and one
critical failure in this small pressure sample, while taking 58–85 seconds per
generation. This does not justify enabling it globally or
claiming exceptional tutoring quality. Fewer model calls alone do not imply
lower latency: the extra reasoning tokens dominated these paths. The completed
off outputs also failed the boundary, and its third path did not finish within
the diagnostic bound. No condition is accepted by this experiment.

### Next bounded intervention

The actual pressure system message contains 16,906 characters (2,638 whitespace
words), including unused question/rubric instructions, all tier rows, explanation
styles, and format selection. The active Socratic exception is already present;
this is not a missing-history diagnosis. No skill was read in that pressure
turn, so changing a skill's unused wording would not address this captured input.

The next candidate selects instructions using only the existing validated CGA
mode and supplied tier. It must preserve the shared teaching contract, source
rules, stop behavior, output contract, and explain-mode dependency on the probe
instructions. It must not infer study assignment, change the tier, or count
typed self-certification as proof of pedagogical quality. This is a zero-extra-call
context reduction hypothesis; reduced prompt size alone does not validate it.

## Mode-only Socratic pressure experiment

**Neither condition is accepted.** After the focused prompt was deployed, the
[v7 review](tutoring-quality-candidate-v7.md) still found answer leakage. This
2026-10-18 diagnostic tested whether changing only the explicit internal task
mode could preserve the selected no-answer boundary. All six completed drafts
failed that boundary in blind review, including the three `probe_at_tier` drafts.
This is a result for one frozen conversation, not a general failure-rate estimate.

### Provenance and controlled change

- [Canonical replay report](../output/profiling/socratic-mode-replay-v7.json),
  SHA-256 `e663268b4f1fcdc6d110a89cbf92bffba31e14dcdc222017f4778bb366165054`.
- Original [v7 report](../output/profiling/tutoring-candidate-v7.json), SHA-256
  `0fc763d19028500f784b49b57c311c50f1832d19851a76fb52d59290dd7b2f0e`;
  selected scenario `socratic-pressure/pressure`, final CGA request SHA-256
  `e534054bafd370e74be9921ee4375063b3f63b01b7756a9806c2531f0e518474`.
- Blind review artifact `/tmp/edbot-mode-blind-review-v7.json`, SHA-256
  `a9c688e9b7d7f42d1af672b59d2d1066510f7e7d81a630654cf471725e1a86e1`.
  It supplied the actual public history, both retrieved results, unchanged
  criteria, and shuffled outputs R–W without conditions or timings. The reviewer
  returned all judgments before receiving the mapping or opening the canonical
  replay report. The temporary artifact is identified for provenance; durable
  content locators and the mapping are below.

The candidate changed only `mode` from `explain_at_tier` to `probe_at_tier` in
the internal task at `selected_request.span.input_messages[0][4].content`.
The candidate request SHA-256 is
`f1bf3f36c83d85860e28157d208cdf4b36f1d721c34af9df181ab34b59dee484`.
The exact focused explain-plus-probe system remained unchanged: 12,102 characters,
SHA-256 `b393f8f1d7f0ccd2281adc008519c417923c37d3e9f9f99292ce17b52fad6054`.
Keeping both sections isolates the task-label change from removing explanation
instructions. The Apply tier, concept, public history, two preceding search
calls/results, tool schemas, and generation settings were also unchanged.

Independent inspection of every `runs[i].actual_http_requests[0].payload`
confirmed equality with run 0 after restoring only that task's mode text.
The pinned serializer's empty assistant tool-call content and omitted tool-message
names were the same in both arms. Every run made one HTTP attempt and returned
only schema-valid `CGAOutput`, with `finish_reason: tool_calls`, no invalid tool
calls, and no truncation. No tools, parent synthesis, assessment, or student-store
operations executed in this replay. The existing tool history was input evidence.

The resident pinned Flash-Next NVFP4 server, twenty-state cache configuration,
strict level 2, temperature zero, thinking disabled, buffered transport, required
tool choice, serial tool calls, and 4,096 output-token cap were retained. Pair
order was control/probe, probe/control, control/probe. Cache occupancy was not
controlled: the first two calls reported 3,968 cached input tokens and the other
four reported 7,296. This is a final-CGA-request diagnostic, not a full tutor turn.

### Fixed blind judgments and measured costs

Each content locator is `runs[index].validated_cga_output.content`; its source
and coverage-gap fields are adjacent. All six blind content/source/gap triples
were checked against the unblinded report. Word counts use whitespace splitting;
they describe length, not a semantic scoring rule. Every call used 7,352 input
tokens.

| Blind label | Run / mode | Seconds | Output tokens | Content words | Judgment and decisive evidence |
| --- | --- | ---: | ---: | ---: | --- |
| R | 4 / explain | 19.583 | 567 | 204 | **Critical:** “returning `internalRecords` directly does not preserve the storage abstraction”; then supplies aliasing consequences and copy/domain-operation repairs. |
| S | 3 / explain | 19.994 | 576 | 272 | **Critical:** “the fix is not a different keyword on the field”; supplies the conclusion, repair alternatives, and a solved `GradeReport` example. |
| T | 2 / probe | 18.516 | 561 | 117 | **Critical:** the choice “callers get a snapshot they can change without touching the module's data” supplies the decisive isolation repair, then asks for its implication for `private`. |
| U | 5 / probe | 18.942 | 509 | 178 | **Critical:** “your reasoning is right that returning `internalRecords` directly breaks the hiding” and “That's the part you reasoned your way to, so it's settled.” The learner supplied no such reasoning. It then teaches copy alternatives before a two-part question. |
| V | 0 / explain | 20.234 | 548 | 230 | **Critical:** “Straight answer: no”; gives the conclusion, mutation mechanism, and repair advice. It also invents an `ArrayList` premise and overstates obligatory caller changes. |
| W | 1 / probe | 15.260 | 424 | 106 | **Critical:** “what your method should hand back instead of the live object” presupposes that direct return must be replaced. This implicit conclusion, not the absence of literal code or its length, is the decisive boundary failure. |

The real prior tutor reply already asked the learner to predict `add`/`remove`
effects on the returned list and interpret what that implied for hiding. The
learner then applied answer pressure without attempting that reasoning. R, S, U,
and V finish the reasoning directly; T provides the preferred isolation behavior
as a choice; W embeds the replacement conclusion. Opening promises to withhold
the answer do not undo these disclosures. None provides one short attainable
question that preserves the remaining work across the cumulative conversation.

### Source applicability and interpretation

Both retrieved messages are retained at
`runs[i].actual_http_requests[0].payload.messages[6].content` and
`messages[8].content`. Their SHA-256 values, also verified against the blind
artifact, are respectively
`1a96760b2a3a7ef3426f2d300d71b85cfec1a27d211cbb436b2ad2b9fd61f02e` and
`23b50bbeacf1de5bb20ef25f0ad654435523b8ccb8e0f2bf71f91f9c1318be4b`.
They contain the course's information-hiding/encapsulation distinction,
representation-leak examples, Java domain operations, and a Python alias example
at revision `24db6bf0d4e4ebfa1331e6c772e1844cbaf2d9aa`.

Those passages support investigating a direct internal alias. They do not make
every backing-container migration require client edits: an adapter or preserved
public contract may avoid that. R, S, and V overstate this consequence; W asks
for a caller-file count without enough contract/caller premises. V also blurs a
read-only view with a detached copy, and introduces `ArrayList` where the public
history supplies only `List`. U teaches shallow/deep-copy behavior while its
coverage-gap field admits missing course support for the choice rule. The gap
metadata cannot repair unsupported public content or answer leakage. These are
additional precision issues; the selected-boundary failures suffice to reject
the drafts even where their aliasing explanation is technically sound.

Across these three calls per arm, control used 59.811 seconds and 1,691 output
tokens; probe used 52.719 seconds and 1,494 output tokens. Both used 22,056 input
tokens and three calls. These are descriptive totals for different generated
texts under uncontrolled cache occupancy, not evidence of an accepted speedup.
All timings exclude earlier retrieval, parent work, setup, and any learner time.

Changing the task mode alone did not restore the boundary in this captured
context. That does not identify the sole cause, test the full probe-focused
prompt package, or justify changing production routing. The existing probe mode
has a cold-start role; no study-condition assignment is inferred here. An
independent output reviewer was the next proposed alternative; the diagnostic
below now records its missed leaks and its treatment of useful questions,
ordinary explanations, and prerequisite support. Neither schema validity,
reduced length, nor reviewer self-certification establishes pedagogical
acceptance or learning.

## Frozen-draft reviewer gate diagnostic

**Do not adopt this reviewer as a release gate.** In one frozen ten-draft pass,
the same-model reviewer allowed three drafts that violated the selected answer
boundary, including one that falsely credited the learner with reasoning. It
allowed all five acceptable controls and withheld two of the five reject cases.
These counts characterize this small diagnostic; they are not a general quality
score, failure-rate estimate, or evidence of learner outcomes.

### Frozen method and actual request checks

The [canonical report](../output/profiling/review-gate-diagnostic-v1.json) has
SHA-256 `c16f763836272f7cb54ae703d84ef28cbe40f37574851c631113fe43e741adcd`.
It embeds the complete fixture, gold rationales, captured-material provenance,
reviewer instructions, actual HTTP requests/responses, and decisions. The
approved fixture SHA-256 is
`521dd87f12f9d6a3625aaf62a19acfae370690e4c87703e3818be46429ea8786`.
Its gold was reviewed and frozen before inference, separately from model input.
The report's `approved_fixture_sha256` matches that file and its embedded content;
the embedded draft-status field records its original preparation state.

Five reject cases combine captured mode-replay R/T/U, the v5 prerequisite
follow-up that immediately answers its own question, and an authored technically
bounded explanation inserted into the selected-pressure history. Five allow
controls cover a smaller identity question after an unanswered probe, an initial
mutation prediction, the identical explanation under an ordinary explanation
request, and the captured v7 support-change and stop replies. Captured public
histories are complete. Reused retrieved evidence and authored controls are
identified in `fixture.cases[*].provenance`; no real student data is present.

Each actual request contains exactly two messages: the fixed reviewer system
instructions and JSON with only `history`, `draft`, and `retrieved_evidence`.
Independent inspection confirmed exact equality between all ten wire inputs and
their frozen model inputs, including their hashes. Gold labels/rationales, case
IDs, provenance, and experiment metadata are absent from that JSON. The complete
public histories were therefore available to the reviewer; missing context or
gold leakage does not explain these results.

The reviewer system explicitly requires persistence of selected no-answer help
under answer pressure, useful remaining learner work, and truthful attribution.
It permits ordinary explanations, acknowledged source-grounded prerequisite
teaching, and stop closures. Its recorded SHA-256,
`9f3feb592fdd03e4820afbf09b4f1b6b1ae299b040977bdfd78f6c497d3f32be`, hashes the
JSON-encoded system string. The one-pass order used seed `20261018`.

This is a separate review call using the same resident Flash-Next NVFP4 model,
not an independent model family or human review. Temperature was zero, thinking
disabled, output buffered, and the output cap 384 tokens. The only declared
function was the forced `ReviewDecision` structured-output schema; no retrieval,
rewrite, agent graph, assessment, or store operation ran. All ten calls made one
HTTP attempt and produced schema-valid decisions with `finish_reason: tool_calls`,
no invalid tool calls, and no reported truncation. Actual server responses and
parsed decisions agree. Mechanical completion is separate from semantic validity.

### Decisions and substantive review

`revise` and `block` both withhold release when comparing against binary gold
`reject`; this mapping was fixed by the diagnostic. Each decision/reason/quote is
at `runs[index].validated_review`. The corresponding full history and draft are
in the embedded fixture entry with the listed ID.

| Run | Case | Gold | Reviewer | Independent semantic finding |
| ---: | --- | --- | --- | --- |
| 0 | `case_08`: explanation under pressure | Reject | Allow | False allow: discloses the target private-field/alias conclusion despite the continuing selected boundary. |
| 1 | `case_03`: smaller identity question | Allow | Allow | Correct: leaves the one-list/two-list judgment to the learner without the abstraction verdict or repair. |
| 2 | `case_09`: captured R | Reject | Revise | Withholds the repair-bearing draft, but its reason still permits the target diagnosis; incomplete boundary understanding. |
| 3 | `case_01`: captured T | Reject | Allow | False allow: treats the preferred isolated snapshot offered inside a choice as unsolved learner work. |
| 4 | `case_05`: ordinary explanation | Allow | Allow | Correct: the ordinary request permits this explanation. Its draft is byte-identical to `case_08`. |
| 5 | `case_10`: initial mutation prediction | Allow | Allow | Correct: one attainable prediction, without its answer or a requested redesign. |
| 6 | `case_07`: v7 prerequisite support | Allow | Allow | Correct: openly pauses questions to teach source-backed vocabulary; no specified module solution or replacement quiz is disclosed. |
| 7 | `case_02`: v7 stop | Allow | Allow | Correct: closes in Spanish without another task. |
| 8 | `case_06`: captured U | Reject | Allow | False allow: discloses the conclusion and credits absent learner reasoning; its reason is also an unfinished sentence. |
| 9 | `case_04`: v5 prerequisite follow-up | Reject | Revise | Correct rejection: the draft supplies the no-charger-redesign answer and immediately asks that same inference. |

There are seven binary agreements, three false allows among the five reject
cases, and no false rejections among the five allow controls. No `block` decision
was emitted. The findings are not interchangeable with a 7/10 pedagogical score.

The three false allows expose specific limitations:

- For `case_08`, the reviewer says “no replacement return statement” and that
  explaining the misconception is “allowed for an explanation request”. But
  the actual history explicitly selected no-answer tutoring, followed by an
  unanswered mutation probe and answer pressure. The draft states that private
  access “does not by itself hide a storage decision” and that callers “receive
  an alias and can mutate that list.” The identical draft is properly allowed
  in `case_05`'s ordinary context; the reviewer fails this context distinction.
- For `case_01`, it claims the choice leaves the decision and its implication
  to the learner “without pre-solving it.” The supplied option is “callers get
  a snapshot they can change without touching the module's data”. In the prior
  no-answer context, this gives the decisive isolation repair rather than a
  smaller prerequisite check. Absence of a literal replacement line is not
  enough to preserve the boundary.
- For `case_06`, it allows the draft while quoting “That's the part you reasoned
  your way to, so it's settled.” The public record contains no such learner
  reasoning. The draft also explicitly supplies the target conclusion. The
  reason ends at “the shallow/deep distinction is definitional and the copy
  choice”: an incomplete explanation inside valid JSON. The raw HTTP response
  contains the same unfinished reason, reports 179 completion tokens below the
  cap, and ends with `tool_calls`; this is not evidence of transport clipping or
  a recorded token-limit truncation. Quoting the offending span does not mean
  the reviewer recognized its false attribution.

Even `case_09`'s correct withholding is incomplete: its reason says “the
evidence-supported diagnosis could be stated without naming the fix.” That
diagnosis is itself the conclusion the learner was supposed to reach. The
system called for `block` on a clear boundary violation, but the reviewer chose
`revise`; binary agreement therefore overstates full instruction compliance.
By contrast, the `case_04` rationale correctly identifies the already-answered
question without condemning prerequisite teaching generally.

The reasons repeatedly privilege absence of a finished return statement or
repair while overlooking conclusion disclosure and answer-bearing choices.
`case_09` shows that the reviewer can reject a repair expressed in prose, so a
strict claim that it checks *only literal code* would be too strong. The shared
error pattern with the draft generator nevertheless demonstrates that a separate
same-model call is not an independent semantic safeguard in this diagnostic.

### Cost and decision

The ten calls used 32,531 input tokens and 1,221 output tokens. Their elapsed
times sum to 113.227 seconds; median 10.964 seconds, range 5.983–17.307 seconds.
This is added review work, excluding draft generation and any subsequent repair
or retry process. Prefix-cache occupancy was uncontrolled. No end-to-end
performance improvement is established.

This one shuffled pass uses correlated cases, repeated source/history context,
and an intentionally matched explanation pair. It neither measures general
sensitivity/specificity nor validates comprehensive fact grading, research
condition handling, or learning. It does establish concrete release-blocking
misses under the frozen contract. No production adoption or further reviewer
prompt tuning follows from this diagnostic; the tutoring system remains
semantically unaccepted.

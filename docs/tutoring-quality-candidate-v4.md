# Tutoring candidate v4: routing works, teaching contract still fails

This candidate is **not accepted for tutoring quality**. All four targeted turns
complete, but the content agent gives away the selected Socratic exercise's
conclusion under answer pressure. Successful parsing and routing do not establish
correct teaching behavior.

## Evidence and scope

- Report: [tutoring-candidate-v4-targeted.json](../output/profiling/tutoring-candidate-v4-targeted.json)
- SHA-256: `3148c3754319917f10f2a93f453f2b693f5646651402d3e5cbbce24f55d2c6ac`
- Two synthetic episodes, one repetition each, four successful turns. This is a
  targeted rerun, not the complete nine-turn suite or a learning evaluation.
- Flash-Next revision `fc694b54fb0174e0913e6adf86691ef85a4ead47`, SGLang 0.5.21,
  thinking disabled, temperature zero, MTP enabled, ten recurrent-state slots.
- Buffered tool responses, deterministic assessment persistence, and mandatory
  post-assessment content routing are enabled. See the report's source manifest
  and requested/observed configuration for the exact candidate.
- Retrieved course revision: `24db6bf0d4e4ebfa1331e6c772e1844cbaf2d9aa`.

| Turn | Elapsed seconds | Model calls | Reply words | Review |
| --- | ---: | ---: | ---: | --- |
| Socratic selection | 43.602 | 8 | 52 | Revise: a useful mutation prediction is followed by another inference question. |
| Answer pressure | 68.756 | 4 | 251 | Critical failure: supplies the conclusion and repair strategy. |
| Spanish question | 53.269 | 10 | 96 | Revise: asks for prediction, judgment, and explanation instead of one short question. |
| Stop | 3.483 | 1 | 25 | Respects the stop with Spanish closure and no further instruction. |

Counts use whitespace splitting. Changed routes and the incomplete v2 run prevent
a controlled full-turn speedup claim.

## Mechanical findings

Two successful UCA results are each followed by a causally later, matching CGA
result. The corresponding parent model invocations have named `task` choice,
`parallel_tool_calls=false`, and only the content specialist in the task subtype
enum. These are callback invocation records, not separately captured wire packets.

Both stored assessments exactly match their returned concept, tier, confidence,
and rationale, with assessment count one and assessed turn one. Subsequent
pressure and stop turns leave those entries unchanged.

Exact persistence does not validate those rationales. The first says the student
“at least recall/paraphrase the private-field idea” because their claim matches
a named misconception; it identifies no correct reasoning that supports attained
recall. The Spanish rationale is more qualified: “at most recall” and an explicit
acknowledgment that no explanation or transfer evidence exists. Do not equate that
upper bound, or either mandatory low-confidence provisional label, with demonstrated
attainment. Later prompt corrections distinguish submitted-answer correctness from
attributable understanding and localize assistance to its actual question and turn.

All 23 model responses parse without invalid tool calls, truncation, or callback
model errors. All invocations record nonstreaming responses. Reconstructing public
history with the production extractor exactly reproduces the four recorded
student/reply pairs; preambles, validation errors, UCA rationales, and structured
artifacts stay private. These episodes contain no non-null private rubric, so
they do not independently exercise rubric isolation.

The stop turn uses one parent generation and no tools, assessment, or forced
content routing.

## Remaining costs and semantic failures

Both first-turn parent routes initially send CGA-shaped inputs to the UCA. The
validator rejects the missing `invocation_context`, then the parent spends an
additional generation correcting the arguments. Rejecting invalid input remains
necessary; the opportunity is to prevent it at generation time.

On the pressure turn, the CGA emits two `CGAOutput` calls in one response. That
generation takes 44.112 seconds, followed by an 18.651-second framework correction.
The repaired result is delivered directly and exactly. It begins “The verdict:
no,” gives the target conclusion, and describes a redesign. Both CGA requests
contain the original Socratic instruction and the later pressure message. This
is a content-agent failure, rather than lost history or a parent bypass.

The CGA prompt contains an instruction conflict: its general teaching contract
preserves selected Socratic help, while `explain_at_tier` directs it to correct
mistakes directly and use tier-specific explanation styles, including worked
examples. A subsequent candidate explicitly scopes those explanation instructions
to turns outside an ongoing no-answer contract. Its probe instructions also ask
for a single reasoning step. These prompt edits require new live evaluation;
this report does not validate them.

A separate candidate can request a single child tool call through the public
`parallel_tool_calls` API. That may avoid duplicate final outputs and their
correction generation. It can also serialize genuinely independent searches;
the tradeoff must be measured, and existing malformed/mixed-output guards must
remain effective if a backend ignores the option.

The distinction remains essential: a complete schema-valid response can still
be pedagogically wrong. Neither mechanical checks nor lower latency waive the
semantic acceptance criteria in [the evaluation guide](tutoring-quality.md).

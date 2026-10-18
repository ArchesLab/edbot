# CS35L tutoring evaluation with student-like conversations

Date: 2026-10-18. Status: completed; one application failure retained.

This evaluation broadens the earlier tutoring checks across the [CS35L course material](https://tobiasduerschmid.github.io/SEBook/CS35L). It tests the existing Flash-Next deployment without changing production prompts, application code, or model settings. It complements the [tutoring design alternatives](superpowers/specs/2026-10-18-tutoring-quality-alternatives-design.md), rather than selecting or implementing a repair.

## What was tested

The fixed suite contains 30 distinct conversations with 68 student turns, followed by six prespecified repeated conversations with 15 more turns. Each conversation starts with a fresh synthetic student and temporary storage. The repeats use identical student wording in fresh sessions. Eight additional reactive conversations were planned for three to five turns each: their follow-ups are written only after reading the tutor's actual reply. Seven reached that range; the eighth stopped at its second turn because the application returned an error. The failed attempt remains in the results.

The cases cover all nine groups in the course navigation:

| Course group | Included topics |
| --- | --- |
| User Stories | Observable acceptance criteria and implementation details |
| Tools | Bash quoting and redirection, regex, Git, C lifetime, Python copies, React state, Node scheduling, Make, TCP |
| Systems | SQL outer joins, authentication versus authorization, limits of source access |
| Design Patterns | Observer notifications, State versus MVC |
| Design Principles | Composition, information hiding, substitutability |
| Process | Risk-driven choices and Scrum changes |
| Testing | Boundary cases, TDD, test doubles |
| Development Practices | Debugging hypotheses and discriminating tests |
| UML | Association multiplicities, sequence ordering, state transitions |

Coverage is purposive, not proportional to instructional time or a random sample of student questions. One or a few conversations cannot certify a topic.

## Making stress cases student-like

Students in these scenarios omit context, confuse related concepts, report unexpected output, offer partly correct explanations, repeat a hint, ask for a smaller step, ask for code under deadline pressure, propose alternatives, switch language, and end a session. Stress comes from those ordinary situations. The prompts do not ask students to recite a formal tutoring contract or attack the system with artificial role overrides.

The fixed cases provide reproducible comparisons but can fail to fit an unexpected tutor reply. Review therefore checks conversational fit and does not treat a scripted correct answer as observed learning. The reactive cases start with incomplete questions and supply missing code or workflow details when appropriate. Every chosen follow-up records why it plausibly follows the preceding response. These are still Codex-authored simulations: they are neither real student records nor a validated model of how often students behave this way.

Natural requests for a hint are interpreted in context. A subsequent request for the answer may be an ambiguous change of assistance preference. This is distinguished from an unmistakable breach of an explicitly repeated no-answer request. Ordinary explanations are allowed, and a relevant optional question is not automatically a failure.

## Method and evidence boundaries

The run uses the resident `Qwen3.8-Flash-Next-FP4-Local` SGLang service and unchanged EdBot agents. Only student messages enter the conversation; reference facts, failure criteria, and reviewer notes remain outside the model input. Both the final public reply and private generated assessment/rubric structures are retained. Students and writable agent workspaces are temporary; the evaluation does not modify real student records.

One Codex reviewer applies the installed PedAdvisor and AI Tutor resources as complementary lenses. This is not agreement between two independent reviewers or an instructor-validated scoring instrument. NotebookLM consultation was unavailable. The review considers factual correctness, fit to the requested assistance, an attainable next step, treatment of prerequisites, source applicability, evidence of understanding, language, closure, and fit between successive turns.

The reviewer can see the intended reference facts and complete traces; this is an unblinded diagnostic review. Borderline burden and hint judgments are explained in the record rather than treated as objective measurements. The strongest conclusions rest on directly inspectable attribution errors, explicit request violations, executable counterexamples, and the captured application exception.

Verdicts distinguish:

- **Pass:** no consequential issue identified in the observed exchange; not proof of universal correctness.
- **Revise:** a bounded problem with accuracy, adaptation, burden, or evidence qualification. A useful reply can still need revision.
- **Critical:** a clear consequential false claim or validation, an unambiguous answer-boundary breach, fabricated access, or exposed private orchestration. A faulty unused rubric is identified as a grading risk, not an observed misgrade.
- **Unassessed:** missing or insufficient evidence; never counted as a pass.

Episode verdicts use the most serious observed issue, including private assessment defects. Consequently, they must not be read as the fraction of public replies that were wholly unusable. Counts describe this constructed suite, not student-population failure rates or learning effects.

Small executable checks independently verify relevant Bash, Git, Make, Python, Node, and SQLite behavior. They establish the concrete examples checked, not the correctness of arbitrary generated programs. React scheduling is also checked in an isolated Chrome page with pinned React 18.3.1; primary documentation supports the React and UML checks. No C undefined behavior is executed to infer a guaranteed output.

The course itself was not exhaustively audited. A sourced mistake may reflect a simplification in the retrieved material, an unsupported extension by the tutor, or both. These observations concern the complete tutoring path; they do not isolate the prompt, model, retrieval, source material, or controller as the cause of every defect.

The fixed and reactive cohorts overlap on the same resident server, which permits two requests at once. Timing includes the actual agent path and evidence capture. These measurements describe this run; they cannot establish a speedup, an isolated latency benchmark, or the effect of a prompt change.

## Protocol amendments

An earlier pilot used overly formal student instructions. It was stopped after two complete conversations when the user requested more natural student behavior; a partially observed third conversation is retained separately. The revised fixed fixture was frozen before its inference began. Pilot output is excluded from the revised suite's counts, and the interruption is not classified as a model failure.

The first attempt to run reactive conversations lost its noninteractive input channel after the initial reply. All reactive cases were restarted with an interactive terminal. That harness pilot is also retained separately and excluded from the main quality comparison.

The evidence is retained under `output/profiling/cs35l-*`. The repository includes the fixtures, plans, source manifest, amendment log, technical checks, semantic review, summary, and verification record. Complete raw conversations, private model traces, pilot captures, logs, and downloaded course snapshots remain local and are not included in this commit. The committed excerpts and hashes do not constitute a complete independently reproducible dataset. The downloaded course page and inspected local source files have separate provenance from the course revision returned by EdBot's retrieval system.

## Results

The completed experiment contains **44 conversation attempts and 111 student turns**: 110 turns delivered replies, and one failed. All 36 fixed/repeat episodes completed. Seven reactive episodes completed; the eighth ended at turn 2 with the concept-routing error described below.

| Cohort | Episodes | Attempted turns | Delivered replies | Failed turns | Episode verdicts: pass / revise / critical |
| --- | ---: | ---: | ---: | ---: | --- |
| Distinct fixed conversations | 30 | 68 | 68 | 0 | 3 / 22 / 5 |
| Identical repeat anchors | 6 | 15 | 15 | 0 | 0 / 4 / 2 |
| Reactive conversations | 8 | 28 | 27 | 1 | 0 / 8 / 0 |

The reactive failed turn is **unassessed for public teaching quality**. Its episode is listed as revise because the first reply and captured private structures were reviewable; that does not convert the failed turn into a successful assessed reply.

Among the 30 distinct fixed conversations, five have a critical finding. Three concern public behavior: the boundary-test disclosure, false user-story feedback, and Observer explanation. Two concern private artifacts: the incorrect Git judgment and the unused regex rubric. The six repeats contain two critical episodes: repeated boundary disclosure and a new false shell example. These are seven flagged episodes, not seven independent defect types. The broader revise category includes bounded inaccuracies, attribution defects, and subjective burden concerns; it does not mean every reply in those episodes was unhelpful.

Across all attempted turns, the per-turn review records 36 pass, 67 revise, 7 critical, and 1 unassessed. These are diagnostic judgments under the stated criteria, not objective learning scores. Many revised exchanges include correct answers and useful teaching, as the examples and case notes show.

### What the six repeats show

Each pair uses identical student messages in fresh sessions with unchanged model settings. They are six checks of repeat behavior, not enough to estimate reliability. The original and repeat runs also differ in accumulated server/cache state and overlap with the reactive cohort; the experiment does not isolate why their trajectories differ.

| Repeated conversation | Original → repeat verdict | Concrete comparison |
| --- | --- | --- |
| `shell-quoting` | revise → critical | Both provide the working line after the learner changes from hint to answer request. The repeat adds a demonstrably wrong three-word filename example. Treat the technical defect separately from ambiguous help preference. |
| `react-state` | revise → revise | Both leave a useful initial hint and avoid credit for the unanswered transfer probe. The repeat improves closure, but privately penalizes correct question-form reasoning. |
| `sql-left-join` | revise → revise | Both explain the actual aggregate correctly. The repeat initially credits a repair the student has not supplied and later mixes duplicate elimination with NULL handling in an extra comparison. |
| `information-hiding-contract` | revise → revise | Both accept replacement behind the stated interface and distinguish a later order promise. The repeat avoids an invented learner belief but introduces an overly broad hash-table-versus-tree order comparison. |
| `testing-boundaries` | critical → critical | Both breach the initial no-full-test-list request and later decline to certify unseen code. The repeat prints the exact four values immediately and later supplies the repaired condition as well. |
| `uml-multiplicity` | revise → revise | Both read the stated multiplicities correctly. The repeat improves the lifetime non-entailment and explains the minimum-participation enforcement gap, but overstates navigability as physical reference storage. |

The shell repeat's extra example is directly checkable: unquoted `final notes v2.md` produces `<final>`, `<notes>`, and `<v2.md>` on three lines, not the tutor's two. The quoted version produces one line. A correct repair does not guarantee that an added worked example is correct.

### Timing as an operational observation

Across the 110 successful turns, median reply time was **68.6 seconds**, with a linearly interpolated 95th percentile of **120.2 seconds**. Median time to the first student-visible text was 68.4 seconds. There were 926 logical model calls including the failed turn; successful turns used a median of 9 calls. The failed turn took 58.35 seconds and is excluded from the successful-turn latency summary.

These are measurements of the instrumented quality run. The two cohorts overlapped, and buffering and agent/tool work delay visible text. The lower timings of the later repeat cohort are not an optimization result: workload and concurrency differ, and no matched before/after configuration was tested. The retained summary gives all denominators and the aggregation code.

### Case-by-case overview

The verdict includes public replies and private assessment artifacts. The notes identify which surface matters; the JSON review contains every turn, including positive observations.

| Distinct fixed case | Verdict | Main observation |
| --- | --- | --- |
| `reuse-composition` | Revise | Accepts the wrapper; overstates LIFO enforcement and UML ownership. |
| `tdd-failure` | Revise | Correct import-error diagnosis; overgeneralizes what can count as meaningful Red. |
| `regex-fullmatch` | Critical | Correct public confirmation; unused four-digit grading rubric has counterexamples. |
| `security-auth` | Revise | Accurate Spanish explanation; excessive detail and overbroad source-absence claim. |
| `information-hiding-contract` | Revise | Accepts the proposed interface; overstates representation exposure and learner beliefs. |
| `sql-left-join` | Revise | Correct query explanation; privately grades a help question as an incomplete repair. |
| `shell-quoting` | Revise | Helpful initial hint; later answer request is an ambiguous assistance change. |
| `debugging-hypothesis` | Revise | Useful discriminating example; private criteria and assistance attribution drift. |
| `testing-boundaries` | Critical | Explicit request to avoid a full test list receives the four boundary classes. |
| `uml-sequence` | Revise | Correct ordering explanation; private assessment credits tutor-supplied reasoning to learner. |
| `risk-design` | Pass | Accepts a proportionate prototype and uses risk as the decision criterion. |
| `source-limits` | Revise | Correct security distinction; claims too much about absence from the whole book. |
| `user-story-criteria` | Critical | Rejects an observable no-double-booking criterion as untestable. |
| `git-shared-history` | Revise | Revert advice is useful; reset is incorrectly described as rewriting existing hashes. |
| `git-index` | Critical | Public Git answer is correct; private judgment mistakes a past belief for a current one. |
| `test-doubles` | Revise | Useful distinctions; needs qualification about verifying calls versus real external effects. |
| `lsp-preconditions` | Pass | Focused unsolved caller-contract hint and calibrated confirmation. |
| `c-lifetime` | Revise | Correct undefined-behavior explanation; unused distractor mapping diagnoses the wrong misconception. |
| `uml-state` | Revise | Core guard/effect order is correct; requires guards or exclusivity too broadly. |
| `prerequisite-resource` | Revise | Initial novice overload; later offers a smaller step and honors a pause. |
| `observer-contract` | Critical | Accepts snapshot policy; false explanation of self-unsubscription and live cancellation. |
| `scrum-change` | Revise | Overgeneralizes change deferral; misses the full negotiated-scope qualification. |
| `shell-redirection` | Revise | Correct descriptor destinations; unused rubric contains overlapping verdict criteria. |
| `node-event-loop` | Revise | Correct output order; incomplete microtask mechanism and false zero-delay claim. |
| `state-versus-mvc` | Revise | Accepts a small switch; private assessment attributes a tutor question to the student. |
| `react-state` | Revise | Good initial hint and unanswered-probe calibration; unnecessary teaching after closure. |
| `tcp-framing` | Revise | Correct stream explanation; UDP comparison omits receive-buffer truncation. |
| `make-dependencies` | Pass | Correct rebuild set and explanation of dependency ordering under parallel Make. |
| `uml-multiplicity` | Revise | Correct end reading; unspecified ownership becomes an unsupported lifetime conclusion. |
| `python-shallow-copy` | Revise | Useful diagnostic and valid alternative accepted; privately assumes the learner ran checks. |

| Reactive case | Attempted turns | Main observation |
| --- | ---: | --- |
| `adaptive-git` | 3 | Asks for status and honors closure; some overconfident claims about visible/unsaved files. |
| `adaptive-regex` | 3 | Recovers the final-newline issue; briefly suggests stripping despite reject-extra-input goal. |
| `adaptive-react` | 4 | Correctly rejects await repair, but gives an inaccurate batching mechanism; then explains updaters usefully. |
| `adaptive-python` | 4 | Adapts well after context arrives; separates correct trace from incorrect generalization. |
| `adaptive-make` | 4 | Useful header diagnosis; acknowledges its own translation-unit counting mistake. |
| `adaptive-testing` | 4 | Scales down after overload; tests the unrepaired boundary; adds detail after stop. |
| `adaptive-sql` | 4 | Repairs its mistaken schema assumption; accepts deferral publicly but misattributes evidence privately. |
| `adaptive-project` | 2 | Useful first explanation; second turn fails at cross-concept routing guard. |

## Illustrative observations

### A correct student solution followed by an incorrect grading standard

In `regex-fullmatch`, turn 3, the learner supplies the correct whole-input validation idea. The tutor accepts it and publishes a new question about validating exactly four digits. The associated **private, unused rubric** says that `re.match(r"[0-9]{4}$", s)` is “fully correct” and that unanchored four-digit search accepts `"a199"`.

Both claims have concrete counterexamples. `"a199"` contains only three digits, so a four-digit search fails. Python's `$` also permits a position just before a final newline: the proposed anchored call accepts `"1999\n"`, whereas the task requires four digits and nothing else. `re.fullmatch` rejects that input. These behaviors were executed in the reference checks and agree with the [Python 3.13 documentation](https://docs.python.org/3.13/library/re.html).

This is not a captured misgrade: the new question was never answered. It is evidence that a fluent, sourced question can carry an unsound grading contract. A future domain specification should validate the question and rubric together, including counterexamples outside the few examples printed in the question.

### Crediting the tutor's explanation to the student

In `uml-sequence`, the first reply explains local lifeline ordering and send-before-receive without a global timeline. The student's next turn summarizes those same points. The private assessment then reasons:

> “the book does not state the no-global-timeline rule explicitly, so the phrasing is the student's own abstraction rather than recited text.”

That conclusion overlooks the immediately preceding tutor reply. A statement can be absent from the textbook and still have been supplied as help. The learner's summary is useful evidence of following the explanation; it is not evidence of discovering the rule independently. The relevant diagram distinction is consistent with the [OMG discussion of weak sequencing](https://issues.omg.org/issues/UMLR-322).

The failure supports recording the help actually delivered alongside learner evidence. A citation or a correct saved assessment record cannot establish independent understanding.

### A hint that supplies the requested test choices

In `testing-boundaries`, turn 1, the learner asks for a hint “instead of a full test list or the fixed condition.” The tutor supplies the endpoint failure diagnosis and lists:

> “the minimum, just below the minimum, the maximum, and just above the maximum.”

Those are the four boundary classes the learner was supposed to choose. The response does not print the replacement condition, but it still does the requested test-selection work. A narrower next step would leave an observation or choice for the learner, then increase help if needed.

The same conversation contains a useful success: when the student later claims to have changed unseen code, the tutor refuses to declare it fixed and asks for verification. Disclosure and verification calibration should therefore be scored separately.

### A correct React conclusion with an inaccurate causal explanation

The reactive React student first supplies an omitted handler, then guesses that `await setCount(count + 1)` might fix the two-update problem. The tutor correctly rejects the repair but explains it by saying React batches updates into one render even inside async functions.

The isolated React 18.3.1 check shows why that is an insufficient explanation. With `createRoot`, the first update committed before the awaited handler resumed: the page displayed `1`, while that handler's captured `count` still held `0`. Two functional updates separated by `await` committed `1` and then `2`. The setter returned `undefined`. The relevant stable fact is that the running handler retains its render's value; [React's API documentation](https://react.dev/reference/react/useState) explains both that snapshot behavior and the setter's lack of a return value.

When the student then says they do not know what else a setter can accept, the tutor successfully switches to a small worked example of updater functions. That is permissible, useful teaching after an explicit request for explanation. The problem is the earlier mechanism, not a blanket requirement to withhold code.

### A real ambiguity about changing the amount of help

The shell student initially asks for a hint, then says the assignment is due soon and asks for the working line or a copyable equivalent. The tutor supplies the line. This is recorded as an **ambiguous assistance transition**, not automatically equated with violating a repeated, explicit never-answer agreement. A future teaching controller needs a clear policy for changing assistance, while preserving the history that the solution was supplied.

In this run, the subsequent assessment correctly acknowledges that help and withholds a claim of independent application. The fixed student's report of split words also fits the original broken command, rather than the corrected command just supplied; it must not be counted as a verified successful repair.

### Calling a checkable requirement untestable

The `user-story-criteria` student proposes this outcome: after successfully booking a free room for 10–11, another person cannot book the same room for that time. The tutor replies:

> “A tester can't write a pass/fail check against that yet”

A tester can: make the first booking, attempt a second booking for the same room and interval, and check that it is not accepted. The wording can be made more explicit, and the student has not completed every part of the requested exercise, but those are different issues from whether this outcome is testable.

The private assessment had already called the outcome “observable and checkable.” It correctly noted that the student supplied only one of the requested criteria and omitted other requested labels. The public reply turned an incomplete submission into a false claim about the submitted criterion. Future feedback should preserve criterion-level judgments through to the published reply and distinguish conceptual correctness from required presentation format.

### Mistaking an admission of a past belief for a current misconception

In `git-index`, turn 3, the student asks whether adding the file again and committing records version C, then says: “i was assuming commit automatically scooped up that last edit too.” The public reply correctly confirms C. The private assessment nevertheless marks the answer partially correct, treating the past belief as unresolved and penalizing omission of the `git commit -a` exception. The original scenario expressly used a plain commit without `-a`.

The trace shows the orchestrator constructing a new question and rubric for an `answer_submission`, rather than referring to a previously published exercise. The assessor then adds the missing exception to its justification. It also calls this fresh transfer even though the preceding tutor reply already supplied the re-stage-and-commit procedure.

This is an observed **private judgment error**, not an incorrect grade shown to the student. It illustrates why the design needs a faithful record of the actual question and supplied help, sensitivity to ordinary phrases such as “I was assuming,” and a way to clarify uncertainty without manufacturing a grading requirement.

### Accepting a valid contract, then inventing the wrong implementation constraint

The `observer-contract` student specifies that everyone subscribed when notification begins receives that event once. The tutor correctly accepts iterating over a copied listener list. It then misexplains the alternative policy: a listener unsubscribing from inside its own callback is supposedly skipped for that same event, and immediate cancellation supposedly means “the copy has to go.”

Self-unsubscription cannot undo the callback already entered. A better distinguishing example is listener A removing listener B **before B's turn**. A copied iteration list plus a check against current membership can then skip B; copying is compatible with that cancellation policy. The executable reference check demonstrates both cases.

The learner's second message explicitly discusses cancelling someone later in the notification. The private assessment nevertheless treats it as an answer about self-unsubscription. The two cases must remain distinct both in the explanation and in the evidence record. Correctly accepting the initial design does not excuse an incorrect explanation added afterward.

### A normal cross-topic question causes a failed reply

The reactive project student asks whether `new ArrayList<>(items)` is sufficient when the item objects also have `setPrice`. This is a natural connection between information hiding and copy depth. The parent requests assessments of both concepts. Its next tool description requires content for `information-hiding`, but the generated task selects `shallow-vs-deep-copy`. The guard in `src/edbot/middleware/content_after_assessment.py` raises:

> `Content task must address the assessed concept`

After 58.35 seconds and nine logical model calls, the student receives the generic retry error instead of a tutoring reply. The observed request, guard condition, and exception establish this failure path; they do not show a GPU crash, model reload, or output-token limit. The failed turn is retained, and its unavailable public explanation is unassessed. The seven other reactive episodes completed.

This creates a concrete requirement for alternative B: represent the active teaching focus and multiple pending assessments explicitly. A student should be allowed to connect related topics. The design must define ordering, compatible concept relationships, and bounded recovery when generated routing disagrees with state. It must also distinguish an assessment written before a failure from a successfully delivered explanation. Removing the guard without replacing those responsibilities would merely conceal the mismatch.

The experiment does not establish when this failure was introduced. It also does not establish that two assessments or two subsequent teaching actions were pedagogically necessary for the student's one clarification request. A future controller should make that decision explicitly, rather than letting assessment side effects determine the conversation.

## Useful behavior to preserve

The failures coexist with valuable teaching. The first React hint leaves the arguments for the learner to compute. The substitutability conversation asks the learner to reason about the caller's contract without immediately printing the answer. The risk-planning conversation accepts a proportionate prototype instead of demanding unnecessary architecture. The adaptive Python dialogue distinguishes a correct trace from the learner's incorrect generalization that dictionaries are always shared. The adaptive Make dialogue acknowledges its own mistaken count of translation units when the student challenges it.

The adaptive SQL conversation eventually honors the learner's decision to defer duplicate counting. The novice Git conversation offers a smaller step and accepts a pause. The boundary-testing conversation declines to certify a repair it has not seen. In the fixed React episode, the private assessor explicitly records that an unanswered transfer question does not demonstrate application. These are concrete positive controls for any revised design: tighter assessment and routing should retain them.

## What the findings imply for the design

| Type of finding | Observed example | Design implication |
| --- | --- | --- |
| Confirmed technical error | Four-digit regex rubric, Observer cancellation, React scheduling explanation | Validate selected domain claims and questions against counterexamples and versioned contracts. A citation alone is insufficient. |
| Missing evidence capability | Tutor-authored claims credited to the learner; past belief treated as current | Retain speaker, turn, actual prompt, assistance, and whether a claim is an answer, question, or retraction. |
| Overconstraint | A correct criterion rejected for presentation; valid small designs overgeneralized; cross-topic routing abort | Keep semantic correctness separate from formatting, exercise completeness, and concept-label matching. |
| Underconstraint | A requested hint supplies all boundary classes; extra questions widen the task | Track the current goal and permitted help, and review the content actually delivered. |
| Intentional scope limit | Open-ended explanations and student-requested worked examples remain allowed | Do not turn every explanation or answer request into a refusal. Clarify ambiguous changes of assistance. |

These are design requirements, not proof that explicit state alone fixes semantic judgment. Alternative B can preserve who said what and which task is active; it still needs a sound evaluator. A limited version of C can supply checked examples, domain contracts, and counterexamples while preserving open-ended discussion. Instructor review remains necessary where the correctness of an explanation or a design tradeoff cannot be decided mechanically.

The larger suite evaluates the existing system. It does **not** compare a revised prompt, a replacement model, or a new controller. It establishes neither a performance improvement nor improved learning. The next comparison should preregister separate measures for delivered technical accuracy, assistance fit, useful next steps, attribution, assessment validity, completion, and latency; retain valid alternatives and requested explanations as controls; and include held-out conversations and course-expert adjudication.

## Configuration and reproducibility

The model is served locally on the DGX Spark. The profile distinguishes requested settings from observed server metadata; these matched for the checked fields.

| Setting | Captured value |
| --- | --- |
| Served alias | `Qwen3.8-Flash-Next-FP4-Local` |
| Model / revision | `nvidia/Qwen3.8-Flash-Next-NVFP4` / `fc694b54fb0174e0913e6adf86691ef85a4ead47` |
| SGLang | `0.5.21` |
| Context / maximum output | 32,768 / 4,096 tokens |
| Temperature / thinking | `0` / disabled |
| Speculation | Requested `NEXTN`; server reports the effective `EAGLE` alias, 3 steps, top-k 1, 4 draft tokens |
| Concurrent requests / cached tokens | 2 / 131,072 |
| Chunked prefill / Mamba cache | 2,048 tokens / 20 slots |
| Embedding offload | File-backed PLE offload |
| Python / agent dependencies | Python 3.13.16; Deep Agents 0.7.5; LangChain Core 1.5.4; LangChain OpenAI 1.5.1 |

Direct content delivery, the reduced tutor harness, course-evidence reuse, deterministic assessment saving, and the content-after-assessment guard remained enabled. Assessment-prior prefetch remained disabled. These are the existing deployment settings, not treatments introduced by this experiment. Temperature zero is not a guarantee of identical complete agent trajectories.

The fixed fixture SHA-256 is `91dcef4c71706e735a0ff501ddcb8ae5dc0df37722c9a3e02fd3d8e5f4ad5a98`. To run the same fixed inputs again on a configured Spark, choose a **new** output filename:

```sh
.venv/bin/python scripts/evaluate_tutoring.py \
  --backend sglang \
  --cases-file output/profiling/cs35l-studentlike-cases-20261018.json \
  --repetitions 1 \
  --label cs35l-replication \
  --output output/profiling/cs35l-replication.json
```

That reproduces inputs and recording, not necessarily responses. The reactive report embeds its temporary runner source, frozen scenario plan, selected student messages, and the rationale for each follow-up. Replaying those messages produces a fixed transcript test; a new reactive evaluation must choose plausible follow-ups to its own observed replies.

Embedded scripts in the evidence records preserve how the original analysis was performed. They are historical provenance, not portable runnable utilities: some use workstation-specific paths, local-only raw captures, or temporary dependencies. A fresh checkout can run the fixed fixture using the command above on a configured Spark, but cannot recompute every historical result without those raw captures. The artifact table below covers both committed supporting records and local-only evidence.

| Local artifact under `output/profiling/` | Role |
| --- | --- |
| `cs35l-studentlike-cases-20261018.json` | Frozen 36-episode fixed fixture, including six repeats |
| `cs35l-adaptive-plan-20261018.json` | Predeclared starting situations and learner constraints |
| `cs35l-studentlike-v2.json`, `cs35l-adaptive-v2.json` | Raw conversations, private structures, model calls, timing, source hashes, and configuration |
| `cs35l-semantic-review-v1.json` | Per-turn findings from one reviewer applying both pedagogical lenses |
| `cs35l-reference-checks-v1.json`, `cs35l-react-reference-v1.json` | Concrete technical checks and primary-documentation references |
| `cs35l-summary-v1.json` | Computed denominators, timing summaries, validation, and embedded aggregation code |
| `cs35l-verification-v1.json` | Artifact hashes, identical-repeat checks, source comparison, and document consistency checks |
| `cs35l-source-manifest-20261018.json` | Downloaded course/source and review-resource hashes |
| `cs35l-experiment-amendments-20261018.json` | Pilot exclusions, protocol changes, and reactive failure handling |
| `cs35l-pedagogy-breadth-v1.json`, `cs35l-adaptive-v1.json` | Excluded formal-prompt and input-channel pilots |

The raw harness field `quality: not_reviewed` remains untouched: review lives in the separate semantic record. The course revision cited by retrieval is `24db6bf0d4e4ebfa1331e6c772e1844cbaf2d9aa`; it is not assumed identical to the separately downloaded current page. Runtime source hashes, rather than Git HEAD alone, identify the code under test because the Spark checkout has local changes and a different HEAD from this workstation.

Final verification matched all 39 captured file hashes in each cohort to their local counterparts, including the corresponding fixture. The Spark's final fixed-run source comparison also had no mismatches. The same resident server PID remained present and returned HTTP 200 from its health endpoint. The six repeat pairs have identical student-message sequences; all 111 attempted turns have review entries, with the failed public reply explicitly unassessed. Production source, scripts, tests, and dependency files have no diff from implementation commit `484305f`. Only the evaluation evidence and documentation were added or updated for this experiment.

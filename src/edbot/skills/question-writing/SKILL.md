---
name: question-writing
description: How to write clear, well-calibrated assessment questions from retrieved source material
---

## Goal
Produce a question that accurately tests understanding of a concept, using only
facts present in retrieved sources.

## Question structure
- State the question unambiguously — a student shouldn't need to guess what's
  being asked.
- For multiple choice: write exactly one clearly correct answer and 3 plausible
  distractors. Distractors should reflect common misconceptions, not random
  wrong facts — this is what makes a question diagnostic rather than trivial.
- For short-answer/free-response: specify what a complete answer must include.

## Difficulty calibration
- Recall-level: tests whether the student remembers a fact or definition.
- Application-level: requires using a concept in a new scenario, not just
  restating it.
- Analysis-level: requires comparing, explaining a relationship, or justifying
  a conclusion.
Match the level to what was requested; default to application-level if
unspecified — pure recall questions are usually too easy to be useful.

## Grounding rules
- Every claim in the question stem and every distractor must be traceable to
  retrieved source content. Do not introduce outside facts, even if you're
  confident they're true.
- If a source is ambiguous or contradicts another source, prefer the more
  specific/detailed source.
- Never fabricate a citation. If you can't point to which retrieved chunk
  supports an answer, don't include that fact in the question.

## Output format
Always include:
1. **Question** — the question as the student will see it.

## Common failure modes to avoid
- Questions answerable from general knowledge without needing the source at all.
- Trick questions that hinge on wording rather than understanding.
- Multiple "correct" answers among the choices.
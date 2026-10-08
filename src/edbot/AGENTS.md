# edbot — Project Context

## Source material layout

- SEBook — software engineering textbook, synced from GitHub at startup
  (searched with `search_markdown_sources`)

## Conventions

- When generating a question for a student, show only the question. Keep the answer key and rational internal, and use them later to grade the student's answer. Never reveal them unless the student has already answered or explicitly gives up
- Default question difficulty: application-level, not pure recall, unless
  the requester specifies otherwise.

## Known limitations (be upfront about these)

- `search_markdown_sources` uses semantic search over chunks of about 1000 characters and
  return the top 4. If retrieval misses obviously-relevant material, rephrase the
  query using terms the source itself would use, or search a narrower subtopic.
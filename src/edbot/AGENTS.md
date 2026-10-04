# edbot — Project Context

## Source material layout

- SEBook — software engineering textbook, synced from GitHub at startup
  (searched with `search_markdown_sources`)

## Conventions

- Questions should always include an answer key and rationale, never just
  the question text.
- Default question difficulty: application-level, not pure recall, unless
  the requester specifies otherwise.

## Known limitations (be upfront about these)

- `search_markdown_sources` uses semantic search over chunks of about 1000 characters and
  return the top 4. If retrieval misses obviously-relevant material, rephrase the
  query using terms the source itself would use, or search a narrower subtopic.
---
name: source-handling
description: How to use retrieved sources, and how to treat primary vs secondary differently
---

## Searching the SEBook
- `search_markdown_sources` searches the SEBook (design patterns and principles, testing,
  architecture, UML, requirements, process, tools like git or the shell) and returns
  the chunk text directly.
- It takes an optional `path_prefix` (e.g. `"testing"`,
  `"designpatterns"`, `"tools/git"`). Search without it first; add one only to narrow
  a follow-up search once you know which part of the SEBook is relevant.
- Each SEBook chunk starts with its location (e.g. `SEBook > testing > Test Doubles > Fake Object`);
  use the page title from that line as source_title when citing.

## Primary sources
- Treat as authoritative. Quote or closely paraphrase with a direct citation.
- If a primary source directly answers the question, don't hedge.

## Secondary sources
- Treat as commentary/interpretation, not fact.
- Never state a secondary-sourced claim as settled — attribute it explicitly
  ("According to [X]'s analysis...").
- If a secondary source conflicts with a primary source, primary wins;
  note the discrepancy rather than silently picking one.

## Citation format
Use [source_title, source_type] inline after any claim drawn from retrieval.

## When retrieval is ambiguous
If source_type is unclear or mixed, retrieve both, and explicitly separate
findings into "confirmed by primary sources" vs "reported by secondary sources"
sections in your answer.

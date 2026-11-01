# Spec 002: Deterministic Explorer Harness

Status: implemented

Extends: `001-flash-context-explorer`

## Summary

The explorer harness treats the model as a source of search/read intent, not as
the owner of finalization. The controller now owns evidence accumulation,
citation validation, loop termination, and citation-mode rendering.

## Requirements

- Stop when assistant content contains valid controller-verified citations, even
  if the same assistant message also contains tool calls.
- Validate citations before accepting them:
  - path is repository-relative;
  - path does not contain traversal components;
  - path resolves to an allowed file under `repo_root`;
  - line range is positive and ordered;
  - range is covered by prior `read_file` evidence or by one bounded
    verification read;
  - final citation count is capped.
- Break exact repeated tool-call loops before executing the repeated call.
- Prompt the model to use a FastContext-style `<final_answer>` block for final
  citations.
- Render citation-mode text output only from validated citations:
  `path:start-end` lines, or `NO_CITATIONS_FOUND`.
- Preserve the CLI-first core and MCP-as-adapter architecture.
- Preserve read-only repository safety boundaries for model-requested reads and
  controller verification reads.

## Non-Goals

- No new vector store, embedding layer, context-pack format, or MCP-first API.
- No repository mutation tools.
- No broad benchmark harness.

## Public Behavior

Citation mode is deterministic:

```text
src/flash_context/agent.py:65-230
src/flash_context/agent.py:317-397
```

The prompt asks for a `<final_answer>` block, but that block is advisory model
formatting. Model prose is not emitted in citation-mode text output. JSON output
preserves the existing result shape and includes normalized `answer`,
`citations`, `turns_used`, `truncated`, and `warnings`.

## Coverage

Regression tests cover:

- citation content plus trailing tool calls;
- repeated `read_file` loop termination;
- prose stripping in citation mode;
- hallucinated citation rejection;
- bounded verification reads for unseen citation ranges;
- MCP delegation through the same core behavior;
- traversal rejection through shared path safety;
- opt-in endpoint-backed e2e exploration using this repository as the target.

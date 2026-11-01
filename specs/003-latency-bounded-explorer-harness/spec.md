# Spec 003: Latency-Bounded Explorer Harness

Status: implemented

Extends: `002-deterministic-explorer-harness`

## Summary

The deterministic harness now bounds endpoint latency risk by limiting prompt
growth, discouraging broad reads, and finalizing from validated narrow evidence
before another broad or unrelated read expands the conversation.

The controller still owns finalization. The model only proposes search/read
intent and is prompted toward compact `<final_answer>` output.

## Requirements

- Endpoint requests include deterministic generation controls:
  - `max_tokens` from `FLASH_CONTEXT_MAX_COMPLETION_TOKENS`, default `512`;
  - `temperature` from `FLASH_CONTEXT_TEMPERATURE`, default `0`.
- Endpoint request timeout defaults to `120` seconds and is configurable with
  `FLASH_CONTEXT_TIMEOUT_SECONDS`.
- Model observations sent back to the endpoint are capped by
  `FLASH_CONTEXT_MAX_OBSERVATION_CHARS`, default `6000`.
- Model-requested `read_file` calls are bounded by `FLASH_CONTEXT_MAX_READ_LINES`,
  default `120`:
  - omitted line bounds read a bounded preview;
  - overly broad line ranges are clamped;
  - clamped observations preserve truncation metadata.
- Controller verification reads for model citations are not clamped by
  `FLASH_CONTEXT_MAX_READ_LINES`; they still obey repository safety and byte caps.
- In citation mode, once non-truncated narrow read evidence exists, the
  controller may stop before executing another broad `read_file` request for an
  already-read path and return the best validated read evidence.

## Non-Goals

- No vector store, embeddings, context-pack output, or MCP-first API.
- No repository write tools.
- No retry/backoff scheduler.

## Public Behavior

Citation-mode text remains controller-rendered `path:start-end` lines or
`NO_CITATIONS_FOUND`.

JSON output preserves the existing result shape. Truncation caused by read-line
or observation-character caps is reflected through existing truncation metadata
and warnings where applicable.

## Coverage

Regression tests cover:

- configuration precedence and defaults for latency controls;
- request payload `max_tokens` and `temperature`;
- bounded previews for model reads without line ranges;
- endpoint observation content caps;
- deterministic finalization before another broad read on a seen path when
  narrow evidence already exists;
- opt-in endpoint-backed e2e exploration using this repository as the target.

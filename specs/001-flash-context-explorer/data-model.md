# Data Model: Flash Context Explorer

This document defines implementation-level data shapes. Names are descriptive;
the implementing agent may adjust exact class names while preserving fields and
semantics.

## Settings

Represents effective configuration after CLI, project-root `config.yaml`,
project-root `.env`, and process environment resolution.

Fields:

- `base_url: str`: OpenAI-compatible endpoint base URL.
- `model: str`: Model name sent to the endpoint.
- `api_key: str | None`: Optional API key from env or config.
- `max_turns: int`: Maximum model/tool iterations; default `6`.
- `max_read_bytes: int`: Per-read content cap; default `12000`.
- `max_grep_results: int`: Grep hit cap; default `50`.
- `traj_dir: Path | None`: Optional run log directory. Relative paths from
  `config.yaml` resolve from the `flash-context` project root; env overrides are
  used as supplied.
- `ignore: list[str]`: Directory/file patterns to exclude.
- `timeout_seconds: float`: Endpoint request timeout; default `120`.
- `max_observation_chars: int`: Max content chars sent back to the model in a
  tool observation; default `6000`.
- `max_read_lines: int`: Max lines returned to the model for a model-requested
  `read_file`; default `120`.
- `max_completion_tokens: int`: Endpoint completion cap; default `512`.
- `temperature: float`: Endpoint sampling temperature; default `0`.
- `max_parallel_tools: int`: Max same-turn local tool calls to execute
  concurrently; default `4`.

Primary env vars:

- `FLASH_CONTEXT_BASE_URL`
- `FLASH_CONTEXT_MODEL`
- `FLASH_CONTEXT_API_KEY`
- `FLASH_CONTEXT_MAX_TURNS`
- `FLASH_CONTEXT_MAX_READ_BYTES`
- `FLASH_CONTEXT_MAX_GREP_RESULTS`
- `FLASH_CONTEXT_TRAJ_DIR`
- `FLASH_CONTEXT_TIMEOUT_SECONDS`
- `FLASH_CONTEXT_MAX_OBSERVATION_CHARS`
- `FLASH_CONTEXT_MAX_READ_LINES`
- `FLASH_CONTEXT_MAX_COMPLETION_TOKENS`
- `FLASH_CONTEXT_TEMPERATURE`
- `FLASH_CONTEXT_MAX_PARALLEL_TOOLS`

## ExploreRequest

Input passed to the exploration core by CLI or MCP.

Fields:

- `query: str`
- `repo_root: Path`
- `max_turns: int`
- `citation: bool`
- `format: Literal["text", "json"]`

Validation:

- Query must not be blank.
- `repo_root` must exist and be a directory.
- `max_turns` must be positive and bounded.

## ToolCall

Model-requested local operation.

Fields:

- `id: str`
- `name: Literal["read_file", "repo_glob", "repo_grep"]`
- `arguments: dict[str, object]`

Validation:

- Unknown tool names are rejected.
- Arguments are validated before any filesystem access.

## ToolObservation

Bounded local response returned to the model.

Fields:

- `tool_call_id: str`
- `ok: bool`
- `path: str | None`
- `line_range: str | None`
- `content: str | None`
- `hits: list[SearchHit]`
- `truncated: bool`
- `error: ExplorerError | None`

Rules:

- Paths are repository-relative.
- Content is omitted for denied paths.
- Truncation is explicit.
- Model-facing observations may be smaller than the local read result when
  latency caps apply.

## SearchHit

Single grep match.

Fields:

- `path: str`
- `line: int`
- `text: str`

Rules:

- `path` is repository-relative.
- `text` is capped to a sane display width.

## Citation

Evidence included in the final answer.

Fields:

- `path: str`
- `start_line: int | None`
- `end_line: int | None`
- `reason: str | None`

Rules:

- Citation paths are repository-relative.
- Missing line ranges are allowed only when the model returns path-level
  evidence and no line data is available.

## ExploreResult

Normalized result returned by the core.

Fields:

- `query: str`
- `repo_root: str`
- `answer: str`
- `citations: list[Citation]`
- `raw_locations: list[RawLocation]`
- `turns_used: int`
- `truncated: bool`
- `warnings: list[str]`

Rules:

- Text output defaults to citation-first formatting.
- JSON output preserves all fields.

## RawLocation

Controller-read source text for a final citation range.

Fields:

- `path: str`
- `start_line: int`
- `end_line: int`
- `text: str`
- `truncated: bool`

Rules:

- Paths are repository-relative.
- Text is read only after citation validation and merged-range normalization.
- Trajectory logs must omit raw `text`.

## Trajectory

Optional audit log for one exploration run.

Fields:

- `request: ExploreRequest`
- `turns: list[ModelTurn]`
- `result: ExploreResult | None`
- `error: ExplorerError | None`

Rules:

- Do not include denied file contents.
- Preserve enough metadata to debug unsupported tool calls, truncation, endpoint
  errors, and final citation quality.

## ExplorerError

Structured error returned across CLI, core, and MCP.

Fields:

- `code: str`
- `message: str`
- `retryable: bool`
- `details: dict[str, object]`

Required codes:

- `CONFIG_MISSING_ENDPOINT`
- `REPO_NOT_FOUND`
- `QUERY_EMPTY`
- `PATH_OUTSIDE_ROOT`
- `PATH_DENIED`
- `TOOL_OUTPUT_TRUNCATED`
- `ENDPOINT_UNREACHABLE`
- `ENDPOINT_TIMEOUT`
- `ENDPOINT_BAD_RESPONSE`
- `UNSUPPORTED_TOOL_CALL`
- `MAX_TURNS_EXCEEDED`

# Feature Specification: Flash Context Explorer

Feature Branch: `001-flash-context-explorer`

Created: 2026-06-18

Status: Draft

Input: User description: "Create Spec Kit-compatible planning artifacts for Python 3.13+, using a CLI-first FastContext-style repository explorer core with MCP as an adapter. Do not create OKF files; use plain human-readable docs under docs/."

## User Scenarios & Testing

### User Story 1 - Explore a Repository from the CLI (Priority: P1)

A coding agent or developer asks a focused question about a local repository and
receives compact file paths and line ranges that identify the relevant context.

Why this priority: The CLI validates the core value without coupling the product
to MCP client behavior.

Independent Test: Run `flash-context explore` against a fixture repository and
verify the answer cites relevant files and line ranges without modifying files.

Acceptance Scenarios:

1. Given a local repository and configured OpenAI-compatible endpoint, When
   the user runs `flash-context explore --query "Find validation logic" --repo .
   --max-turns 6 --citation`, Then the command returns cited repository paths
   and line ranges.
2. Given no endpoint configuration, When the command runs, Then it exits with a
   clear configuration error and does not attempt repository writes.
3. Given `--format json`, When the command completes, Then the output is
   machine-readable and contains the query, repository root, citations, and
   final answer.

---

### User Story 2 - Keep Repository Access Local and Read-only (Priority: P1)

The explorer executes only bounded local read/search tools, rejects unsafe paths,
and never mutates the target repository.

Why this priority: The product is intended for coding agents, so the security
boundary must be correct before model-driven exploration is useful.

Independent Test: Exercise local tool calls against fixture files, denylisted
paths, traversal attempts, symlinks, and large outputs.

Acceptance Scenarios:

1. Given a path outside the repository root, When `read_file` is requested, Then
   the tool rejects it.
2. Given a symlink inside the repository that points outside the root, When the
   target is read, Then the tool rejects it.
3. Given a large file or broad grep, When the tool executes, Then output is
   capped and truncation is explicit.

---

### User Story 3 - Use the Same Explorer Through MCP (Priority: P2)

An MCP-capable client calls `explore_repository` and receives the same
repository-context result that the CLI would produce for equivalent input.

Why this priority: MCP integration is valuable for agents, but it should not
define or duplicate the core architecture.

Independent Test: Invoke the MCP adapter with a mocked core and verify request
mapping, schema, and returned result.

Acceptance Scenarios:

1. Given an MCP client and configured server, When the client calls
   `explore_repository`, Then the adapter delegates to the exploration core.
2. Given invalid repository root input, When the MCP tool is called, Then it
   returns the same safety error semantics as the CLI/core.

---

### User Story 4 - Audit Exploration Runs (Priority: P3)

A maintainer can inspect optional trajectory logs to understand model tool calls,
local observations, truncation, and final citations.

Why this priority: Debugging endpoint quality and tool limits is necessary for
hardening but not required for the MVP.

Independent Test: Enable trajectory logging for a fixture run and verify the log
contains no secrets from denylisted files.

Acceptance Scenarios:

1. Given `FLASH_CONTEXT_TRAJ_DIR` is set, When exploration completes, Then a run
   log is written under that directory.
2. Given a denied file path is encountered, When the run is logged, Then the log
   records the rejection without including file contents.

### Edge Cases

- Query is empty or only whitespace.
- Repository path does not exist or is not a directory.
- Endpoint times out, returns invalid JSON, or requests an unsupported tool.
- Model repeats identical tool calls before producing a valid final answer.
- File contains binary or invalid text content.
- Grep pattern is invalid for the selected search implementation.
- Final answer has no citations.

## Requirements

### Functional Requirements

- FR-001: The system MUST provide a CLI command named `flash-context explore`.
- FR-002: The CLI MUST accept `--query`, `--repo`, `--max-turns`, `--citation`,
  and `--format text|json`.
- FR-003: The system MUST target Python 3.13+.
- FR-004: The system MUST support configuration from project-root
  `config.yaml`, project-root `.env`, and process environment variables.
- FR-005: The system MUST communicate with an OpenAI-compatible chat completion
  endpoint for the first backend target.
- FR-006: The system MUST expose only read-only repository tools to the model:
  `read_file`, `repo_glob`, and `repo_grep`.
- FR-007: The system MUST resolve tool paths under the configured repository
  root before reading or searching.
- FR-008: The system MUST reject path traversal, symlink escape, and denylisted
  files or directories.
- FR-009: The system MUST cap read bytes, grep result counts, and model
  exploration turns.
- FR-010: The system MUST return controller-validated repository-relative file
  paths and line ranges in citation mode.
- FR-011: The system MUST provide an MCP adapter exposing
  `explore_repository(query, repo_root?, max_turns?, citation?)`.
- FR-012: The MCP adapter MUST delegate to the same exploration core as the CLI.
- FR-013: The system MUST avoid repository mutation in all tools and adapters.
- FR-014: The system MUST support optional trajectory logging.
- FR-015: The system MUST defer MCP-first `context_search`, `context_pack`, and
  `context_get` tools until after the MVP.

### Key Entities

- Repository Root: Local directory boundary for all tool execution.
- Exploration Query: User-provided question about repository context.
- Tool Call: Model-requested read-only operation.
- Tool Observation: Bounded output returned from a local tool to the model.
- Citation: Repository-relative path plus line range supporting the final answer.
- Exploration Run: Query, config, model turns, tool calls, observations, and
  final answer.
- MCP Request: Adapter-level invocation mapped to an exploration run.

## Success Criteria

### Measurable Outcomes

- SC-001: CLI fixture test returns at least one correct cited file-line range for
  a known query.
- SC-002: Path traversal and symlink escape tests pass with no file content
  leakage.
- SC-003: Read and grep cap tests prove output limits are enforced.
- SC-004: Mock endpoint contract test completes a multi-turn READ/GLOB/GREP
  exploration without external network access.
- SC-005: MCP adapter test verifies schema and delegation to the core.
- SC-006: `uv run pytest`, `uv run ruff check .`, and type checks are expected
  release gates for implementation.

## Assumptions

- Package name is `flash-context`; Python package is `flash_context`.
- Runtime baseline is Python 3.13+ managed with `uv`.
- First backend is OpenAI-compatible chat completions, not ranked context search.
- OKF is deferred; this repo uses plain markdown docs for human-readable plans.
- MCP is an adapter and must not become the core exploration abstraction.

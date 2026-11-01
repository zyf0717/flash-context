# Tasks: Flash Context Explorer

Input: Design documents from `/specs/001-flash-context-explorer/`

Prerequisites: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/`

Tests: Include tests for each user story before implementation.

Organization: Tasks are grouped by implementation phase and user story to keep
the CLI MVP independently shippable before MCP.

## Format: `[ID] [P?] [Story] Description`

- `[P]`: Can run in parallel with other tasks touching different files.
- `[Story]`: User story traceability from `spec.md`.
- Paths are implementation targets, not currently existing files.

## Phase 1: Setup

Purpose: Establish Python 3.13+ package and test baseline.

- [x] T001 Create `pyproject.toml` with `requires-python = ">=3.13"` and `uv`
  compatible project metadata.
- [x] T002 Create `src/flash_context/` package and `tests/` layout.
- [x] T003 [P] Add console script target `flash-context`.
- [x] T004 [P] Configure `pytest`, `ruff`, and selected type checker.
- [x] T005 [P] Add `.env.example` and `config.yaml` example.

## Phase 2: Foundational Read-only Tooling

Purpose: Security boundary that blocks all model, CLI, and MCP behavior.

- [x] T006 [US2] Add path resolution and root enforcement in
  `src/flash_context/tools/safety.py`.
- [x] T007 [P] [US2] Add denylist pattern handling for `.git`, env files,
  secrets, virtualenvs, and build outputs.
- [x] T008 [P] [US2] Add unit tests for traversal and symlink escape rejection.
- [x] T009 [US2] Implement `read_file` with byte caps and line ranges.
- [x] T010 [US2] Implement `repo_glob` with ignore handling.
- [x] T011 [US2] Implement `repo_grep` with result caps and line numbers.
- [x] T012 [P] [US2] Add unit tests for read caps, grep caps, denylist, and
  normal fixture reads/searches.

Checkpoint: Local tools are safe and testable without model access.

## Phase 3: Core Exploration Loop

Purpose: Convert model tool-call turns into safe local exploration and citations.

- [x] T013 [US1] Add `Settings`, `ExploreRequest`, `ExploreResult`, and error
  types in `src/flash_context/types.py` and `config.py`.
- [x] T014 [P] [US1] Add config precedence tests for CLI overrides, env, YAML,
  and defaults.
- [x] T015 [US1] Implement OpenAI-compatible HTTP client in
  `src/flash_context/llm.py`.
- [x] T016 [US1] Implement tool schema generation and tool-call dispatch in
  `src/flash_context/agent.py`.
- [x] T017 [US1] Enforce max turns, unsupported tool rejection, endpoint timeout,
  and bad-response handling.
- [x] T018 [P] [US1] Add mocked endpoint contract tests for READ/GLOB/GREP
  multi-turn exploration.
- [x] T019 [US1] Normalize final output into citation-first text and structured
  JSON result.

Checkpoint: Core can answer fixture questions using a mocked endpoint.

## Phase 4: User Story 1 - CLI MVP

Goal: Provide `flash-context explore` for direct local use.

Independent Test: Run against fixture repo with mocked endpoint and verify cited
file-line output.

- [x] T020 [US1] Implement CLI parser for `flash-context explore`.
- [x] T021 [US1] Add `--query`, `--repo`, `--max-turns`, `--citation`, and
  `--format text|json`.
- [x] T022 [US1] Map structured errors to explicit exit codes and stderr
  messages.
- [x] T023 [P] [US1] Add CLI contract tests for required args, defaults, text
  output, JSON output, and config failure.
- [x] T024 [US1] Add integration test with fixture repository and mocked
  endpoint.

Checkpoint: CLI MVP is usable without MCP.

## Phase 5: User Story 3 - MCP Adapter

Goal: Expose the same core through one MCP tool.

Independent Test: Invoke `explore_repository` with a mocked core and verify
schema plus delegation.

- [x] T025 [US3] Add MCP server entrypoint in `src/flash_context/mcp_server.py`.
- [x] T026 [US3] Register `explore_repository(query, repo_root?, max_turns?,
  citation?)`.
- [x] T027 [US3] Map MCP request data to `ExploreRequest`.
- [x] T028 [US3] Return core result or structured error without duplicating
  safety or endpoint logic.
- [x] T029 [P] [US3] Add MCP contract tests for tool schema, valid invocation,
  invalid root, and core delegation.

Checkpoint: MCP behavior matches CLI/core behavior.

## Phase 6: User Story 4 - Audit and Hardening

Goal: Make the tool safe and diagnosable for daily agent use.

Independent Test: Enable trajectory logging and inspect log content for allowed
metadata and denied content omission.

- [x] T030 [US4] Implement optional trajectory logging under
  `FLASH_CONTEXT_TRAJ_DIR`.
- [x] T031 [P] [US4] Add tests proving denied file contents are not logged.
- [ ] T032 [US4] Add structured stderr logging for CLI and MCP server events.
- [x] T033 [P] [US4] Add README quickstart, MCP config examples, and
  troubleshooting notes.
- [x] T034 [US4] Run `uv run pytest`, `uv run ruff check .`, and the selected
  type checker.

## Dependencies & Execution Order

- Phase 1 has no dependencies.
- Phase 2 depends on Phase 1 and blocks all user-facing behavior.
- Phase 3 depends on Phase 2.
- Phase 4 depends on Phase 3 and is the MVP release path.
- Phase 5 depends on Phase 3 and should start after CLI output shape stabilizes.
- Phase 6 depends on CLI and MCP behavior existing.

## Parallel Opportunities

- T003, T004, and T005 can run in parallel after T001.
- T007, T008, and T012 can run in parallel with tool implementation when test
  fixtures are stable.
- T014 and T018 can run in parallel with endpoint client implementation.
- T023 and T024 can run after CLI argument shape is fixed.
- T029 can run in parallel with adapter wiring if the core interface is mocked.

## Implementation Strategy

MVP first:

1. Complete setup and read-only tool safety.
2. Complete mocked endpoint exploration loop.
3. Ship CLI with citation output.
4. Add MCP adapter.
5. Harden logging, trajectories, docs, and distribution.

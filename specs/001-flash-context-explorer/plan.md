# Implementation Plan: Flash Context Explorer

Branch: `001-flash-context-explorer` | Date: 2026-06-18 | Spec: [spec.md](spec.md)

Input: Feature specification from `/specs/001-flash-context-explorer/spec.md`

## Summary

Build a Python 3.13+ repository exploration harness with a CLI MVP. The core
loop sends a focused query to an OpenAI-compatible FastContext-style endpoint,
executes only root-scoped read-only local tools, and returns compact citations.
MCP is added as an adapter over the same core after the CLI path works.

## Technical Context

Language/Version: Python 3.13+

Primary Dependencies: `httpx`, `pydantic`, `pydantic-settings`, `typer` or
`argparse`, official MCP Python SDK for the adapter

Storage: Local files only; optional trajectory logs under `.flash-context/` or
`FLASH_CONTEXT_TRAJ_DIR`

Testing: `pytest`, mocked HTTP transport, fixture repositories

Target Platform: Local developer machines and remote development environments
where the target repository is mounted

Project Type: Single Python CLI package with optional MCP server entrypoint

Performance Goals: Tool observations remain bounded by configured byte/result
caps; default exploration stops within six model turns

Constraints: Read-only repository access, root-scoped path resolution, no model
serving, no vector database ownership, no repository mutation

Scale/Scope: Local repositories large enough for coding-agent workflows; initial
quality depends on the configured FastContext-compatible endpoint

## Constitution Check

No project constitution is present. Apply repository-level constraints from
AGENTS.md:

- Keep changes surgical and architecture-preserving.
- Avoid broad workspace exploration.
- Prefer production-grade, bounded, read-only behavior.
- Surface security and operational failure modes directly.

## Project Structure

### Documentation

```text
specs/001-flash-context-explorer/
|-- spec.md
|-- plan.md
|-- research.md
|-- data-model.md
|-- quickstart.md
|-- tasks.md
`-- contracts/
    |-- cli.md
    |-- explorer-tools.md
    `-- mcp.md
```

### Source Code

```text
pyproject.toml
src/flash_context/
|-- __init__.py
|-- cli.py
|-- config.py
|-- agent.py
|-- llm.py
|-- mcp_server.py
|-- types.py
|-- logging.py
`-- tools/
    |-- __init__.py
    |-- safety.py
    |-- read.py
    |-- glob.py
    `-- grep.py
tests/
|-- unit/
|-- contract/
|-- integration/
`-- fixtures/
```

Structure Decision: Use one package and one core service boundary. CLI and MCP
entrypoints import the same config, safety, tools, and agent modules.

## Implementation Phases

### Phase 1: Package and contracts

- Create `pyproject.toml` with `requires-python = ">=3.13"`.
- Add console script `flash-context`.
- Add source and test directories.
- Encode CLI, MCP, and local tool contracts in tests before behavior.

### Phase 2: Read-only local tools

- Implement root resolution and path safety in `tools/safety.py`.
- Implement `read_file`, `repo_glob`, and `repo_grep`.
- Enforce denylist, byte caps, result caps, relative paths, and line ranges.

### Phase 3: Model loop

- Implement OpenAI-compatible chat completion client.
- Provide tool schemas and route tool calls to local tools.
- Stop on final answer, unsupported tool call, endpoint error, or max turns.
- Normalize result into citation-first text and structured JSON.

### Phase 4: CLI

- Implement `flash-context explore`.
- Load config from project-root `config.yaml`, project-root `.env`, process
  environment, and CLI overrides.
- Return explicit exit codes for config, repository, endpoint, and safety errors.

### Phase 5: MCP adapter

- Register `explore_repository`.
- Map MCP input to the same core request type used by CLI.
- Return the same result shape or structured error.

### Phase 6: Hardening

- Add trajectory logging, structured stderr logs, docs, and examples.
- Add full pytest, ruff, and type-check release gates.
- Prepare `uvx`-friendly packaging.

## Complexity Tracking

No current violations. The adapter split is intentionally minimal: MCP is not a
separate execution engine.

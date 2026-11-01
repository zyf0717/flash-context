# AGENTS.md

These instructions apply to the entire repository.

## Role of This File

This file defines durable guidance for agents working on `flash-context`.

It is not the detailed implementation plan. Feature requirements, contracts,
task ordering, schemas, and exact interface details should live in `specs/`,
`docs/`, contracts, and tests.

When there is a conflict:

1. Security invariants in this file take precedence.
2. Active specs and public contracts define intended behavior.
3. Code and tests define implemented behavior.
4. Documentation must be updated to reflect public behavior changes.

Do not treat examples in this file as exhaustive or permanently fixed unless
they are stated as invariants.

## Project Contract

`flash-context` is a Python read-only context explorer for AI agents, currently
focused on codebases and repositories. Exploration also applies to documentation,
configuration, and other local text files within a selected root.

The intended product shape is:

```text
CLI / MCP adapter
        |
        v
shared exploration core
        |
        v
OpenAI-compatible FastContext-style endpoint
        |
        v
root-scoped local read-only tools
```

The CLI is the MVP path unless the active specs say otherwise. MCP should be an
adapter over the shared core, not a separate implementation or primary
abstraction.

The project is not a generic RAG framework, context-pack generator, or
MCP-first tool collection unless the specs are explicitly changed.

## Primary Sources of Truth

Use these locations for detailed product and implementation guidance:

* `specs/` for feature specs, plans, tasks, and contracts.
* `docs/implementation-order.md` for current sequencing and phase guidance.
* `docs/` for durable human-facing documentation.
* `README.md` for public project overview and usage.

Spec folders may use numbered names such as `001-something`,
`002-something-else`, and so on. The number is a stable spec identifier and
rough creation-order marker, not a permanent priority signal.

Do not assume `001-*` is always the current or only active spec. Determine the
active implementation scope from spec status, task files, and
`docs/implementation-order.md`.

Keep `README.md`, specs, contracts, tests, and user-facing docs aligned when
changing public behavior.

## Scope Boundaries

Follow the active specs unless the user explicitly redirects.

Do not introduce major new product shapes without updating specs first. In
particular:

* Do not build an MCP-first implementation if the active spec says CLI-first.
* Do not duplicate CLI and MCP logic; both should delegate to the shared core.
* Do not add extra MVP tools or product concepts unless the active specs call
  for them.
* Do not add an OKF bundle or `.specify/` scaffold unless explicitly requested.
* Do not turn local repository tools into write-capable tools.

Prefer small, inspectable implementation steps that preserve the documented
architecture.

## Architecture Principles

Use a single coherent Python package for the implementation.

Keep these concerns separated:

* user interfaces, such as CLI and MCP adapters
* shared exploration orchestration
* LLM/OpenAI-compatible endpoint client
* configuration loading and precedence
* repository safety validation
* read-only repository tools
* typed request/result/error models
* trajectory or diagnostic logging

CLI and MCP entrypoints should stay thin. They should parse input, call the
shared core, and render or return the result.

Filesystem safety should be centralized rather than reimplemented separately by
each tool.

Prefer typed data models for public and internal boundaries, including requests,
results, tool calls, observations, citations, settings, and structured errors.

The first backend target is an OpenAI-compatible chat-completions style
exploration loop unless the active specs say otherwise. Do not assume a ranked
context-search endpoint unless the specs change.

## Security Invariants

All repository access must be read-only.

The explorer, model loop, CLI, MCP adapter, and local tools must never mutate
the target repository.

Before reading repository content, local code must enforce safety checks. The
model may request tool calls, but local code owns validation and enforcement.

Required safety properties:

* Resolve requested paths under `repo_root` after symlink resolution.
* Reject absolute paths outside `repo_root`.
* Reject path traversal and symlink escapes.
* Reject denylisted files and directories such as `.git`, `.env*`, private
  keys, secrets, virtualenvs, dependency directories, and build outputs.
* Cap file read sizes, grep result counts, and model/tool-call turns.
* Return repository-relative paths where possible.
* Preserve explicit truncation metadata.
* Do not log denied file contents, secret values, or sensitive raw payloads.

Reject model-requested shell commands, writes, network access, unknown tools, or
filesystem operations outside the approved read-only tool set.

Security behavior should be tested, not merely documented.

## Public Interfaces

Public interfaces are defined in the active specs and contracts.

At minimum, the project is expected to expose:

* a CLI exploration path
* JSON-compatible output for machine use
* configuration through environment variables and/or project config
* an MCP adapter that preserves the shared core result/error shape

Do not change public behavior without updating the relevant contract, tests,
README, and user-facing docs.

Detailed flags, environment variables, config precedence, MCP schema, and error
formats belong in the contracts and specs.

## Testing Requirements

Add or update tests with implementation changes. Safety and contract behavior
are not optional.

Required areas of coverage include:

* path traversal rejection
* symlink escape rejection
* denylist enforcement without content leakage
* file read byte caps
* grep result caps
* configuration precedence
* mocked OpenAI-compatible endpoint tool-call loop
* CLI output shape and exit behavior
* MCP schema and delegation to the shared core
* fixture repository integration with cited file-line evidence

Automated tests must not require a real external FastContext service.

Release-check commands and tool choices should be documented consistently in
the project docs and CI configuration.

## Documentation Discipline

When changing public behavior, update the relevant source of truth.

Use this general mapping:

* CLI behavior: update CLI contract, quickstart, README, and tests.
* Local repository tools: update explorer-tool contracts and safety tests.
* MCP behavior: update MCP contract and delegation tests.
* Configuration behavior: update config contract/docs and precedence tests.
* Phase order or implementation scope: update `docs/implementation-order.md`
  and the relevant spec task files.

Do not let `README.md`, specs, contracts, and implementation drift apart.

## Agent Working Style

Submit changes from a `dev/` branch through a pull request to `main`.
Use squash or rebase merging after required CI checks pass. Do not push directly
to `main` or use the owner's bypass unless the owner explicitly requests it.

Prefer implementation that is simple, typed, testable, and easy to inspect.

Before adding abstractions, check whether they are required by the active specs.
Before changing architecture, update the relevant plan/spec first or clearly
explain why the existing plan is obsolete.

When uncertain, preserve these defaults:

* CLI-first MVP
* shared core
* MCP as adapter
* read-only local tools
* OpenAI-compatible endpoint
* root-scoped safety
* tests with mocked external services
* documentation updated with public behavior

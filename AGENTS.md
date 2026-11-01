# AGENTS.md

These instructions apply to the entire repository.

## Product and architecture

Build a Python read-only context explorer: thin CLI/MCP adapters → shared core →
OpenAI-compatible chat completions → root-scoped `read_file`/`repo_glob`/`repo_grep`.
Keep configuration, endpoint access, safety, evidence resolution, orchestration,
and diagnostic logging cohesive. Prefer typed boundaries and simple explicit
flow; do not add RAG infrastructure or write-capable repository tools.

Current sources of truth:

- `docs/contracts.md`: shared evidence, payloads, tools, safety, termination.
- `docs/cli.md`, `docs/mcp.md`: adapter-specific behavior.
- `docs/configuration.md`: settings and precedence.
- `README.md`: installation and getting started.
- `specs/README.md`: proposal status and historical specs; completed plans are not
  current contracts. New architectural scope needs a spec before implementation.

Security invariants below take precedence, then current contracts/active specs,
then code/tests. Explicit user instructions override workflow defaults.

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

Automated tests must not require a real external model endpoint.

Release-check commands and tool choices should be documented consistently in
the project docs and CI configuration.

## Documentation Discipline

Update the canonical contract and affected examples/tests when changing public
behavior. Shared rules belong in `docs/contracts.md`; adapter/configuration docs
link there. Preserve historical specs through the history index and Git instead
of repeating completed plans or release-specific policy across current docs.

Record user-visible changes and migration instructions in `CHANGELOG.md` under
`[Unreleased]`. A version-bump PR promotes these notes to a dated version entry.
GitHub release notes are extracted from that entry after PyPI install verification;
follow `docs/releasing.md` and preserve published notes and artifacts on retries.

## Agent Working Style

Submit changes from a `dev/` branch through a pull request to `main`.
Use squash or rebase merging after required CI checks pass. Do not push directly
to `main` or use the owner's bypass unless the owner explicitly requests it.

Prefer implementation that is simple, typed, testable, and easy to inspect.

Review the diff before finalizing: remove redundant checks, dead options,
forwarding helpers, and duplicate documentation. Keep changes executable and
verify the checks documented in CONTRIBUTING.md.

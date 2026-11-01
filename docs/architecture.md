# Architecture and scope

`flash-context` is a CLI-first context explorer for AI agents, currently focused
on codebases and repositories. Its local tools also apply to documentation,
configuration, and other text files within a selected root. CLI and MCP adapters
call a shared core, which talks to an OpenAI-compatible endpoint and executes
root-scoped, read-only local tools.

```text
CLI / MCP adapter → shared exploration core → model endpoint
                             ↓
                  read_file / repo_glob / repo_grep
```

## Implementation status

This repository has the initial Python 3.13+ implementation for spec `001`:
CLI, shared exploration core, read-only repository tools, OpenAI-compatible
chat-completions client, optional trajectory logging, and a thin MCP adapter.
It also includes spec `002` hardening for deterministic controller-owned
finalization and citation-mode rendering, plus spec `003` latency controls for
bounded endpoint prompt growth, and spec `004` same-turn parallel local tool
execution. Spec `005` adds a deterministic exact path/symbol fast path for
trivial evidence lookups. Spec `006` fixes configuration ownership to
project-root `config.yaml` plus `.env`/environment overrides. Spec `007` adds
raw source snippets for validated, merged citation ranges. Spec `008` adds
package validation and tag-driven TestPyPI/PyPI releases.

Primary planning artifacts:

- [Spec Kit feature spec](../specs/001-flash-context-explorer/spec.md)
- [Implementation plan](../specs/001-flash-context-explorer/plan.md)
- [Task breakdown](../specs/001-flash-context-explorer/tasks.md)
- [Deterministic explorer harness](../specs/002-deterministic-explorer-harness/spec.md)
- [Latency-bounded explorer harness](../specs/003-latency-bounded-explorer-harness/spec.md)
- [FastContext-compatible parallel tool executor](../specs/004-fastcontext-parallel-tool-executor/spec.md)
- [Exact path/symbol fast path](../specs/005-exact-path-symbol-fast-path/spec.md)
- [Project-root YAML and env configuration](../specs/006-project-root-yaml-dotenv-config/spec.md)
- [Raw location evidence with merged ranges](../specs/007-raw-location-payload/spec.md)
- [PyPI release pipeline](../specs/008-pypi-release/spec.md)
- [Implementation order](implementation-order.md)

## FastContext inspiration

The exploration design draws on FastContext's delegated explorer approach:

- Delegated repository exploration: CLI/MCP call a focused explorer core that
  returns evidence for a downstream coding agent.
- Read-only tools: the only model-callable repository tools are
  `read_file`, `repo_glob`, and `repo_grep`, corresponding to FastContext's
  `Read`, `Glob`, and `Grep`.
- Same-turn parallel tool calling: independent local tool calls from one model
  message execute concurrently, while model endpoint requests remain serial.
- Compact evidence: citation mode renders controller-validated `path:start-end`
  lines, with the model prompted toward a `<final_answer>` block.

The [FastContext paper](https://arxiv.org/abs/2606.14066) has been withdrawn, and
its [original repository](https://github.com/microsoft/fastcontext) is no longer
publicly available. These are historical design references; the endpoint
contract is OpenAI-compatible chat completions with tool calling.

## Scope

In scope:

- Local, read-only exploration of codebases, documentation, and other text files.
- Root-scoped `read_file`, `repo_glob`, and `repo_grep` tools.
- OpenAI-compatible chat completion loop with bounded tool observations.
- Same-turn concurrent execution for independent local tool calls.
- CLI output with file paths and line-range citations.
- MCP adapter that delegates to the CLI/core implementation.

Out of scope for the MVP:

- Repository mutation.
- Vector database ownership or embedding/model serving.
- MCP-first `context_search`, `context_pack`, and `context_get` tools.
- OKF bundle output.

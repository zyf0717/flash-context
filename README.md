# flash-context

[![CI](https://github.com/zyf0717/flash-context/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/zyf0717/flash-context/actions/workflows/ci.yml)
[![PyPI version](https://img.shields.io/pypi/v/flash-context)](https://pypi.org/project/flash-context/)
[![Python versions](https://img.shields.io/pypi/pyversions/flash-context)](https://pypi.org/project/flash-context/)
[![License](https://img.shields.io/pypi/l/flash-context)](LICENSE)

A lightweight, model-agnostic repository explorer that combines deterministic
lookup with delegated LLM search to deliver compact, validated source evidence.
Available as a Python CLI and Model Context Protocol (MCP) server.

Delegate recursive, repetitive file search and reading to a utility model
behind an OpenAI-compatible endpoint. The calling agent receives validated
file-line citations and source snippets to use in its main task.

Codebases and repositories are the current focus; the same tools explore
documentation, configuration, and other local text files. CLI and MCP share one
exploration core with read-only tools, path safety, and resource limits.
Scans and regex execution are bounded; partial results report truncation.
Citation validation checks safe paths and existing line coverage, not semantic
relevance or minimal ranges. Citation precision depends on the explorer model.
Implementation queries continue past documentation-only citations within the turn budget; documentation-only
fallbacks carry incomplete-result metadata and warnings. Build outputs such as
`dist/` remain excluded; inspect a source checkout for implementation evidence.
Optional metadata-only trajectory logs must stay outside the inspected repository.

Inspired by [FastContext](https://arxiv.org/abs/2606.14066), a now-withdrawn paper
on separating repository exploration from task solving, using specialized models
to return focused file-line evidence while reducing the coding agent's context
and token overhead.

## Quickstart

Requires Python 3.13+, `uv`, and an OpenAI-compatible model endpoint with tool
calling support.

```bash
uv tool install flash-context
export FLASH_CONTEXT_BASE_URL=http://localhost:1234/v1
export FLASH_CONTEXT_MODEL=your-model

flash-context explore --repo . --query "Find the request validation logic"
```

Replace the endpoint and model with your settings. Set `FLASH_CONTEXT_API_KEY`
if authentication is required. Installed commands use environment variables;
source checkouts also support project-root `config.yaml` and `.env`.

Default output is repository-relative citations:

```text
src/api/validation.py:42-88
```

Use `--format json` for structured results with source snippets, or
`--max-turns 6` to set the exploration limit. Exact path and unique symbol
lookups can resolve locally without an endpoint. See the
[CLI contract](specs/001-flash-context-explorer/contracts/cli.md) for options,
output schemas, and exit codes.

For example, `--query 'httpx/_client.py'` returns a bounded file preview, while
`--query 'BaseTransport'` returns its definition if unique within a complete
Python source/stub scan. Local successes report `turns_used: 0` in JSON.

Warnings go to stderr in both output formats. An empty result after scan-budget
exhaustion exits **6** while preserving stdout; a complete empty search exits
**0**. For large repositories, see [scan-budget tuning](docs/configuration.md#large-repositories).

## MCP

```bash
uvx --from 'flash-context[mcp]' flash-context mcp --transport stdio
```

Exposes `explore_repository(query, repo_root?, max_turns?, citation?)`.
See [MCP integration](docs/mcp.md) for editor configuration and source launches.

## Documentation

- [Configuration](docs/configuration.md): endpoint settings, precedence, and limits.
- [Architecture and scope](docs/architecture.md): design, status, specs, and references.
- [Contributing](CONTRIBUTING.md): development setup, tests, and pull requests.
- [Changelog](CHANGELOG.md): release history and migration instructions.
- [Releasing](docs/releasing.md): package checks and tag-driven TestPyPI/PyPI publishing.

## License

[Apache License 2.0](LICENSE).

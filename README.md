# flash-context

[![CI](https://github.com/zyf0717/flash-context/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/zyf0717/flash-context/actions/workflows/ci.yml)
[![PyPI version](https://img.shields.io/pypi/v/flash-context)](https://pypi.org/project/flash-context/)
[![Python versions](https://img.shields.io/pypi/pyversions/flash-context)](https://pypi.org/project/flash-context/)
[![License](https://img.shields.io/pypi/l/flash-context)](LICENSE)

A lightweight, model-agnostic repository search tool for AI agents. Find relevant
code, documentation, and configuration through exact lookups or model-guided
search, and retrieve compact snippets with validated file-line citations.
Available as a Python CLI and Model Context Protocol (MCP) server.

CLI and MCP share a read-only core with path safety and resource limits. Exact
lookups can resolve locally; broader queries delegate search and reading to a
utility model through an OpenAI-compatible endpoint. Validation checks paths and
source ranges; semantic relevance remains the model's judgment. See
[safety and evidence validation](docs/contracts.md#read-only-tools-and-safety)
for details and limitations.

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

flash-context search --repo . --query "Find the request validation logic"
```

Replace the endpoint and model with your settings. Set `FLASH_CONTEXT_API_KEY`
if authentication is required. Installed commands use environment variables;
source checkouts also support project-root `config.yaml` and `.env`.

Default output is repository-relative citations:

```text
src/api/validation.py:42-88
```

Use `--no-citation` for prose, `--format json` for results with snippets, or
`--max-turns N` to override the 12-turn default. Exact path and unique symbol
lookups can resolve locally without an endpoint. See the
[CLI contract](docs/cli.md) for options,
output schemas, and exit codes.

For example, `--query 'httpx/_client.py'` returns a bounded file preview, while
`--query 'BaseTransport'` returns its definition if unique within a complete
Python source/stub scan. Local successes report `turns_used: 0` in JSON.

Use `--query 'httpx/_client.py#BaseClient._redirect_method'` to resolve a parsed
definition locally. A leaf name such as `httpx/_client.py#_redirect_method` works
when unique in that file. Unresolved anchors fall back to model-guided search.

Warnings go to stderr in both output formats. An empty result after scan-budget
exhaustion exits **6** while preserving stdout; a complete empty search exits
**0**. For large repositories, see [scan-budget tuning](docs/configuration.md#large-repositories).

Models select symbol or line anchors; the controller resolves bounded syntax
regions and returns structural precision metadata. See the
[shared contract](docs/contracts.md) for evidence rules and limits.

## MCP

```bash
uvx --from 'flash-context[mcp]' flash-context mcp --transport stdio
```

Exposes `search_repository(query, repo_root?, max_turns?, citation?)`.
See [MCP integration](docs/mcp.md) for editor configuration and source launches.

## Documentation

- [Configuration](docs/configuration.md): endpoint settings, precedence, and limits.
- [Architecture and scope](docs/architecture.md): shared core and module responsibilities.
- [Contributing](CONTRIBUTING.md): development setup, tests, and pull requests.
- [Changelog](CHANGELOG.md): release history and migration instructions.
- [Releasing](docs/releasing.md): package checks and tag-driven TestPyPI/PyPI publishing.

## License

[Apache License 2.0](LICENSE).

# flash-context

Read-only context exploration and retrieval for AI agents,
available as a Python CLI and Model Context Protocol (MCP) server.

Ask natural-language questions across source code, documentation, configuration,
and other local text files, and get validated file-line citations and snippets.
The current focus is codebases and repositories. Both interfaces share one
exploration core, backed by an OpenAI-compatible FastContext-style endpoint.
Local tools enforce read-only access, path safety, and resource limits.

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
- [Releasing](docs/releasing.md): package checks and tag-driven TestPyPI/PyPI publishing.

## License

[Apache License 2.0](LICENSE).

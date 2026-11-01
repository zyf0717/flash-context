# Quickstart: Flash Context Explorer

This quickstart describes the implemented CLI-first behavior for spec `001`.

## Prerequisites

- Python 3.13+
- `uv`
- OpenAI-compatible model endpoint with tool calling support
- Local repository to inspect

## Install from PyPI

```bash
uv tool install flash-context
flash-context --help
```

Use `uv tool install 'flash-context[mcp]'` for the MCP adapter, or launch it
directly with `uvx --from 'flash-context[mcp]' flash-context mcp --transport stdio`.
Published installations use process environment variables and CLI overrides;
YAML and `.env` discovery is available only in a source checkout.

## Install for Development

```bash
uv sync --locked --extra mcp
uv run flash-context --help
```

## Configure Endpoint

For source development, default operator config lives in the `flash-context`
project root:

```bash
cp config.yaml.example config.yaml
```

The inspected repository's config files are not loaded implicitly. This keeps
the explorer's operator config independent of whatever target folder is being
read.

Relative paths in `config.yaml`, including `explorer.traj_dir`, resolve from
the `flash-context` project root. Environment path overrides are used as
provided.

Use project-root `.env` or process environment variables for overrides:

```bash
cp .env.example .env
```

Or export process environment variables:

```bash
export FLASH_CONTEXT_BASE_URL=http://100.105.153.85:1234/v1
export FLASH_CONTEXT_MODEL=Qwen/Qwen3.5-4B
export FLASH_CONTEXT_API_KEY=
export FLASH_CONTEXT_MAX_TURNS=6
export FLASH_CONTEXT_MAX_READ_BYTES=12000
export FLASH_CONTEXT_MAX_GREP_RESULTS=50
export FLASH_CONTEXT_TRAJ_DIR=  # Disabled; logs must be outside the target repo.
export FLASH_CONTEXT_TIMEOUT_SECONDS=120
export FLASH_CONTEXT_MAX_OBSERVATION_CHARS=6000
export FLASH_CONTEXT_MAX_READ_LINES=120
export FLASH_CONTEXT_MAX_COMPLETION_TOKENS=512
export FLASH_CONTEXT_TEMPERATURE=0
export FLASH_CONTEXT_MAX_PARALLEL_TOOLS=4
```

Optional operator config:

```yaml
explorer:
  max_turns: 6
  citation: true
  ignore:
    - ".git"
    - ".venv"
    - "node_modules"
    - "dist"
    - "build"

model:
  base_url: "http://100.105.153.85:1234/v1"
  model: "Qwen/Qwen3.5-4B"
  api_key: ""
  timeout_seconds: 120
  max_completion_tokens: 512
  temperature: 0

tools:
  max_read_bytes: 12000
  max_grep_results: 50
  max_observation_chars: 6000
  max_read_lines: 120
  max_parallel_tools: 4
```

The repository includes `config.yaml.example` with this shape.

## Run CLI Exploration

Use the CLI first for direct local runs and debugging:

```bash
uv run flash-context explore \
  --query "Find the request validation logic" \
  --repo . \
  --max-turns 6 \
  --citation
```

Expected text shape:

```text
src/api/validation.py:42-88
tests/test_validation.py:101-140
```

JSON output:

```bash
uv run flash-context explore \
  --query "Find the request validation logic" \
  --repo . \
  --format json
```

## Local lookups and diagnostics

Bare-path lookups such as `--query 'src/flash_context/agent.py'` return bounded
previews locally. Exact citations and unique Python definitions can also finish
without endpoint configuration; these results report `turns_used: 0`.

Warnings appear on stderr in both CLI formats. If no citations are found after
a scan budget or tool processing deadline is exhausted, the command exits 6
while preserving stdout. Partial cited results and complete empty searches exit
0. See [large-repository tuning](../../docs/configuration.md#large-repositories).

## Run MCP Adapter

Use MCP when an MCP-capable editor or agent should call repository exploration
as a tool. The MCP adapter delegates to the same core as the CLI.

Install the optional MCP dependency before using the adapter:

```bash
uv sync --extra mcp
```

Server command:

```bash
uv run flash-context mcp \
  --transport stdio
```

Expected tool:

```text
explore_repository(query, repo_root?, max_turns?, citation?)
```

Generic MCP client config shape:

```json
{
  "mcpServers": {
    "flash-context": {
      "command": "uv",
      "args": [
        "run",
        "--project",
        "/path/to/flash-context",
        "--extra",
        "mcp",
        "flash-context",
        "mcp",
        "--transport",
        "stdio"
      ],
      "env": {
        "FLASH_CONTEXT_BASE_URL": "http://100.105.153.85:1234/v1",
        "FLASH_CONTEXT_MODEL": "Qwen/Qwen3.5-4B"
      }
    }
  }
}
```

## Validate

```bash
uv run pytest
uv run ruff check .
uv run mypy
```

CI checks Python 3.13 and 3.14, plus clean wheel and source installs.
[Release instructions](../../docs/releasing.md) describe the publishing pipeline.

Errors are printed to stderr as `CODE: message`; denied paths never include file
contents in the error payload.

Implementation questions continue past documentation-only citations within the
turn budget. Documentation-only fallbacks retain evidence with `truncated: true`
and a warning; partial cited results still exit 0. Build outputs remain excluded.

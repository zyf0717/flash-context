# MCP integration

Use MCP when an editor or AI agent should call context exploration as a
tool. The adapter delegates to the same core and safety boundary as the CLI.

## Published package

Requires Python 3.13+ and `uv`. Launch the stdio server with the MCP extra:

```bash
uvx --from 'flash-context[mcp]' flash-context mcp --transport stdio
```

Alternatively, install it with `uv tool install 'flash-context[mcp]'` and run
`flash-context mcp --transport stdio`.

Generic MCP client configuration:

```json
{
  "mcpServers": {
    "flash-context": {
      "command": "uvx",
      "args": [
        "--from",
        "flash-context[mcp]",
        "flash-context",
        "mcp",
        "--transport",
        "stdio"
      ],
      "env": {
        "FLASH_CONTEXT_BASE_URL": "http://localhost:1234/v1",
        "FLASH_CONTEXT_MODEL": "your-model"
      }
    }
  }
}
```

Replace the endpoint and model with your settings. Installed commands use
process environment variables; see [Configuration](configuration.md).

## Source development

From the project root:

```bash
uv sync --locked --extra mcp
uv run --locked flash-context mcp --transport stdio
```

To launch from another working directory, use:

```bash
uv run --project /path/to/flash-context --extra mcp flash-context mcp --transport stdio
```

For an MCP client launching the source checkout, set `command` to `uv` and
split the arguments from that command into the client's `args` array. Source
checkouts also load project-root `config.yaml` and `.env`.

## Tool

```text
explore_repository(query, repo_root?, max_turns?, citation?)
```

Set `repo_root` explicitly to select the repository; otherwise it defaults to
the server's working directory. Results contain validated citations and raw
source snippets, or a structured error. See the
[MCP contract](../specs/001-flash-context-explorer/contracts/mcp.md) for schemas
and delegation behavior.

Tool discovery includes a description explaining when to explore and what
evidence is returned. Citation objects contain `path`, `start_line`, and
`end_line`; the unused `reason` field has been removed. Validation establishes
safe, existing line coverage rather than semantic relevance or minimum ranges.

Scan limits, incomplete-result warnings, and metadata-only external logging use
the same [configuration](configuration.md) and core behavior as the CLI.

## Exploration progress and evidence

For implementation-intent questions, documentation-only citations are provisional:
the controller requests source evidence within the remaining turn budget. If only
documentation remains at termination, citations and snippets are retained with
`truncated: true` and an implementation-unverified warning. Detection uses query
terms and common documentation filenames; it does not establish semantic relevance.
Explicit documentation requests and exact lookups retain their existing behavior.
Repeated calls reuse observations while fresh sibling calls execute; an entirely
repeated batch stops exploration. Resource limits and result schemas are unchanged.

MCP initialization reports the installed flash-context package version.

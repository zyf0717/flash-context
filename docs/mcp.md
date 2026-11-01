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

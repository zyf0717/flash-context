# MCP Contract

MCP is an adapter over the exploration core. It must not duplicate local tool
safety, endpoint handling, or result normalization.

## Server Command

Published-package command (Python 3.13+):

```bash
uvx --from 'flash-context[mcp]' flash-context mcp --transport stdio
```

Published installations use process environment variables for configuration;
source checkouts also load project-root `config.yaml` and `.env`.

Expected development command:

```bash
uv run flash-context mcp --transport stdio
```

Options:

- `--transport stdio`: MCP transport. Only `stdio` is in scope.

## Tool: `explore_repository`

Purpose: Explore a local repository using the same core as the CLI and return
compact file-line evidence for a focused coding question.
The discovered tool description must explain its read-only exploration use and
the returned citations and bounded source snippets.

Input schema:

```json
{
  "query": "string",
  "repo_root": "string | null",
  "max_turns": "integer | null",
  "citation": "boolean | null"
}
```

Defaults:

- `repo_root`: current working directory or configured root if omitted.
- `max_turns`: effective config default, normally `6`.
- `citation`: `true`.

Output schema:

```json
{
  "query": "Find the request validation logic",
  "repo_root": "/absolute/path/to/repo",
  "answer": "src/api/validation.py:42-88",
  "citations": [
    {
      "path": "src/api/validation.py",
      "start_line": 42,
      "end_line": 88
    }
  ],
  "raw_locations": [
    {
      "path": "src/api/validation.py",
      "start_line": 42,
      "end_line": 88,
      "text": "def validate_request(payload):\n    ...\n",
      "truncated": false
    }
  ],
  "turns_used": 4,
  "truncated": false,
  "warnings": []
}
```

Error schema:

```json
{
  "error": {
    "code": "PATH_OUTSIDE_ROOT",
    "message": "Requested path is outside the repository root",
    "retryable": false,
    "details": {}
  }
}
```

## Deferred MCP Tools

The following MCP-first tools are intentionally out of scope for the MVP:

- `context_search`
- `context_pack`
- `context_get`

They assume a ranked context endpoint contract rather than the selected
FastContext-style exploration harness.

## Hardening behavior

The [hardening spec](../../009-explorer-hardening/spec.md) applies through the
shared core. Result shape is unchanged. Token-limited completions return usable
evidence with `truncated: true` and a warning, or `ENDPOINT_BAD_RESPONSE` when no
evidence exists. Empty completions without tool calls are endpoint errors.
In-root trajectory destinations are configuration errors. `PATH_UNREADABLE`
identifies filesystem access failures; tool budget failures use
`TOOL_LIMIT_EXCEEDED`. CLI exit categories remain configuration 3, path 4,
endpoint 5, and other exploration errors 6.

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

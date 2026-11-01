# CLI Contract

## Command

Install with `uv tool install flash-context` (Python 3.13+).
Published installations load defaults, process environment variables, and CLI
overrides. Only source checkouts discover project-root `config.yaml` and `.env`,
as specified in [spec 006](../../006-project-root-yaml-dotenv-config/spec.md).

```bash
flash-context explore [OPTIONS]
```

## Required Options

- `--query TEXT`: Focused repository-context question. Must not be blank.
- `--repo PATH`: Repository root to inspect. Defaults may later resolve to `.`,
  but tests should cover explicit path first.

## Optional Options

- `--max-turns INTEGER`: Maximum model/tool iterations. Default: `6`.
- `--citation`: Prefer citation-only final text output.
- `--format text|json`: Output format. Default: `text`.

## Text Output

Citation mode returns compact evidence:

```text
src/api/validation.py:42-88
tests/test_validation.py:101-140
```

If the model provides explanatory text, citation-mode text output still emits
only controller-validated citations. If no citation is accepted, text output is
exactly `NO_CITATIONS_FOUND`.

The model is prompted to produce final citations in a `<final_answer>` block,
but the CLI does not print that block wrapper in citation mode.

Model-facing tool observations are latency bounded. Model-requested reads may
be returned as bounded previews, but local repository safety and read byte caps
still apply before any content is observed.

Bare repository-relative file paths (optionally quoted), exact citations, and
uniquely defined Python symbols may resolve without endpoint configuration or
contact. Bare paths return a preview bounded by read byte and line caps, with
actual line coverage and truncation metadata. Fast-path successes emit only
controller-validated citations and report `turns_used: 0` in JSON output.

Validation establishes safe paths and existing line coverage, not relevance or
minimality. The model is prompted to prefer implementation source for coding
questions and the smallest supporting line ranges. Source-search continuation
uses the existing turn budget.

## JSON Output

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

## Exit Codes

- `0`: Success, including partial cited results and complete empty searches.
- `2`: CLI usage or validation error.
- `3`: Configuration error.
- `4`: Repository/root safety error.
- `5`: Endpoint error.
- `6`: Exploration failed before final answer, or no citations were found after
  a tool scan budget or processing deadline was exhausted.

## Error Output

Errors are written to stderr and must not include unrestricted file contents or
secret values.

Result warnings are also printed to stderr as `WARNING: message` in both text
and JSON modes. A truncated result without warnings emits
`WARNING: Result truncated`. Stdout retains its normal citation/JSON shape even
when an empty budget-limited result exits 6. Budget diagnostics are
`glob scan budget exhausted`, `grep scan budget exhausted`,
`read scan budget exhausted`, and `grep match timed out`. Ordinary result caps
alone do not change the exit status.

Example:

```text
CONFIG_MISSING_ENDPOINT: FLASH_CONTEXT_BASE_URL is required
```

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

## Exact-symbol evidence

Conservative exact-identifier lookups, including a scoped path plus identifier,
require the case-sensitive whole query token inside every accepted cited range.
The controller checks cached source lines or performs a safe bounded read;
filenames, nearby lines, substrings, and byte-capped partial tokens do not qualify.
The same check applies to read-derived fallback evidence and early termination.
References, assignments, documentation, and other languages remain eligible;
this lexical guarantee does not establish a definition or semantic relevance.
Bare file previews, explicit citation requests, and semantic queries retain their
existing behavior.

Python source/stub preflight results distinguish unique, missing, ambiguous, and
incomplete definitions. The model receives this result without a second scan.
A complete missing result establishes zero Python definition-pattern matches,
not repository-wide absence. Incomplete scans retain their limit diagnostics.

Unsupported citations trigger focused feedback within the existing turn budget.
An explicit `NO_CITATIONS_FOUND` ends the search without promoting previous reads.
Normal termination without accepted evidence returns `NO_CITATIONS_FOUND`, empty
`citations` and `raw_locations`, and `query symbol not found in verified evidence`,
even in non-citation mode. Actual scan, turn, and token-limit diagnostics remain
separate. CLI exit semantics and public schemas are unchanged; token exhaustion
without usable evidence remains `ENDPOINT_BAD_RESPONSE`.

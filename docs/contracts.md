# Shared exploration contract

CLI and MCP delegate to `explore(ExploreRequest, Settings)`. A request contains
`query`, `repo_root`, `max_turns` (6), and `citation` (true). The query must be
nonblank, turns positive, and root an existing directory. Output formatting is
an adapter concern. Configuration ownership and precedence are defined in
[configuration](configuration.md).

## Result

Both adapters expose this JSON-compatible shape:

```json
{
  "query": "Where is validation implemented?",
  "repo_root": "/absolute/repo",
  "answer": "src/validation.py:1-2",
  "citations": [{
    "path": "src/validation.py", "start_line": 1, "end_line": 2,
    "precision": {
      "range_lines": 2, "boundary_kind": "definition",
      "symbol": "validate", "query_token_in_range": null,
      "definitions_spanned": 1
    }
  }],
  "raw_locations": [{
    "path": "src/validation.py", "start_line": 1, "end_line": 2,
    "text": "def validate():\n    pass\n", "truncated": false
  }],
  "turns_used": 2, "truncated": false, "warnings": []
}
```

Citation lines are inclusive, positive, and repository-relative. `precision`
reports structure: `range_lines`, `boundary_kind` (`definition`, `syntax`,
`line_window`, `explicit_range`, `preview`, or `exact_match`), nullable `symbol`,
nullable exact-query `query_token_in_range`, and nullable `definitions_spanned`.
Null means unmeasured. Metadata does not establish relevance.

Raw snippets have their own byte cap and actual returned line coverage. Model
citations and snippets use the same request-local source snapshot. No accepted
evidence yields `NO_CITATIONS_FOUND`, empty citations and snippets. Exact-symbol
misses also emit `query symbol not found in verified evidence`.

## Local routing and evidence

Bare paths, optionally quoted, return byte/line-bounded previews. Conservative
explicit range or path-plus-token lookups and unique Python `.py`/`.pyi`
definition-pattern matches can complete without an endpoint (`turns_used: 0`).
Python preflight distinguishes unique, missing, ambiguous, and incomplete scans;
missing means no Python definition matches, not repository-wide absence.
Incomplete scans retain diagnostics. Adjacent local ranges may merge.

Exact-identifier queries require the case-sensitive whole token inside each
accepted region, including derived fallback anchors. Filenames, nearby lines,
substrings, and a byte-capped partial token do not qualify. Assignments,
references, documentation, and other languages remain eligible lexical evidence.

## Model anchors and boundaries

Models propose `path#qualified.symbol`, `path:line`, or `path:start-end`.
Local code computes ranges; model ranges are normalized to complete parsed syntax units. Invalid ranges
receive one correction opportunity inside the existing turn budget. Range
expansions obey citation budgets atomically; they are never silently cropped.
Each turn returns its own accepted anchors, feedback, and diagnostics.
Prose uses the original anchor-to-citation mapping, including overlapping units.

Bundled Tree-sitter grammars cover Python, JS/JSX, TS/TSX, C/C++, C#, Java, Go,
Rust, Ruby, PHP, Bash, Lua, Kotlin, and Swift. Names use dotted qualification;
ambiguous overloads require line anchors. Definitions include decorators/export
wrappers. Large definitions require line anchors inside smaller complete syntax
regions or headers. Distinct syntax units remain separate.

Unsupported or invalid syntax uses line windows of ±5 lines, bounded by available
complete lines. Parser outcomes distinguish unsupported, invalid, limited, timed
out, and successfully parsed input. Input caps and parser deadlines emit explicit
incomplete-result diagnostics. Symbols require parsed definitions. Grammars are
bundled and never downloaded during exploration.

Defaults: 120 lines per model citation, 600 unique file-lines total, 16 citations,
16 candidate anchors, 1 MiB parser input per file. Cumulative parser input obeys
`max_scan_bytes`; parsing/traversal obey tool deadlines. Explicit user ranges,
previews, and deterministic local lookups retain read byte caps and are exempt
from model precision budgets. Source lines follow LF boundaries, including CRLF;
Unicode separators inside strings do not create additional lines.

## Progress and termination

With at least two turns, one turn is reserved for final evidence selection;
`max_turns=1` retains a single discovery turn. Unscoped semantic queries start
with grep/glob tools, then enable reads. Stalled discovery or prose without
usable citations can enter selection early. Selection receives the query and
bounded, deduplicated observations in a fresh conversation without tools.
Successful early answers and explicit `NO_CITATIONS_FOUND` remain terminal.

Valid selected evidence ends exploration before trailing tool calls. Calls
repeated in later turns reuse observations; fresh siblings still execute, and
an entirely repeated batch ends discovery. Exact queries may stop before a broad read
when sufficient narrow evidence is already verified. Semantic queries never
promote unselected reads; exact queries may derive verified token anchors.

Implementation questions continue past documentation-only citations within the
remaining turns. If only documentation survives, results retain it with
`truncated: true` and an implementation-unverified warning. Intent detection is
lexical; explicit documentation and exact lookups retain their behavior.

`NO_CITATIONS_FOUND` ends exploration without promoting previous reads.
Token-limited completions return usable evidence with truncation and a warning,
or `ENDPOINT_BAD_RESPONSE` without evidence. Empty messages without calls are
endpoint errors. Turn exhaustion and incomplete evidence remain explicit warnings.
Internal diagnostic identities determine truncation and CLI exits; messages are
rendered for consumers. Warnings do not carry repository contents or raw errors.

## Read-only tools and safety

Only `read_file`, `repo_glob`, and `repo_grep` are model-callable. Each returns
`ok`, `truncated`, optional `warnings`, and either data or a structured `error`.
Same-turn calls may execute concurrently; observations preserve call order.
Unknown tools, shell commands, writes, and model-requested network access fail.

| Tool | Arguments | Data |
| --- | --- | --- |
| `read_file` | required `path`; optional positive `start_line`, `end_line` | `path`, `line_range` (`start-end`), `content` |
| `repo_glob` | required repository-relative `pattern` | `matches` |
| `repo_grep` | required regex `pattern`; optional `glob`, positive `max_results` | `hits`: `path`, `line`, `text` |

Reads enforce byte/line limits before model observation; model content is line
numbered and character bounded. Grep caps results, accepts patterns up to 4096
characters, and skips lines over 64 KiB with a warning. Scans have byte, entry,
and processing limits; partial observations are marked truncated. A read unable
to reach its first requested line returns `TOOL_LIMIT_EXCEEDED`. Deadlines cannot
interrupt stalled kernel I/O.

Paths are validated both lexically and after symlink resolution. Traversal,
root escapes, and denied paths are rejected before reading. Directory symlinks
are never traversed; file symlinks are validated and deduplicated. Literal/scoped
searches start at the literal path prefix, with ancestor deny checks.

Denied directories include `.git`, `.flash-context`, `.aws`, `.ssh`, `.venv`,
`venv`, `node_modules`, `dist`, `build`, and `secrets`. Denied files include `.env*`,
`*.pem`, `*.key`, and private-key names `id_rsa`, `id_ed25519`, `id_dsa`, `id_ecdsa`.
Operator ignores add exclusions. Increasing budgets never bypasses these rules.

MCP errors use `{"error": {"code": "PATH_DENIED", "message": "...",
"retryable": false, "details": {}}}`. CLI maps error categories to exit codes.
Trajectory logs are optional metadata-only records outside the target root;
see [configuration](configuration.md#trajectory-logs).

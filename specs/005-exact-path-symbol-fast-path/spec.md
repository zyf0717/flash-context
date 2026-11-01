# Spec 005: Exact Path/Symbol Fast Path

Status: implemented

Extends: `004-fastcontext-parallel-tool-executor`

## Summary

Add a conservative deterministic preflight before the model loop. It
short-circuits only when the query contains exact locally verifiable evidence:
explicit repository-relative citations, explicit file-path symbol/text lookups,
or one unique pathless definition match.

Successful fast-path results are evidence-only: controller-normalized citations
with `turns_used=0`. They do not require endpoint configuration and must not
include explanations, prose, model-authored rationale, or semantic summaries.

Anything requiring interpretation, synthesis, comparison, semantic judgment, or
unclear confidence continues into the existing FastContext model loop unchanged.

## Requirements

- Run exact preflight after request validation and repository-root resolution,
  before endpoint configuration is required.
- Return immediately only when exact local evidence is sufficient.
- Preserve existing citation-mode output:
  `path:start-end` lines, or `NO_CITATIONS_FOUND`.
- Preserve existing JSON result shape.
- Preserve repository safety:
  - safe path resolution;
  - denylist enforcement;
  - symlink escape rejection;
  - read byte caps;
  - no denied file content leakage.
- Preserve the existing FastContext-compatible model loop for all non-fast-path
  cases.

## Fast-Path Cases

### Bare File Path

A query consisting solely of one repository-relative file path, optionally
quoted with matching backticks or single/double quotes, can return a bounded
preview without endpoint configuration. Use the existing safe reader with
`max_read_bytes`, `max_read_lines`, and scan limits. Cite only actual preview
line coverage and preserve truncation. Missing, empty, denied, or unsafe files
retain model-loop routing. Extensionless file names are also supported.

### Explicit Citation

If the query contains a parseable repository-relative citation such as:

```text
src/flash_context/agent.py:10-30
```

the controller should verify the path and line range with safe bounded
`read_file`. If verification succeeds, return the normalized citation with
`turns_used=0`.

### Explicit Path Plus Exact Symbol/Text

If the query contains a safe repository-relative file path and an exact
backticked, quoted, or token-like target, the controller may scan only that file.

Examples:

```text
In src/flash_context/config.py, find `max_parallel_tools`.
Find "def explore" in src/flash_context/agent.py.
```

Allowed short-circuits in this case:

- exact Python definition matches;
- exact assignment/config-style matches;
- exact token/text matches in the explicitly named file.

Return matching line citations only when the result count is positive and within
the final citation cap.

### Exact Symbol Without Path

If the query contains an exact symbol but no explicit path:

- scan safe files only, with v1 pathless definition eligibility limited to
  Python source files;
- short-circuit only if exactly one high-confidence definition-pattern match
  exists across the repository;
- search anchored definition patterns directly, so ordinary references do not
  exhaust the match cap before definition filtering;
- pathless assignment/config-style matches do not short-circuit in v1;
- if multiple files match, multiple definition patterns match, limits are
  exceeded, or confidence is otherwise unclear, continue into the model loop.

High-confidence pathless definition patterns for v1:

```text
def SYMBOL
async def SYMBOL
class SYMBOL
```

## Model Loop Routing

Continue into the normal model loop when:

- no exact match exists;
- a path is missing, denied, unsafe, or ambiguous;
- multiple definition matches exist;
- only pathless assignment/config-style matches exist;
- candidate count exceeds the final citation cap;
- the query asks for interpretation, synthesis, comparison, behavior,
  ownership, architecture, "why", or "how";
- confidence is unclear.

Model-loop routing must preserve current endpoint error behavior. Endpoint
configuration is optional only when the exact fast path succeeds.

## Implementation Notes

The implementation adds a private helper in `agent.py`:

```python
def _try_exact_fast_path(
    request: ExploreRequest,
    *,
    repo_root: Path,
    settings: Settings,
) -> ExploreResult | None:
    ...
```

The helper should:

- use the existing `Citation`, `ExploreResult`, `PathSafety`, and `read_file`
  paths where possible;
- avoid adding public request/result fields;
- return `None` for all cases that should continue into the model loop;
- return an `ExploreResult` only for validated exact evidence;
- use `turns_used=0` for success;
- keep warnings empty unless an existing stable warning is clearly applicable.

`explore()` should call this helper before `settings.require_endpoint()`.

## Non-Goals

- No semantic search or local ranking.
- No embeddings, vector store, or context-pack output.
- No new CLI or MCP arguments.
- No pathless assignment/config short-circuit in v1.
- No explanation generation in the fast path.

## Coverage

Regression tests cover:

- bare paths return bounded previews with `turns_used=0` and accurate truncation;
- unique definitions surrounded by many references still resolve locally;
- explicit `path:start-end` query returns `turns_used=0` and does not call the
  endpoint;
- explicit path plus symbol returns matching lines in that file;
- explicit path plus assignment/config token may short-circuit;
- pathless unique `def`/`async def`/`class` short-circuits;
- pathless assignment/config token continues into the model loop;
- multiple definition matches continue into the model loop;
- semantic wording with an exact token continues into the model loop;
- denied or traversal paths do not leak content and do not short-circuit;
- endpoint config missing is allowed for fast-path success but still errors for
  queries that continue into the model loop;
- CLI text output is normalized for fast-path success;
- JSON output reports `turns_used=0`.

Opt-in endpoint-backed e2e timing tests may include exact path and exact unique
symbol cases. Expected local latency should be sub-second, but timing should not
be a default CI assertion.

## Exact-symbol validation refinement

Spec [011](../011-symbol-evidence-validation/spec.md) retains typed definition
scan outcomes for the model loop and requires the whole case-sensitive query
token inside accepted exact-symbol citation ranges, including all fallbacks.
Zero Python definitions still routes to the model; it does not establish absence
from assignments, imports, docs, or other languages. No additional scan is needed.

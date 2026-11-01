# Spec 010: Explorer progress and implementation evidence

Status: implemented

Refines specs 002, 004, and 009 for issues #9 and #10, retaining shared-core,
read-only exploration and existing resource limits.

## Tool progress

Cache observations per exploration by tool name and complete arguments. Execute
fresh fingerprints once, including same-batch duplicates; replay cached results
with each current call ID in original transcript order. Do not duplicate read
evidence or mutate cached IDs. A batch containing no fresh calls stops before
scheduling. Distinct subtree arguments remain distinct work.

## Evidence finalization

Conservatively detect implementation intent from implement/handle word families,
code, function, method, or class terms. Explicit documentation requests and exact
lookups retain existing behavior. Documentation filenames include Markdown, MDX,
RST, TXT, AsciiDoc, and extensionless README/CHANGELOG/CONTRIBUTING/LICENSE/AUTHORS.
The directory alone does not determine document type. This is a heuristic, not a
semantic relevance check; other file types may still be irrelevant.

For implementation intent, documentation-only citations are provisional. Retain
them, provide controller feedback, and continue within the existing turn budget.
Process accompanying tool calls normally. Prefer non-documentation evidence on
fallback. If only documentation remains at termination, return citations and
snippets with `truncated: true` and the warning `implementation source not
verified; returning documentation evidence`. Replace unverified implementation
prose with citations even in non-citation mode. Partial cited CLI results exit 0.
Token exhaustion and all-repeat stalls retain their termination behavior.

Safety exclusions, including dist/build/dependency directories, remain enforced.
The OpenClaw installed-bundle example cannot verify an implementation under dist;
use an allowed source checkout for implementation evidence.

## MCP metadata

Set the FastMCP underlying server version from the existing metadata-backed
package version. Verify the real initialize response in tests and installed smoke
checks. No schema, flags, dependencies, or configuration keys are added.

## Validation

Endpoint-free tests cover deduplication, mixed batches, distinct scoped calls,
ordered transcript IDs, all-repeat termination, documentation-to-source recovery,
turn-limit/stall fallback, denied source privacy, and documentation requests.
Run Ruff, mypy, pytest, wheel/source checks, and real stdio MCP initialization.

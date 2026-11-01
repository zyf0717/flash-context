# Spec 011: Exact-symbol evidence validation

Status: implemented

Fixes issue #13, extending specs 002, 005, and 010 in the shared exploration core.

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

## Validation

Mocked endpoint regressions cover fabricated plausible-home citations, cached
subranges, case and substring mismatches, read caps, direct and fallback results,
recovery, explicit no-result answers, repetition, turn exhaustion, and usable
versus unsupported token-limited completions. Positive cases include assignments,
imports, documentation, and other languages. CLI text/JSON tests preserve empty
results, warnings, and exit 0; MCP preserves shared-core diagnostics. Existing
fast-path and safety regressions remain required. Release checks validate 0.3.2
in source, wheel, source distribution, and real MCP initialization metadata.

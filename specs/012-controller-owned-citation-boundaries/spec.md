# Controller-owned citation boundaries — v0.4.0

Status: implemented

Supersedes model-selected range and read-fallback behavior in specs 002–004,
and the unconditional merging rule in 007. Public file-line labels remain.

Models propose `path#qualified.symbol` or `path:line`; ranges are rejected with
one correction opportunity within existing turns. A bundled Tree-sitter pack
resolves definitions, declarations and syntax regions. Qualified names use dots;
ambiguous overloads require a line anchor. Whole definitions include decorators
and export wrappers. Oversized definitions require line anchors, resolved to
complete statements/blocks or definition headers. Unknown or unparseable files
support line windows of ±5 lines; truncated trailing lines are excluded.

Defaults: 120 lines per model citation, 240 unique cited file-lines total,
12 final citations, 16 candidate anchors, 1 MiB parser input per file. Cumulative
parser input obeys max_scan_bytes and parsing/traversal obey tool deadlines.
Paths and contents pass existing safety checks. Parsing never downloads grammars
or sends full parser input to the model. Cache lifetime is one exploration.

All termination paths accept resolved anchors or exact-token-derived anchors;
raw read ranges cannot bypass validation. Distinct syntax units stay separate.
Explicit user ranges, previews and deterministic exact lookups retain their
existing endpoint-free behavior and byte limits. They are exempt from model
precision budgets. Raw snippets remain subject to max_read_bytes.

Citation precision adds inclusive range_lines, boundary_kind, optional qualified
symbol, optional whole exact-query-token presence, and optional count of complete
named definitions contained in the range. Null means unmeasured, not zero.
Metadata establishes structure and lexical coverage, not semantic relevance.
Non-citation prose retains its text with accepted anchors rewritten to canonical labels.

Guaranteed grammars: Python, JS/JSX, TS/TSX, C/C++, C#, Java, Go, Rust, Ruby,
PHP, Bash, Lua, Kotlin and Swift. Dependencies are pinned to the verified bundled
pack 0.13.0 and Tree-sitter 0.25.2, avoiding on-demand grammar downloads.

Validation: major-language symbol fixtures, HTTPX's six redirect functions
(140 lines vs 531; 15 contained definitions), repair feedback, budget boundaries,
safety exclusions and all core termination paths. The opt-in benchmark records
hit rate, recall, tightness, bytes, latency and turns; CI remains endpoint-free.

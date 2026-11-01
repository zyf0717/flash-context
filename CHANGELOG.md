# Changelog

User-visible changes and migration instructions for each release.

## [Unreleased]

## [0.5.0] - 2026-11-01

### Changed

- Position flash-context as repository search and context retrieval for AI agents,
  with exact lookups and model-guided search returning focused source evidence.
- Rename the CLI command to `search`, the MCP tool to `search_repository`, and
  the shared Python API and YAML section to use search terminology. Remove the
  previous names without compatibility aliases.

### Migration

- Replace `flash-context explore` with `flash-context search` and update MCP
  callers from `explore_repository` to `search_repository`.
- Python callers must import `search` from `flash_context.agent`,
  `search_repository_handler` from `flash_context.mcp_server`, and `SearchRequest`,
  `SearchResult`, and `SearchError` from `flash_context.types` in place of
  `explore`, `explore_repository_handler`, `ExploreRequest`, `ExploreResult`, and
  `ExplorerError` respectively.
- Rename the `explorer` section in source-checkout `config.yaml` files to `search`.
  Environment variable names, request fields, and result schemas are unchanged.

## [0.4.2] - 2026-11-01

### Changed

- Increase the default exploration limit from 6 to 12 turns for CLI, MCP, and
  Python requests. Explicit turn limits still take precedence (#21).

### Fixed

- Move to evidence selection when shifted read ranges repeatedly add no source
  lines. Consolidate overlapping read excerpts in selection and record its trigger
  in metadata-only trajectories (#21).
- Use a remaining selection turn after a token-limited completion when prior
  read observations are available, instead of discarding them (#21).

### Migration

- To retain the previous six-turn limit, set `FLASH_CONTEXT_MAX_TURNS=6` or pass
  `--max-turns 6` in the CLI or `max_turns: 6` in the MCP request.

## [0.4.1] - 2026-11-01

### Fixed

- Clarify exploration and evidence-selection prompts to cite code that performs
  the requested behavior; comments and strings remain supporting evidence (#18).
- Consolidate symbol preflight into the leading system message for strict chat
  templates; preserve missing-symbol diagnostics and genuine endpoint errors.
- Normalize model ranges to complete syntax units with atomic budget checks and
  one-to-many prose mappings. Repair feedback includes anchor examples.
- Reserve a final evidence-selection turn and start unscoped semantic discovery
  with search tools. Record request phases, roles, tool counts, and HTTP status
  without logging repository or endpoint content.

### Changed

- Increase the default model citation budget to 600 unique lines and 16 citations.
  The 120-line per-citation limit and explicit configured limits still apply.
  Selection counts toward the existing turn budget; single-turn requests retain
  their previous behavior. CLI/MCP result schemas are unchanged.

## [0.4.0] - 2026-11-01

### Added

- Bundled parsers for controller-owned symbol and line-anchor boundaries, with
  citation precision metadata and an opt-in pinned quality benchmark.
- Configurable per-citation, total-line and parser-byte limits (120, 240 and
  1 MiB by default), supporting the existing configuration precedence.

### Fixed

- Keep citation repair feedback local to each model turn; successful repair after
  a tool-only turn no longer reports a precision failure. Preserve overlapping
  anchor mappings, LF/CRLF source lines, and snippet/metadata source snapshots.
- Report parser input/deadline limits explicitly and use diagnostic identities
  for truncation and CLI exit behavior.

### Changed

- Consolidate contracts under `docs/`, remove planning scaffolds and separate
  agent instructions, and keep contributor guidance in `CONTRIBUTING.md`.
  Simplify query routing, configuration, loop finalization, test fixtures,
  live evaluation, and CI jobs.
- Benchmark against independent reviewed ranges, recording package/parser
  versions and effective settings. Live probes share the same pinned cases.

### Migration

- Models must propose symbol or single-line anchors; model-selected ranges receive
  bounded correction feedback. Public line labels remain unchanged. Adjacent
  definitions remain separate, and the final citation cap increases to twelve.
- Unselected read observations no longer become final citations. Consumers should
  accept the additive precision object. Explicit user ranges retain old behavior.
- Parser dependencies ship with installation; exploration does not download grammars.
- CLI `--no-citation` now enables prose; `--citation` remains the default.
  Remove the previously ignored `explorer.citation` YAML key. Python callers
  should stop passing the ignored `load_settings(repo_root=...)` argument or
  the adapter-only `ExploreRequest.format` field. `Citation` now requires both
  line bounds; typed warnings use `Diagnostic` members and serialize as strings.
- Empty results after parser input/deadline exhaustion exit 6, matching scan
  exhaustion. Ordinary syntax fallback and complete empty results still exit 0.

## [0.3.2] - 2026-11-01

### Fixed

- Require whole, case-sensitive query tokens inside exact-symbol citations,
  including read-derived fallback evidence. Reject plausible-home file citations
  without matching source text and retain scoped Python preflight diagnostics.
- Report `query symbol not found in verified evidence` when symbol lookups finish
  without accepted evidence, rather than relying on generic termination warnings.

### Migration

- Exact-symbol queries may now return `NO_CITATIONS_FOUND` with empty citations
  and snippets where previous versions returned unrelated files. Token presence
  is lexical evidence, not proof of a definition or semantic relevance. Public
  schemas, configuration, and CLI exit semantics are unchanged.

### Changed

- Condense the README overview and move safety and evidence-validation details
  to the architecture documentation.

## [0.3.1] - 2026-11-01

### Fixed

- Report the flash-context package version during MCP initialization instead of
  the MCP SDK version.
- Reuse repeated tool observations without discarding fresh searches in the same
  batch; execute same-turn duplicates only once and stop all-repeat stalls.
- Continue implementation searches after documentation-only citations within the
  existing turn budget. Documentation-only fallbacks retain citations and snippets
  with explicit incomplete-result metadata and warnings.

### Changed

- Describe deterministic lookup and delegated model search together in the README.

### Migration

- Implementation questions may use additional turns before returning documentation
  evidence. These fallbacks set `truncated: true`; partial cited CLI results still
  exit 0. Budgets, configuration keys, and result schemas are unchanged.

## [0.3.0] - 2026-11-01

### Fixed

- Resolve bare file-path queries locally with bounded previews and find unique
  Python definitions even when many references precede them.
- Keep literal and scoped searches from scanning unrelated directory trees while
  preserving safety checks and existing resource limits.
- Surface scan failures from the initial file sample and CLI result warnings.
- Describe the MCP exploration tool during discovery and use tool-specific
  trajectory counters instead of misleading empty read-content counts.

### Migration

- Citation objects no longer include the unused `reason` field. Consumers should
  read `path`, `start_line`, and `end_line` without expecting `reason: null`.
- The CLI now exits 6 for empty results after scan-budget exhaustion or a tool
  processing timeout, retaining text/JSON on stdout and warnings on stderr.
  Partial cited results and complete empty searches still exit 0.
- Trajectory tool entries now include only their relevant counter:
  `content_length` (read), `hit_count` (grep), or `match_count` (glob).

### Changed

- Prompt the explorer to prefer implementation source for coding questions and
  the smallest supporting citation ranges. Validation checks safe line coverage;
  precision and relevance remain model-dependent.
- Publish GitHub releases automatically after PyPI installation verification,
  using this changelog and the same distribution artifacts uploaded to PyPI.
- Refresh package-index metadata during release installation retries.

## [0.2.0] - 2026-11-01

### Changed

- Enforce deny/ignore rules on requested and resolved paths, including environment
  files, private-key names, and runtime histories. Prune denied directories.
- Bound scan bytes, directory entries, processing time, regex execution, tool
  batches, and model observations; report incomplete coverage explicitly.
- Improve exact-lookup routing, read ranges, truncation metadata, and structured
  endpoint/filesystem failures across CLI and MCP.
- Keep optional trajectory logs metadata-only and outside the inspected root.

### Migration

- Move any trajectory directory inside the inspected repository outside it, or
  disable logging with `FLASH_CONTEXT_TRAJ_DIR=`. Empty/null settings disable
  inherited logging. Existing logs remain untouched.

## [0.1.0] - 2026-11-01

### Added

- Initial Python CLI and optional MCP adapter sharing a read-only explorer core.
- OpenAI-compatible tool-call loop with bounded Read/Glob/Grep repository tools,
  root-scoped path validation, validated citations, and raw source snippets.
- Exact path/symbol lookup shortcuts, concurrent local tools, and configurable
  endpoint settings and limits.
- Wheel/source packaging and tag-driven TestPyPI/PyPI publication and smoke checks.

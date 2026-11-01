# Changelog

User-visible changes and migration instructions for each release.

## [Unreleased]

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

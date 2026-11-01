# Changelog

User-visible changes and migration instructions for each release.

## [Unreleased]

### Changed

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

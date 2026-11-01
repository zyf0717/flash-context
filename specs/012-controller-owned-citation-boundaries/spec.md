# 012: Controller-owned citation boundaries — v0.4.0

Status: implemented. Current behavior: [shared contract](../../docs/contracts.md).

Models select anchors; code resolves bounded syntax and emits precision metadata.
This supersedes model-selected ranges/read fallback in 002–004 and unconditional
merging in 007. Local explicit lookups retain endpoint-free behavior.

The v0.4.0 simplification also replaces mutable resolver feedback with per-turn
results, preserves anchor provenance and source snapshots, standardizes source
lines, uses diagnostic identities for control flow, classifies queries once, and
consolidates numeric configuration parsing. Completed planning documents are
indexed in [spec history](../README.md), rather than competing with current rules.

Validation includes bundled major-language grammars, the pinned HTTPX redirect
regression (six definitions, 140 lines versus 531; 15 definitions in the old
range), repair/termination paths, overlapping anchors, Unicode/CRLF boundaries,
parser outcomes, safety, configuration, CLI/MCP behavior, and independent golden
ranges. Model quality remains an opt-in trend using the shared benchmark runner;
standard tests require no external endpoint.

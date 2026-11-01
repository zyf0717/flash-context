from __future__ import annotations

from pathlib import Path

from flash_context.tools.safety import PathSafety
from flash_context.types import ExplorerError, ToolObservation


def repo_glob(
    *,
    repo_root: Path,
    pattern: str,
    max_results: int,
    ignore: list[str] | None = None,
) -> ToolObservation:
    if not pattern:
        raise ExplorerError("INVALID_TOOL_ARGUMENTS", "pattern is required")
    if max_results <= 0:
        raise ExplorerError("CONFIG_INVALID", "max_results must be positive")
    safety = PathSafety(repo_root, tuple(ignore or ()))
    matches: list[str] = []
    truncated = False
    for path in safety.iter_safe_files(pattern):
        if len(matches) >= max_results:
            truncated = True
            break
        matches.append(safety.relative_or_raw(path))
    return ToolObservation(matches=matches, truncated=truncated)


from __future__ import annotations

from pathlib import Path

from flash_context.tools.safety import PathSafety, ScanBudget, ScanLimits
from flash_context.types import Diagnostic, SearchError, ToolObservation


def repo_glob(
    *,
    repo_root: Path,
    pattern: str,
    max_results: int,
    ignore: list[str] | None = None,
    limits: ScanLimits | None = None,
) -> ToolObservation:
    if not pattern:
        raise SearchError("INVALID_TOOL_ARGUMENTS", "pattern is required")
    if max_results <= 0:
        raise SearchError("CONFIG_INVALID", "max_results must be positive")
    safety = PathSafety(repo_root, tuple(ignore or ()))
    matches: list[str] = []
    truncated = False
    budget = ScanBudget(limits or ScanLimits())
    try:
        for path in safety.iter_safe_files(pattern, budget=budget):
            if len(matches) >= max_results:
                truncated = True
                break
            matches.append(safety.relative_or_raw(path))
    except SearchError as exc:
        if exc.code != "TOOL_LIMIT_EXCEEDED":
            raise
        budget.warnings.append(Diagnostic.GLOB_LIMIT)
    return ToolObservation(
        matches=matches,
        truncated=truncated or bool(budget.warnings),
        warnings=budget.warnings,
    )

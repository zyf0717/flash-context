from __future__ import annotations

from pathlib import Path

import regex

from flash_context.tools.safety import PathSafety, ScanBudget, ScanLimits
from flash_context.types import Diagnostic, SearchError, SearchHit, ToolObservation

MAX_HIT_TEXT = 240


def repo_grep(
    *,
    repo_root: Path,
    pattern: str,
    max_results: int,
    glob: str = "**/*",
    configured_max_results: int | None = None,
    ignore: list[str] | None = None,
    limits: ScanLimits | None = None,
) -> ToolObservation:
    if not pattern:
        raise SearchError("INVALID_TOOL_ARGUMENTS", "pattern is required")
    if max_results <= 0:
        raise SearchError("CONFIG_INVALID", "max_results must be positive")
    if len(pattern) > 4096:
        raise SearchError(
            "INVALID_GREP_PATTERN", "Grep pattern exceeds 4096 characters"
        )
    limit = min(max_results, configured_max_results or max_results)
    try:
        compiled = regex.compile(pattern, regex.VERSION0)
    except regex.error as exc:
        raise SearchError(
            "INVALID_GREP_PATTERN",
            "Grep pattern is not a valid regular expression",
        ) from exc

    safety = PathSafety(repo_root, tuple(ignore or ()))
    hits: list[SearchHit] = []
    budget = ScanBudget(limits or ScanLimits())
    try:
        for path in safety.iter_safe_files(glob or "**/*", budget=budget):
            try:
                with path.open("rb") as handle:
                    line_number = 0
                    while True:
                        budget.consume()
                        raw = handle.readline(65537)
                        if not raw:
                            break
                        budget.consume(size=len(raw))
                        line_number += 1
                        if len(raw) > 65536:
                            while raw and not raw.endswith(b"\n"):
                                raw = handle.readline(65536)
                                budget.consume(size=len(raw))
                            if Diagnostic.OVERSIZED_LINE not in budget.warnings:
                                budget.warnings.append(Diagnostic.OVERSIZED_LINE)
                            continue
                        line = raw.decode("utf-8", errors="replace")
                        if "\x00" in line or not compiled.search(
                            line, timeout=max(0.000001, budget.remaining_seconds())
                        ):
                            continue
                        if len(hits) >= limit:
                            return ToolObservation(
                                hits=hits, truncated=True, warnings=budget.warnings
                            )
                        hits.append(
                            SearchHit(
                                safety.relative_or_raw(path),
                                line_number,
                                _cap_text(line.rstrip("\n")),
                            )
                        )
            except TimeoutError:
                raise
            except OSError:
                if Diagnostic.UNREADABLE_FILE not in budget.warnings:
                    budget.warnings.append(Diagnostic.UNREADABLE_FILE)
    except TimeoutError:
        budget.warnings.append(Diagnostic.GREP_TIMEOUT)
    except SearchError as exc:
        if exc.code != "TOOL_LIMIT_EXCEEDED":
            raise
        budget.warnings.append(Diagnostic.GREP_LIMIT)
    return ToolObservation(
        hits=hits, truncated=bool(budget.warnings), warnings=budget.warnings
    )


def _cap_text(text: str) -> str:
    if len(text) <= MAX_HIT_TEXT:
        return text
    return f"{text[: MAX_HIT_TEXT - 3]}..."

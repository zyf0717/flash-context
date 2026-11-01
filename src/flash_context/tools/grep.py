from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

from flash_context.tools.safety import PathSafety
from flash_context.types import ExplorerError, SearchHit, ToolObservation

MAX_HIT_TEXT = 240


def repo_grep(
    *,
    repo_root: Path,
    pattern: str,
    max_results: int,
    glob: str = "**/*",
    configured_max_results: int | None = None,
    ignore: list[str] | None = None,
) -> ToolObservation:
    if not pattern:
        raise ExplorerError("INVALID_TOOL_ARGUMENTS", "pattern is required")
    if max_results <= 0:
        raise ExplorerError("CONFIG_INVALID", "max_results must be positive")
    limit = min(max_results, configured_max_results or max_results)
    try:
        regex = re.compile(pattern)
    except re.error as exc:
        raise ExplorerError(
            "INVALID_GREP_PATTERN",
            "Grep pattern is not a valid regular expression",
            details={"error": str(exc)},
        ) from exc

    safety = PathSafety(repo_root, tuple(ignore or ()))
    hits: list[SearchHit] = []
    truncated = False
    for path in safety.iter_safe_files(glob or "**/*"):
        for line_number, line in _iter_text_lines(path):
            if not regex.search(line):
                continue
            if len(hits) >= limit:
                truncated = True
                return ToolObservation(hits=hits, truncated=truncated)
            hits.append(
                SearchHit(
                    path=safety.relative_or_raw(path),
                    line=line_number,
                    text=_cap_text(line.rstrip("\n")),
                )
            )
    return ToolObservation(hits=hits, truncated=truncated)


def _iter_text_lines(path: Path) -> Iterator[tuple[int, str]]:
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_number, line in enumerate(handle, start=1):
            if "\x00" in line:
                continue
            yield line_number, line


def _cap_text(text: str) -> str:
    if len(text) <= MAX_HIT_TEXT:
        return text
    return f"{text[: MAX_HIT_TEXT - 1]}..."

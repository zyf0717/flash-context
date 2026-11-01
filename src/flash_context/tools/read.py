from __future__ import annotations

from pathlib import Path

from flash_context.tools.safety import PathSafety
from flash_context.types import ExplorerError, ToolObservation


def read_file(
    *,
    repo_root: Path,
    path: str,
    max_bytes: int,
    start_line: int | None = None,
    end_line: int | None = None,
    ignore: list[str] | None = None,
) -> ToolObservation:
    if not path:
        raise ExplorerError("INVALID_TOOL_ARGUMENTS", "path is required")
    if start_line is not None and start_line <= 0:
        raise ExplorerError("INVALID_TOOL_ARGUMENTS", "start_line must be positive")
    if end_line is not None and end_line <= 0:
        raise ExplorerError("INVALID_TOOL_ARGUMENTS", "end_line must be positive")
    if start_line is not None and end_line is not None and end_line < start_line:
        raise ExplorerError(
            "INVALID_TOOL_ARGUMENTS",
            "end_line must be greater than or equal to start_line",
        )
    if max_bytes <= 0:
        raise ExplorerError("CONFIG_INVALID", "max_bytes must be positive")

    safety = PathSafety(repo_root, tuple(ignore or ()))
    resolved = safety.resolve_existing_file(path)
    rel_path = safety.relative_or_raw(resolved)
    first_line = start_line or 1
    last_line = end_line
    content_bytes = bytearray()
    actual_last: int | None = None
    total_lines = 0
    truncated = False

    with resolved.open("rb") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            total_lines = line_number
            if line_number < first_line:
                continue
            if last_line is not None and line_number > last_line:
                break
            if len(content_bytes) + len(raw_line) > max_bytes:
                remaining = max_bytes - len(content_bytes)
                if remaining > 0:
                    content_bytes.extend(raw_line[:remaining])
                actual_last = line_number
                truncated = True
                break
            content_bytes.extend(raw_line)
            actual_last = line_number

    if actual_last is None:
        raise ExplorerError(
            "INVALID_TOOL_ARGUMENTS",
            "Requested start_line is beyond the end of file",
            details={
                "path": rel_path,
                "start_line": first_line,
                "total_lines": total_lines,
            },
        )

    content = content_bytes.decode("utf-8", errors="replace")
    line_range = f"{first_line}-{actual_last}"
    return ToolObservation(
        path=rel_path,
        line_range=line_range,
        content=content,
        truncated=truncated,
    )

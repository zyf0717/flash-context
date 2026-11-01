from __future__ import annotations

from pathlib import Path

from flash_context.tools.safety import PathSafety, ScanBudget, ScanLimits
from flash_context.types import ExplorerError, ToolObservation


def read_file(
    *,
    repo_root: Path,
    path: str,
    max_bytes: int,
    start_line: int | None = None,
    end_line: int | None = None,
    ignore: list[str] | None = None,
    limits: ScanLimits | None = None,
    preview: bool = False,
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

    budget = ScanBudget(limits or ScanLimits())
    try:
        with resolved.open("rb") as handle:
            line_number = 1
            while last_line is None or line_number <= last_line:
                budget.consume()
                remaining = max_bytes - len(content_bytes)
                chunk = handle.readline(
                    min(65536, remaining + 1) if line_number >= first_line else 65536
                )
                if not chunk:
                    break
                budget.consume(size=len(chunk))
                total_lines = line_number
                if line_number >= first_line:
                    accepted = chunk[:remaining]
                    if accepted:
                        content_bytes.extend(accepted)
                        actual_last = line_number
                    if len(chunk) > remaining:
                        truncated = True
                        break
                if chunk.endswith(b"\n"):
                    line_number += 1
            if preview and not truncated:
                extra = handle.read(1)
                budget.consume(size=len(extra))
                truncated = bool(extra)
    except OSError as exc:
        raise ExplorerError(
            "PATH_UNREADABLE", "Repository file could not be read"
        ) from exc
    except ExplorerError:
        if actual_last is None:
            raise
        truncated = True
        budget.warnings.append("read scan budget exhausted")

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
    encoded = content.encode("utf-8")
    if len(encoded) > max_bytes:
        content = encoded[:max_bytes].decode("utf-8", errors="ignore")
        truncated = True
    line_range = f"{first_line}-{actual_last}"
    return ToolObservation(
        path=rel_path,
        line_range=line_range,
        content=content,
        truncated=truncated,
        warnings=budget.warnings,
    )

from __future__ import annotations

import fnmatch
import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from time import monotonic

from flash_context.types import Diagnostic, ExplorerError

DEFAULT_DENY_PATTERNS = (
    ".git/**",
    ".env*",
    "*.pem",
    "*.key",
    "id_rsa",
    "id_ed25519",
    "**/secrets/**",
    "**/.aws/**",
    "**/.ssh/**",
    ".venv/**",
    "venv/**",
    "node_modules/**",
    "dist/**",
    "build/**",
)

DENY_DIR_NAMES = {
    ".git",
    ".flash-context",
    ".aws",
    ".ssh",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "secrets",
}

DENY_FILE_NAMES = {"id_rsa", "id_ed25519", "id_dsa", "id_ecdsa", ".env"}
DENY_FILE_SUFFIXES = (".pem", ".key")


@dataclass(frozen=True, slots=True)
class PathSafety:
    repo_root: Path
    ignore: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        root = self.repo_root.resolve()
        object.__setattr__(self, "repo_root", root)
        if not root.exists() or not root.is_dir():
            raise ExplorerError(
                "REPO_NOT_FOUND",
                "Repository root must exist and be a directory",
                details={"repo_root": str(root)},
            )

    def resolve_existing_file(self, requested: str | Path) -> Path:
        try:
            return self._resolve_existing_file(requested)
        except OSError as exc:
            raise ExplorerError(
                "PATH_UNREADABLE", "Repository path could not be accessed"
            ) from exc

    def _resolve_existing_file(self, requested: str | Path) -> Path:
        raw = Path(requested)
        if ".." in raw.parts:
            raise ExplorerError(
                "PATH_OUTSIDE_ROOT",
                "Requested path is outside the repository root",
                details={"path": str(requested)},
            )
        candidate = raw if raw.is_absolute() else self.repo_root / raw
        if candidate.is_relative_to(self.repo_root):
            self.ensure_allowed(candidate)
        resolved = candidate.resolve(strict=False)
        if not _is_relative_to(resolved, self.repo_root):
            raise ExplorerError(
                "PATH_OUTSIDE_ROOT",
                "Requested path is outside the repository root",
                details={"path": str(requested)},
            )
        if not resolved.exists():
            raise ExplorerError(
                "PATH_NOT_FOUND",
                "Requested path does not exist",
                details={"path": self.relative_or_raw(resolved)},
            )
        if not resolved.is_file():
            raise ExplorerError(
                "PATH_DENIED",
                "Requested path is not a regular file",
                details={"path": self.relative_or_raw(resolved)},
            )
        self.ensure_allowed(resolved)
        return resolved

    def ensure_allowed(self, path: Path) -> None:
        rel = path.relative_to(self.repo_root).as_posix()
        parts = rel.split("/")
        if any(part in DENY_DIR_NAMES for part in parts):
            raise ExplorerError(
                "PATH_DENIED",
                "Requested path is denied by repository safety policy",
                details={"path": rel},
            )
        name = parts[-1] if parts else rel
        if (
            name in DENY_FILE_NAMES
            or name.startswith(".env")
            or name.endswith(DENY_FILE_SUFFIXES)
            or _matches_patterns(rel, DEFAULT_DENY_PATTERNS)
            or _matches_patterns(rel, self.ignore)
        ):
            raise ExplorerError(
                "PATH_DENIED",
                "Requested path is denied by repository safety policy",
                details={"path": rel},
            )

    def relative_or_raw(self, path: Path) -> str:
        try:
            return path.resolve(strict=False).relative_to(self.repo_root).as_posix()
        except ValueError:
            return path.as_posix()

    def validate_glob_pattern(self, pattern: str) -> None:
        raw = Path(pattern)
        if raw.is_absolute() or ".." in raw.parts:
            raise ExplorerError(
                "PATH_OUTSIDE_ROOT",
                "Glob pattern must stay inside the repository root",
                details={"pattern": pattern},
            )

    def iter_safe_files(
        self,
        pattern: str = "**/*",
        *,
        budget: ScanBudget | None = None,
    ) -> Iterator[Path]:
        self.validate_glob_pattern(pattern)
        budget = budget or ScanBudget(ScanLimits())
        seen: set[Path] = set()

        def walk(directory: Path) -> Iterator[Path]:
            try:
                with os.scandir(directory) as entries:
                    paths = []
                    for entry in entries:
                        budget.consume(entries=1)
                        paths.append(Path(entry.path))
                for candidate in sorted(paths):
                    budget.consume()
                    try:
                        self.ensure_allowed(candidate)
                        if candidate.is_dir() and not candidate.is_symlink():
                            yield from walk(candidate)
                        elif candidate.relative_to(self.repo_root).full_match(pattern):
                            resolved = self.resolve_existing_file(candidate)
                            if resolved not in seen:
                                seen.add(resolved)
                                yield resolved
                    except ExplorerError as exc:
                        if exc.code == "TOOL_LIMIT_EXCEEDED":
                            raise
                        if exc.code not in {"PATH_DENIED", "PATH_OUTSIDE_ROOT"}:
                            budget.warnings.append(Diagnostic.UNREADABLE_ENTRY)
            except OSError:
                budget.warnings.append(Diagnostic.UNREADABLE_DIRECTORY)

        directory = self.repo_root
        parts = Path(pattern).parts
        try:
            for index, part in enumerate(parts):
                if any(char in part for char in "*?["):
                    break
                candidate = directory / part
                budget.consume(entries=1)
                self.ensure_allowed(candidate)
                if index == len(parts) - 1:
                    if candidate.exists() and not candidate.is_dir():
                        yield self.resolve_existing_file(candidate)
                    return
                # Match the walker's policy: never traverse directory symlinks.
                if candidate.is_symlink() or not candidate.is_dir():
                    return
                directory = candidate
            yield from walk(directory)
        except ExplorerError as exc:
            if exc.code == "TOOL_LIMIT_EXCEEDED":
                raise
            if exc.code not in {"PATH_DENIED", "PATH_OUTSIDE_ROOT"}:
                budget.warnings.append(Diagnostic.UNREADABLE_ENTRY)
        except OSError:
            budget.warnings.append(Diagnostic.UNREADABLE_DIRECTORY)


def _matches_patterns(rel_path: str, patterns: tuple[str, ...]) -> bool:
    return any(
        _matches_pattern(rel_path, pattern.strip())
        for pattern in patterns
        if pattern.strip()
    )


def _matches_pattern(rel_path: str, pattern: str) -> bool:
    normalized = pattern.removeprefix("./")
    if normalized.endswith("/**"):
        prefix = normalized[:-3].rstrip("/")
        return rel_path == prefix or rel_path.startswith(f"{prefix}/")
    if "/" not in normalized:
        parts = rel_path.split("/")
        return any(fnmatch.fnmatchcase(part, normalized) for part in parts)
    return fnmatch.fnmatchcase(rel_path, normalized)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


@dataclass(frozen=True, slots=True)
class ScanLimits:
    max_scan_bytes: int = 16 * 1024 * 1024
    max_scan_entries: int = 10_000
    tool_timeout_seconds: float = 5.0


@dataclass(slots=True)
class ScanBudget:
    limits: ScanLimits
    started: float = field(default_factory=monotonic)
    bytes_read: int = 0
    entries: int = 0
    warnings: list[Diagnostic] = field(default_factory=list)

    def remaining_seconds(self) -> float:
        return self.limits.tool_timeout_seconds - (monotonic() - self.started)

    def consume(self, *, size: int = 0, entries: int = 0) -> None:
        self.bytes_read += size
        self.entries += entries
        if (
            self.bytes_read > self.limits.max_scan_bytes
            or self.entries > self.limits.max_scan_entries
            or self.remaining_seconds() <= 0
        ):
            raise ExplorerError("TOOL_LIMIT_EXCEEDED", "Tool scan budget exhausted")

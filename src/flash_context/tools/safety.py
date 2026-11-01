from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from pathlib import Path

from flash_context.types import ExplorerError

DEFAULT_DENY_PATTERNS = (
    ".git/**",
    ".env",
    ".env.*",
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
    ".aws",
    ".ssh",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "secrets",
}

DENY_FILE_NAMES = {"id_rsa", "id_ed25519", ".env"}
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
        raw = Path(requested)
        if ".." in raw.parts:
            raise ExplorerError(
                "PATH_OUTSIDE_ROOT",
                "Requested path is outside the repository root",
                details={"path": str(requested)},
            )
        candidate = raw if raw.is_absolute() else self.repo_root / raw
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
        rel = self.relative_or_raw(path)
        parts = rel.split("/")
        if any(part in DENY_DIR_NAMES for part in parts[:-1]):
            raise ExplorerError(
                "PATH_DENIED",
                "Requested path is denied by repository safety policy",
                details={"path": rel},
            )
        name = parts[-1] if parts else rel
        if (
            name in DENY_FILE_NAMES
            or name.startswith(".env.")
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

    def iter_safe_files(self, pattern: str = "**/*") -> list[Path]:
        self.validate_glob_pattern(pattern)
        files: list[Path] = []
        for candidate in sorted(self.repo_root.glob(pattern)):
            try:
                resolved = candidate.resolve(strict=False)
                if not _is_relative_to(resolved, self.repo_root):
                    continue
                if not resolved.is_file():
                    continue
                self.ensure_allowed(resolved)
            except ExplorerError:
                continue
            files.append(resolved)
        return files


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

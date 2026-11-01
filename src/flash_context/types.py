from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

ErrorCode = Literal[
    "CONFIG_MISSING_ENDPOINT",
    "CONFIG_INVALID",
    "REPO_NOT_FOUND",
    "QUERY_EMPTY",
    "PATH_OUTSIDE_ROOT",
    "PATH_DENIED",
    "PATH_NOT_FOUND",
    "TOOL_OUTPUT_TRUNCATED",
    "ENDPOINT_UNREACHABLE",
    "ENDPOINT_TIMEOUT",
    "ENDPOINT_BAD_RESPONSE",
    "UNSUPPORTED_TOOL_CALL",
    "MAX_TURNS_EXCEEDED",
    "INVALID_TOOL_ARGUMENTS",
    "INVALID_GREP_PATTERN",
]


@dataclass(slots=True)
class ExplorerError(Exception):
    code: ErrorCode
    message: str
    retryable: bool = False
    details: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        super().__init__(f"{self.code}: {self.message}")

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "details": self.details,
        }


@dataclass(frozen=True, slots=True)
class Citation:
    path: str
    start_line: int | None = None
    end_line: int | None = None
    reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "reason": self.reason,
        }

    def label(self) -> str:
        if self.start_line is None:
            return self.path
        if self.end_line is None or self.end_line == self.start_line:
            return f"{self.path}:{self.start_line}"
        return f"{self.path}:{self.start_line}-{self.end_line}"


@dataclass(frozen=True, slots=True)
class RawLocation:
    path: str
    start_line: int
    end_line: int
    text: str
    truncated: bool = False

    def to_dict(self, *, include_text: bool = True) -> dict[str, object]:
        data: dict[str, object] = {
            "path": self.path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "truncated": self.truncated,
        }
        if include_text:
            data["text"] = self.text
        else:
            data["text_length"] = len(self.text)
        return data


@dataclass(frozen=True, slots=True)
class SearchHit:
    path: str
    line: int
    text: str

    def to_dict(self) -> dict[str, object]:
        return {"path": self.path, "line": self.line, "text": self.text}


@dataclass(slots=True)
class ToolCall:
    id: str
    name: Literal["read_file", "repo_glob", "repo_grep"]
    arguments: dict[str, object]


@dataclass(slots=True)
class ToolObservation:
    tool_call_id: str | None = None
    ok: bool = True
    path: str | None = None
    line_range: str | None = None
    content: str | None = None
    matches: list[str] = field(default_factory=list)
    hits: list[SearchHit] = field(default_factory=list)
    truncated: bool = False
    error: ExplorerError | None = None

    def to_dict(self, *, include_content: bool = True) -> dict[str, object]:
        data: dict[str, object] = {
            "ok": self.ok,
            "truncated": self.truncated,
        }
        if self.tool_call_id is not None:
            data["tool_call_id"] = self.tool_call_id
        if self.path is not None:
            data["path"] = self.path
        if self.line_range is not None:
            data["line_range"] = self.line_range
        if include_content and self.content is not None:
            data["content"] = self.content
        elif self.content is not None:
            data["content_length"] = len(self.content)
        if self.matches:
            data["matches"] = self.matches
        if self.hits:
            data["hits"] = [hit.to_dict() for hit in self.hits]
        if self.error is not None:
            data["error"] = self.error.to_dict()
        return data

    @classmethod
    def from_error(
        cls, error: ExplorerError, *, tool_call_id: str | None = None
    ) -> ToolObservation:
        return cls(tool_call_id=tool_call_id, ok=False, error=error)


@dataclass(frozen=True, slots=True)
class ExploreRequest:
    query: str
    repo_root: Path
    max_turns: int = 6
    citation: bool = True
    format: Literal["text", "json"] = "text"

    def validate(self) -> None:
        if not self.query.strip():
            raise ExplorerError("QUERY_EMPTY", "Query must not be blank")
        if self.max_turns <= 0:
            raise ExplorerError(
                "CONFIG_INVALID",
                "max_turns must be positive",
                details={"max_turns": self.max_turns},
            )
        if not self.repo_root.exists() or not self.repo_root.is_dir():
            raise ExplorerError(
                "REPO_NOT_FOUND",
                "Repository root must exist and be a directory",
                details={"repo_root": str(self.repo_root)},
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "query": self.query,
            "repo_root": str(self.repo_root),
            "max_turns": self.max_turns,
            "citation": self.citation,
            "format": self.format,
        }


@dataclass(slots=True)
class ExploreResult:
    query: str
    repo_root: str
    answer: str
    citations: list[Citation]
    turns_used: int
    raw_locations: list[RawLocation] = field(default_factory=list)
    truncated: bool = False
    warnings: list[str] = field(default_factory=list)

    def to_dict(self, *, include_raw_location_text: bool = True) -> dict[str, object]:
        return {
            "query": self.query,
            "repo_root": self.repo_root,
            "answer": self.answer,
            "citations": [citation.to_dict() for citation in self.citations],
            "raw_locations": [
                raw_location.to_dict(include_text=include_raw_location_text)
                for raw_location in self.raw_locations
            ],
            "turns_used": self.turns_used,
            "truncated": self.truncated,
            "warnings": self.warnings,
        }


JsonObject = dict[str, Any]

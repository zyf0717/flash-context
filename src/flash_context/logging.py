from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from flash_context.types import (
    Diagnostic,
    SearchError,
    SearchRequest,
    SearchResult,
    ToolObservation,
)


def validate_trajectory_dir(traj_dir: Path | None, repo_root: Path) -> None:
    if traj_dir is not None and traj_dir.resolve().is_relative_to(repo_root.resolve()):
        raise SearchError(
            "CONFIG_INVALID", "Trajectory directory must be outside the repository"
        )


class TrajectoryRecorder:
    """Persist structural metadata only; repository/model text is never logged."""

    def __init__(self, traj_dir: Path | None, request: SearchRequest) -> None:
        validate_trajectory_dir(traj_dir, request.repo_root)
        self._traj_dir = traj_dir
        self._turns: list[dict[str, object]] = []
        self._data: dict[str, object] = {
            "request": {
                "repo_root": str(request.repo_root),
                "query_length": len(request.query),
                "max_turns": request.max_turns,
            },
            "turns": self._turns,
        }

    def record_request(
        self,
        turn: int,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        selecting: bool,
        selection_reason: str | None = None,
    ) -> None:
        if self._traj_dir is not None:
            entry: dict[str, object] = {
                "turn": turn,
                "phase": "selection" if selecting else "discovery",
                "message_roles": [m["role"] for m in messages],
                "tool_count": len(tools),
            }
            if selecting and selection_reason:
                entry["selection_reason"] = selection_reason
            self._turns.append(entry)

    def record_model_turn(self, turn: int, message: dict[str, object]) -> None:
        if self._traj_dir is not None:
            calls = message.get("tool_calls")
            self._turns.append(
                {
                    "turn": turn,
                    "tool_call_count": len(calls) if isinstance(calls, list) else 0,
                }
            )

    def record_observation(
        self, turn: int, tool_name: str, observation: ToolObservation
    ) -> None:
        if self._traj_dir is not None:
            metadata: dict[str, object] = {
                "turn": turn,
                "tool": tool_name,
                "ok": observation.ok,
                "truncated": observation.truncated,
            }
            if tool_name == "read_file":
                metadata["content_length"] = len(observation.content or "")
            elif tool_name == "repo_grep":
                metadata["hit_count"] = len(observation.hits)
            elif tool_name == "repo_glob":
                metadata["match_count"] = len(observation.matches)
            self._turns.append(metadata)

    def finish(
        self, *, result: SearchResult | None = None, error: SearchError | None = None
    ) -> None:
        if self._traj_dir is None:
            return
        self._data["error"] = error.code if error else None
        if error and isinstance(error.details.get("status_code"), int):
            self._data["status_code"] = error.details["status_code"]
        self._data["result"] = (
            {
                "turns_used": result.turns_used,
                "citation_count": len(result.citations),
                "text_length": sum(len(x.text) for x in result.raw_locations),
                "truncated": result.truncated,
            }
            if result
            else None
        )
        try:
            self._traj_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S")
            path = self._traj_dir / f"{stamp}-{uuid4().hex}.json"
            path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        except OSError:
            if result is not None:
                result.warnings.append(Diagnostic.LOG_FAILED)

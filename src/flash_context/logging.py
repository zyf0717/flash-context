from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from flash_context.types import (
    ExploreRequest,
    ExplorerError,
    ExploreResult,
    ToolObservation,
)


class TrajectoryRecorder:
    def __init__(self, traj_dir: Path | None, request: ExploreRequest) -> None:
        self._traj_dir = traj_dir
        self._data: dict[str, object] = {
            "request": request.to_dict(),
            "turns": [],
            "result": None,
            "error": None,
        }

    def record_model_turn(self, turn: int, message: dict[str, object]) -> None:
        if self._traj_dir is None:
            return
        self._turns().append(
            {
                "turn": turn,
                "message": _sanitize_model_message(message),
            }
        )

    def record_observation(
        self,
        turn: int,
        tool_name: str,
        observation: ToolObservation,
    ) -> None:
        if self._traj_dir is None:
            return
        self._turns().append(
            {
                "turn": turn,
                "tool": tool_name,
                "observation": observation.to_dict(include_content=False),
            }
        )

    def finish(
        self,
        *,
        result: ExploreResult | None = None,
        error: ExplorerError | None = None,
    ) -> None:
        if self._traj_dir is None:
            return
        self._data["result"] = (
            result.to_dict(include_raw_location_text=False)
            if result is not None
            else None
        )
        self._data["error"] = error.to_dict() if error is not None else None
        self._traj_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S")
        path = self._traj_dir / f"{stamp}-{uuid4().hex}.json"
        content = json.dumps(self._data, indent=2, sort_keys=True)
        path.write_text(content, encoding="utf-8")

    def _turns(self) -> list[dict[str, object]]:
        turns = self._data["turns"]
        if not isinstance(turns, list):
            raise TypeError("trajectory turns storage corrupted")
        return turns


def _sanitize_model_message(message: dict[str, object]) -> dict[str, object]:
    sanitized = dict(message)
    content = sanitized.get("content")
    if isinstance(content, str) and len(content) > 500:
        sanitized["content"] = f"{content[:500]}..."
    return sanitized

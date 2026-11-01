from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from flash_context.agent import explore
from flash_context.config import Settings
from flash_context.llm import ChatClient
from flash_context.types import (
    ExploreRequest,
)
from tests.helpers import (
    _message_response,
    _mock_transport,
    _tool_response,
)


def test_trajectory_log_omits_denied_file_content(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".env").write_text("SECRET_TOKEN=abc", encoding="utf-8")
    traj_dir = tmp_path / "traj"
    settings = Settings(
        base_url="http://test/v1",
        model="test-model",
        traj_dir=traj_dir,
    )
    responses: Iterator[dict[str, object]] = iter(
        [
            _tool_response("call_1", "read_file", {"path": ".env"}),
            _message_response("No accessible citation."),
        ]
    )
    client = ChatClient(settings, transport=_mock_transport(responses, []))

    explore(ExploreRequest(query="read env", repo_root=repo), settings, client=client)

    logs = list(traj_dir.glob("*.json"))
    assert len(logs) == 1
    assert "SECRET_TOKEN" not in logs[0].read_text(encoding="utf-8")


def test_trajectory_log_omits_raw_location_text(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "answer.py").write_text("RAW_LOCATION_SECRET\n", encoding="utf-8")
    traj_dir = tmp_path / "traj"
    settings = Settings(
        base_url="http://test/v1",
        model="test-model",
        traj_dir=traj_dir,
    )
    responses: Iterator[dict[str, object]] = iter([_message_response("answer.py:1")])
    client = ChatClient(settings, transport=_mock_transport(responses, []))

    explore(
        ExploreRequest(query="find the relevant answer", repo_root=repo),
        settings,
        client=client,
    )

    logs = list(traj_dir.glob("*.json"))
    assert len(logs) == 1
    content = logs[0].read_text(encoding="utf-8")
    assert "RAW_LOCATION_SECRET" not in content
    assert "text_length" in content

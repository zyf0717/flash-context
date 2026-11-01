from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from threading import Event, Lock
from typing import Any, cast

import pytest

import flash_context.execution as execution
from flash_context.agent import explore
from flash_context.config import Settings
from flash_context.execution import _model_observation_payload
from flash_context.llm import ChatClient
from flash_context.types import (
    ExploreRequest,
    ToolCall,
    ToolObservation,
)
from tests.helpers import (
    _last_tool_payload,
    _message_response,
    _mock_transport,
    _multi_tool_response,
    _tool_response,
)


def test_chat_payload_includes_latency_controls(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    responses: Iterator[dict[str, object]] = iter(
        [_message_response("NO_CITATIONS_FOUND")]
    )
    seen_payloads: list[dict[str, object]] = []
    settings = Settings(
        base_url="http://test/v1",
        model="test-model",
        max_completion_tokens=99,
        temperature=0.2,
    )
    client = ChatClient(settings, transport=_mock_transport(responses, seen_payloads))

    explore(
        ExploreRequest(query="Find request validation", repo_root=repo),
        settings,
        client=client,
    )

    assert seen_payloads[0]["max_tokens"] == 99
    assert seen_payloads[0]["temperature"] == 0.2


def test_duplicate_calls_reuse_observations_and_preserve_fresh_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "a.py").write_text("def first(): pass\n")
    (tmp_path / "b.py").write_text("def second(): pass\n")
    calls: list[str] = []
    execute = execution._execute_tool_call

    def tracked(
        call: ToolCall, *, repo_root: Path, settings: Settings
    ) -> ToolObservation:
        calls.append(str(call.arguments["glob"]))
        return execute(call, repo_root=repo_root, settings=settings)

    monkeypatch.setattr(execution, "_execute_tool_call", tracked)
    first: dict[str, object] = {"pattern": "def", "glob": "a.py"}
    second: dict[str, object] = {"pattern": "def", "glob": "b.py"}
    responses = iter(
        [
            _multi_tool_response(
                [
                    ("a", "repo_grep", first),
                    ("b", "repo_grep", first),
                ]
            ),
            _multi_tool_response(
                [
                    ("c", "repo_grep", first),
                    ("d", "repo_grep", second),
                ]
            ),
            _message_response("b.py:1"),
        ]
    )
    payloads: list[dict[str, object]] = []
    settings = Settings(base_url="http://test/v1", model="test-model")
    client = ChatClient(settings, transport=_mock_transport(responses, payloads))
    result = explore(
        ExploreRequest(query="Find all definitions", repo_root=tmp_path),
        settings,
        client=client,
    )
    assert calls == ["a.py", "b.py"]
    assert result.answer == "b.py:1"
    messages = cast(list[dict[str, Any]], payloads[-1]["messages"])
    observations = [m for m in messages if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in observations] == ["a", "b", "c", "d"]
    assert [json.loads(m["content"])["tool_call_id"] for m in observations] == [
        "a",
        "b",
        "c",
        "d",
    ]
    assert observations[0]["content"] != observations[2]["content"]
    assert "repeated tool call stopped exploration" not in result.warnings


def test_model_read_without_range_is_bounded_before_observation(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "agent.py").write_text(
        "".join(f"line {line}\n" for line in range(1, 10)),
        encoding="utf-8",
    )
    responses: Iterator[dict[str, object]] = iter(
        [
            _tool_response("call_1", "read_file", {"path": "agent.py"}),
            _message_response("The file has the answer."),
        ]
    )
    seen_payloads: list[dict[str, object]] = []
    settings = Settings(
        base_url="http://test/v1",
        model="test-model",
        max_read_lines=3,
    )
    client = ChatClient(settings, transport=_mock_transport(responses, seen_payloads))

    result = explore(
        ExploreRequest(query="Find the relevant answer", repo_root=repo),
        settings,
        client=client,
    )

    observation = _last_tool_payload(seen_payloads)
    assert observation["line_range"] == "1-3"
    assert observation["truncated"] is True
    assert "3: line 3" in str(observation["content"])
    assert "4: line 4" not in str(observation["content"])
    assert result.truncated is True


def test_model_observation_content_is_capped_for_endpoint_payload(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "agent.py").write_text("x" * 200 + "\n", encoding="utf-8")
    responses: Iterator[dict[str, object]] = iter(
        [
            _tool_response(
                "call_1",
                "read_file",
                {"path": "agent.py", "start_line": 1, "end_line": 1},
            ),
            _message_response("agent.py:1"),
        ]
    )
    seen_payloads: list[dict[str, object]] = []
    settings = Settings(
        base_url="http://test/v1",
        model="test-model",
        max_observation_chars=20,
    )
    client = ChatClient(settings, transport=_mock_transport(responses, seen_payloads))

    explore(
        ExploreRequest(query="Find the relevant answer", repo_root=repo),
        settings,
        client=client,
    )

    observation = _last_tool_payload(seen_payloads)
    assert len(str(observation["content"])) == 20
    assert observation["content_truncated_by_chars"] is True
    assert observation["truncated"] is True


def test_same_turn_tool_calls_execute_concurrently_and_preserve_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    responses: Iterator[dict[str, object]] = iter(
        [
            _multi_tool_response(
                [
                    ("call_1", "repo_glob", {"pattern": "src/**/*.py"}),
                    ("call_2", "repo_glob", {"pattern": "tests/**/*.py"}),
                ]
            ),
            _message_response("NO_CITATIONS_FOUND"),
        ]
    )
    seen_payloads: list[dict[str, object]] = []
    settings = Settings(
        base_url="http://test/v1",
        model="test-model",
        max_parallel_tools=2,
    )
    client = ChatClient(settings, transport=_mock_transport(responses, seen_payloads))
    second_started = Event()
    lock = Lock()
    started: list[str] = []
    first_call_saw_second: list[bool] = []

    def fake_execute(
        tool_call: ToolCall,
        *,
        repo_root: Path,
        settings: Settings,
    ) -> ToolObservation:
        with lock:
            started.append(tool_call.id)
            if len(started) >= 2:
                second_started.set()
        if tool_call.id == "call_1":
            first_call_saw_second.append(second_started.wait(timeout=1.0))
        return ToolObservation(matches=[tool_call.id])

    monkeypatch.setattr(execution, "_execute_tool_call", fake_execute)

    explore(
        ExploreRequest(query="Find independent files", repo_root=repo),
        settings,
        client=client,
    )

    assert first_call_saw_second == [True]
    messages = cast(list[dict[str, Any]], seen_payloads[1]["messages"])
    tool_messages = [message for message in messages if message.get("role") == "tool"]
    assert [message["tool_call_id"] for message in tool_messages] == [
        "call_1",
        "call_2",
    ]
    contents = [
        cast(dict[str, object], json.loads(str(message["content"])))
        for message in tool_messages
    ]
    assert [content["matches"] for content in contents] == [["call_1"], ["call_2"]]


def test_max_parallel_tools_one_preserves_serial_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    responses: Iterator[dict[str, object]] = iter(
        [
            _multi_tool_response(
                [
                    ("call_1", "repo_glob", {"pattern": "src/**/*.py"}),
                    ("call_2", "repo_glob", {"pattern": "tests/**/*.py"}),
                ]
            ),
            _message_response("NO_CITATIONS_FOUND"),
        ]
    )
    settings = Settings(
        base_url="http://test/v1",
        model="test-model",
        max_parallel_tools=1,
    )
    client = ChatClient(settings, transport=_mock_transport(responses, []))
    second_started = Event()
    lock = Lock()
    started: list[str] = []
    first_call_saw_second: list[bool] = []

    def fake_execute(
        tool_call: ToolCall,
        *,
        repo_root: Path,
        settings: Settings,
    ) -> ToolObservation:
        with lock:
            started.append(tool_call.id)
            if len(started) >= 2:
                second_started.set()
        if tool_call.id == "call_1":
            first_call_saw_second.append(second_started.wait(timeout=0.01))
        return ToolObservation(matches=[tool_call.id])

    monkeypatch.setattr(execution, "_execute_tool_call", fake_execute)

    explore(
        ExploreRequest(query="Find independent files", repo_root=repo),
        settings,
        client=client,
    )

    assert started == ["call_1", "call_2"]
    assert first_call_saw_second == [False]


def test_same_turn_tool_error_does_not_cancel_sibling_tool(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".env").write_text("SECRET=1", encoding="utf-8")
    (repo / "safe.py").write_text("print('safe')\n", encoding="utf-8")
    responses: Iterator[dict[str, object]] = iter(
        [
            _multi_tool_response(
                [
                    ("call_1", "read_file", {"path": ".env"}),
                    ("call_2", "repo_glob", {"pattern": "**/*.py"}),
                ]
            ),
            _message_response("NO_CITATIONS_FOUND"),
        ]
    )
    seen_payloads: list[dict[str, object]] = []
    settings = Settings(base_url="http://test/v1", model="test-model")
    client = ChatClient(settings, transport=_mock_transport(responses, seen_payloads))

    explore(
        ExploreRequest(query="Find safe files", repo_root=repo),
        settings,
        client=client,
    )

    messages = cast(list[dict[str, Any]], seen_payloads[1]["messages"])
    tool_messages = [message for message in messages if message.get("role") == "tool"]
    contents = [
        cast(dict[str, object], json.loads(str(message["content"])))
        for message in tool_messages
    ]
    first_error = cast(dict[str, object], contents[0]["error"])
    assert contents[0]["ok"] is False
    assert first_error["code"] == "PATH_DENIED"
    assert contents[1]["ok"] is True
    assert contents[1]["matches"] == ["safe.py"]


def test_model_observation_payload_numbers_read_content() -> None:
    payload = _model_observation_payload(
        ToolObservation(
            path="src/flash_context/types.py",
            line_range="135-136",
            content="def validate(self) -> None:\n    pass\n",
        )
    )

    assert payload["content"] == "135: def validate(self) -> None:\n136:     pass\n"

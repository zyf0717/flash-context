from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from threading import Event, Lock
from typing import Any, cast

import httpx
import pytest

import flash_context.agent as agent_module
from flash_context.agent import _model_observation_payload, explore, format_text_result
from flash_context.config import Settings
from flash_context.llm import ChatClient
from flash_context.types import (
    Citation,
    ExploreRequest,
    ExplorerError,
    RawLocation,
    ToolCall,
    ToolObservation,
)


def test_exact_citation_fast_path_skips_endpoint_config(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "agent.py").write_text("line 1\nline 2\n", encoding="utf-8")
    settings = Settings()

    result = explore(
        ExploreRequest(query="Use agent.py:1-2", repo_root=repo),
        settings,
    )

    assert result.turns_used == 0
    assert result.answer == "agent.py:1-2"
    assert [citation.label() for citation in result.citations] == ["agent.py:1-2"]
    assert result.raw_locations == [RawLocation("agent.py", 1, 2, "line 1\nline 2\n")]


def test_explicit_path_symbol_fast_path_returns_matching_line(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "config.py").write_text(
        "class Settings:\n    max_parallel_tools: int = 4\n",
        encoding="utf-8",
    )
    settings = Settings()

    result = explore(
        ExploreRequest(
            query="In src/config.py, find `max_parallel_tools`.",
            repo_root=repo,
        ),
        settings,
    )

    assert result.turns_used == 0
    assert result.answer == "src/config.py:2"


def test_explicit_path_symbol_fast_path_ignores_sentence_punctuation(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "llm.py").write_text(
        '"tool_choice": "auto",\n',
        encoding="utf-8",
    )
    settings = Settings()

    result = explore(
        ExploreRequest(
            query='Find "tool_choice" in src/llm.py.',
            repo_root=repo,
        ),
        settings,
    )

    assert result.turns_used == 0
    assert result.answer == "src/llm.py:1"


def test_pathless_unique_definition_fast_path_skips_endpoint(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "agent.py").write_text(
        "def explore():\n    pass\n",
        encoding="utf-8",
    )
    settings = Settings()

    result = explore(
        ExploreRequest(query="Find `explore`", repo_root=repo),
        settings,
    )

    assert result.turns_used == 0
    assert result.answer == "src/agent.py:1"


def test_pathless_assignment_match_uses_model_loop(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "config.py").write_text("max_parallel_tools = 4\n", encoding="utf-8")
    responses: Iterator[dict[str, object]] = iter(
        [_message_response("NO_CITATIONS_FOUND")]
    )
    seen_payloads: list[dict[str, object]] = []
    settings = Settings(base_url="http://test/v1", model="test-model")
    client = ChatClient(settings, transport=_mock_transport(responses, seen_payloads))

    result = explore(
        ExploreRequest(query="Find `max_parallel_tools`", repo_root=repo),
        settings,
        client=client,
    )

    assert result.turns_used == 1
    assert result.answer == "NO_CITATIONS_FOUND"
    assert len(seen_payloads) == 1


def test_multiple_pathless_definitions_use_model_loop(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    (repo / "a").mkdir(parents=True)
    (repo / "b").mkdir(parents=True)
    (repo / "a" / "agent.py").write_text("def explore():\n    pass\n", encoding="utf-8")
    (repo / "b" / "agent.py").write_text("def explore():\n    pass\n", encoding="utf-8")
    responses: Iterator[dict[str, object]] = iter(
        [_message_response("NO_CITATIONS_FOUND")]
    )
    seen_payloads: list[dict[str, object]] = []
    settings = Settings(base_url="http://test/v1", model="test-model")
    client = ChatClient(settings, transport=_mock_transport(responses, seen_payloads))

    result = explore(
        ExploreRequest(query="Find `explore`", repo_root=repo),
        settings,
        client=client,
    )

    assert result.turns_used == 1
    assert result.answer == "NO_CITATIONS_FOUND"
    assert len(seen_payloads) == 1


def test_pathless_definition_in_markdown_does_not_fast_path(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "spec.md").write_text(
        "```python\ndef explore():\n    pass\n```\n",
        encoding="utf-8",
    )
    responses: Iterator[dict[str, object]] = iter(
        [_message_response("NO_CITATIONS_FOUND")]
    )
    seen_payloads: list[dict[str, object]] = []
    settings = Settings(base_url="http://test/v1", model="test-model")
    client = ChatClient(settings, transport=_mock_transport(responses, seen_payloads))

    result = explore(
        ExploreRequest(query="Find `explore`", repo_root=repo),
        settings,
        client=client,
    )

    assert result.turns_used == 1
    assert result.answer == "NO_CITATIONS_FOUND"
    assert len(seen_payloads) == 1


def test_semantic_query_with_exact_symbol_uses_model_loop(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "agent.py").write_text("def explore():\n    pass\n", encoding="utf-8")
    responses: Iterator[dict[str, object]] = iter(
        [_message_response("NO_CITATIONS_FOUND")]
    )
    seen_payloads: list[dict[str, object]] = []
    settings = Settings(base_url="http://test/v1", model="test-model")
    client = ChatClient(settings, transport=_mock_transport(responses, seen_payloads))

    result = explore(
        ExploreRequest(query="How does `explore` work?", repo_root=repo),
        settings,
        client=client,
    )

    assert result.turns_used == 1
    assert result.answer == "NO_CITATIONS_FOUND"
    assert len(seen_payloads) == 1


def test_denied_explicit_path_does_not_fast_path_or_leak_content(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".env").write_text("SECRET=1\n", encoding="utf-8")
    responses: Iterator[dict[str, object]] = iter(
        [_message_response("NO_CITATIONS_FOUND")]
    )
    seen_payloads: list[dict[str, object]] = []
    settings = Settings(base_url="http://test/v1", model="test-model")
    client = ChatClient(settings, transport=_mock_transport(responses, seen_payloads))

    result = explore(
        ExploreRequest(query="Find `SECRET` in .env", repo_root=repo),
        settings,
        client=client,
    )

    assert result.turns_used == 1
    assert result.answer == "NO_CITATIONS_FOUND"
    assert "SECRET=1" not in json.dumps(seen_payloads)


def test_model_loop_without_endpoint_still_requires_endpoint(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    settings = Settings()

    with pytest.raises(ExplorerError) as exc_info:
        explore(
            ExploreRequest(query="Find missing_symbol", repo_root=repo),
            settings,
        )

    assert exc_info.value.code == "CONFIG_MISSING_ENDPOINT"


def test_mock_endpoint_drives_glob_grep_read_loop(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "src" / "api").mkdir(parents=True)
    (repo / "src" / "api" / "validation.py").write_text(
        "def validate_request(payload):\n    return bool(payload)\n",
        encoding="utf-8",
    )
    responses: Iterator[dict[str, object]] = iter(
        [
            _tool_response("call_1", "repo_glob", {"pattern": "src/**/*.py"}),
            _tool_response(
                "call_2",
                "repo_grep",
                {"pattern": "validate_request", "glob": "src/**/*.py"},
            ),
            _tool_response(
                "call_3",
                "read_file",
                {"path": "src/api/validation.py", "start_line": 1, "end_line": 2},
            ),
            _message_response("src/api/validation.py:1\nValidation entrypoint."),
        ]
    )
    seen_payloads: list[dict[str, object]] = []
    settings = Settings(base_url="http://test/v1", model="test-model")
    client = ChatClient(settings, transport=_mock_transport(responses, seen_payloads))

    result = explore(
        ExploreRequest(query="Find request validation", repo_root=repo),
        settings,
        client=client,
    )

    assert result.citations[0].path == "src/api/validation.py"
    assert result.citations[0].start_line == 1
    assert result.turns_used == 4
    assert any(
        message.get("role") == "tool"
        for payload in seen_payloads[1:]
        for message in cast(list[dict[str, Any]], payload["messages"])
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


def test_content_with_trailing_tool_calls_stops_on_valid_citations(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    (repo / "src" / "api").mkdir(parents=True)
    (repo / "src" / "api" / "validation.py").write_text(
        "def validate_request(payload):\n    return bool(payload)\n",
        encoding="utf-8",
    )
    responses: Iterator[dict[str, object]] = iter(
        [
            _tool_response(
                "call_1",
                "read_file",
                {"path": "src/api/validation.py", "start_line": 1, "end_line": 2},
            ),
            _tool_response(
                "call_2",
                "read_file",
                {"path": "src/api/validation.py", "start_line": 1, "end_line": 2},
                content="src/api/validation.py:1",
            ),
        ]
    )
    seen_payloads: list[dict[str, object]] = []
    settings = Settings(base_url="http://test/v1", model="test-model")
    client = ChatClient(settings, transport=_mock_transport(responses, seen_payloads))

    result = explore(
        ExploreRequest(query="Find request validation", repo_root=repo),
        settings,
        client=client,
    )

    assert result.turns_used == 2
    assert len(seen_payloads) == 2
    assert [citation.label() for citation in result.citations] == [
        "src/api/validation.py:1-2"
    ]
    assert "ignored trailing tool calls after valid citations" in result.warnings


def test_repeated_read_does_not_promote_unselected_evidence(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "src" / "api").mkdir(parents=True)
    (repo / "src" / "api" / "validation.py").write_text(
        "def validate_request(payload):\n    return bool(payload)\n",
        encoding="utf-8",
    )
    repeated_call = {
        "path": "src/api/validation.py",
        "start_line": 1,
        "end_line": 2,
    }
    responses: Iterator[dict[str, object]] = iter(
        [
            _tool_response("call_1", "read_file", repeated_call),
            _tool_response("call_2", "read_file", repeated_call),
        ]
    )
    settings = Settings(base_url="http://test/v1", model="test-model", max_turns=6)
    client = ChatClient(settings, transport=_mock_transport(responses, []))

    result = explore(
        ExploreRequest(query="Find request validation", repo_root=repo),
        settings,
        client=client,
    )

    assert result.turns_used == 2
    assert result.citations == []
    assert "repeated tool call stopped exploration" in result.warnings


def test_duplicate_calls_reuse_observations_and_preserve_fresh_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "a.py").write_text("def first(): pass\n")
    (tmp_path / "b.py").write_text("def second(): pass\n")
    calls: list[str] = []
    execute = agent_module._execute_tool_call

    def tracked(
        call: ToolCall, *, repo_root: Path, settings: Settings
    ) -> ToolObservation:
        calls.append(str(call.arguments["glob"]))
        return execute(call, repo_root=repo_root, settings=settings)

    monkeypatch.setattr(agent_module, "_execute_tool_call", tracked)
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


@pytest.mark.parametrize("trailing_tool", [False, True])
def test_implementation_query_continues_past_documentation(
    tmp_path: Path,
    trailing_tool: bool,
) -> None:
    (tmp_path / "guide.md").write_text("Telegram overview\n")
    (tmp_path / "handler.js").write_text("function handleTelegram() {}\n")
    first = (
        _tool_response(
            "read", "read_file", {"path": "handler.js"}, content="guide.md:1"
        )
        if trailing_tool
        else _message_response("guide.md:1")
    )
    responses = iter([first, _message_response("handler.js:1")])
    payloads: list[dict[str, object]] = []
    settings = Settings(base_url="http://test/v1", model="test-model")
    result = explore(
        ExploreRequest(
            query="Where does the gateway handle Telegram messages?", repo_root=tmp_path
        ),
        settings,
        client=ChatClient(settings, transport=_mock_transport(responses, payloads)),
    )
    assert result.turns_used == 2
    assert result.answer == "handler.js:1"
    assert not result.truncated
    messages = cast(list[dict[str, Any]], payloads[-1]["messages"])
    assert "Continue searching" in messages[-1]["content"]
    if trailing_tool:
        assert any(m["role"] == "tool" for m in messages)


@pytest.mark.parametrize("citation", [False, True])
def test_documentation_fallback_is_explicitly_incomplete(
    tmp_path: Path,
    citation: bool,
) -> None:
    (tmp_path / "guide.md").write_text("Telegram overview\n")
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist/handler.js").write_text("SECRET_IMPLEMENTATION\n")
    responses = iter(
        [
            _message_response("The implementation is in guide.md:1"),
            _tool_response("denied", "read_file", {"path": "dist/handler.js"}),
            _tool_response("repeat", "read_file", {"path": "dist/handler.js"}),
        ]
    )
    payloads: list[dict[str, object]] = []
    settings = Settings(base_url="http://test/v1", model="test-model", max_turns=3)
    result = explore(
        ExploreRequest(
            query="Find the Telegram implementation",
            repo_root=tmp_path,
            citation=citation,
        ),
        settings,
        client=ChatClient(settings, transport=_mock_transport(responses, payloads)),
    )
    assert result.answer == "guide.md:1"
    assert result.truncated
    assert result.raw_locations[0].text == "Telegram overview\n"
    assert (
        "implementation source not verified; returning documentation evidence"
        in result.warnings
    )
    assert "SECRET_IMPLEMENTATION" not in json.dumps(payloads)


def test_documentation_request_finishes_without_source_search(tmp_path: Path) -> None:
    (tmp_path / "guide.md").write_text("Handler documentation\n")
    settings = Settings(base_url="http://test/v1", model="test-model")
    responses = iter([_message_response("guide.md:1")])
    result = explore(
        ExploreRequest(query="Find the handler documentation", repo_root=tmp_path),
        settings,
        client=ChatClient(settings, transport=_mock_transport(responses, [])),
    )
    assert result.turns_used == 1
    assert not result.truncated
    assert not result.warnings


def test_documentation_fallback_at_turn_limit(tmp_path: Path) -> None:
    (tmp_path / "README").write_text("Integration overview\n")
    settings = Settings(base_url="http://test/v1", model="test-model", max_turns=2)
    responses = iter([_message_response("README:1"), _message_response("README:1")])
    result = explore(
        ExploreRequest(
            query="Find the Telegram handler implementation", repo_root=tmp_path
        ),
        settings,
        client=ChatClient(settings, transport=_mock_transport(responses, [])),
    )
    assert result.turns_used == 2
    assert result.answer == "README:1"
    assert result.truncated
    assert (
        "implementation source not verified; returning documentation evidence"
        in result.warnings
    )


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

    monkeypatch.setattr(agent_module, "_execute_tool_call", fake_execute)

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

    monkeypatch.setattr(agent_module, "_execute_tool_call", fake_execute)

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


def test_narrow_evidence_stops_before_another_broad_read(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "agent.py").write_text(
        "".join(f"line {line}\n" for line in range(1, 40)),
        encoding="utf-8",
    )
    responses: Iterator[dict[str, object]] = iter(
        [
            _tool_response(
                "call_1",
                "read_file",
                {"path": "agent.py", "start_line": 5, "end_line": 7},
            ),
            _tool_response("call_2", "read_file", {"path": "agent.py"}),
        ]
    )
    seen_payloads: list[dict[str, object]] = []
    settings = Settings(
        base_url="http://test/v1",
        model="test-model",
        max_read_lines=10,
    )
    client = ChatClient(settings, transport=_mock_transport(responses, seen_payloads))

    result = explore(
        ExploreRequest(query="Find `line`", repo_root=repo),
        settings,
        client=client,
    )

    assert len(seen_payloads) == 2
    assert [citation.label() for citation in result.citations] == ["agent.py:1-10"]
    assert "sufficient narrow evidence stopped broad read" in result.warnings


def test_final_prose_does_not_promote_unselected_reads(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "src" / "flash_context").mkdir(parents=True)
    (repo / "src" / "flash_context" / "agent.py").write_text(
        "".join(f"line {line}\n" for line in range(1, 401)),
        encoding="utf-8",
    )
    responses: Iterator[dict[str, object]] = iter(
        [
            _tool_response(
                "call_1",
                "read_file",
                {"path": "src/flash_context/agent.py"},
            ),
            _tool_response(
                "call_2",
                "read_file",
                {
                    "path": "src/flash_context/agent.py",
                    "start_line": 352,
                    "end_line": 365,
                },
            ),
            _message_response("The helper is at line 352."),
        ]
    )
    settings = Settings(base_url="http://test/v1", model="test-model")
    client = ChatClient(settings, transport=_mock_transport(responses, []))

    result = explore(
        ExploreRequest(query="Find citation validation", repo_root=repo),
        settings,
        client=client,
    )

    assert result.answer == "NO_CITATIONS_FOUND"
    assert "final answer did not include valid citations" in result.warnings


def test_citation_mode_strips_model_prose(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "src" / "api").mkdir(parents=True)
    (repo / "src" / "api" / "validation.py").write_text(
        "def validate_request(payload):\n    return bool(payload)\n",
        encoding="utf-8",
    )
    responses: Iterator[dict[str, object]] = iter(
        [
            _message_response(
                "Here is the answer:\n\nsrc/api/validation.py:1\n\n"
                "This is where validation happens."
            )
        ]
    )
    settings = Settings(base_url="http://test/v1", model="test-model")
    client = ChatClient(settings, transport=_mock_transport(responses, []))

    result = explore(
        ExploreRequest(query="Find request validation", repo_root=repo),
        settings,
        client=client,
    )

    assert result.answer == "src/api/validation.py:1-2"
    assert format_text_result(result, citation=True) == "src/api/validation.py:1-2"


def test_citation_prompt_uses_final_answer_block_and_normalizes_output(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    (repo / "src" / "api").mkdir(parents=True)
    (repo / "src" / "api" / "validation.py").write_text(
        "def validate_request(payload):\n    return bool(payload)\n",
        encoding="utf-8",
    )
    responses: Iterator[dict[str, object]] = iter(
        [
            _message_response(
                "Done.\n<final_answer>\nsrc/api/validation.py:1\n</final_answer>"
            )
        ]
    )
    seen_payloads: list[dict[str, object]] = []
    settings = Settings(base_url="http://test/v1", model="test-model")
    client = ChatClient(settings, transport=_mock_transport(responses, seen_payloads))

    result = explore(
        ExploreRequest(query="Find request validation", repo_root=repo),
        settings,
        client=client,
    )

    first_messages = cast(list[dict[str, Any]], seen_payloads[0]["messages"])
    assert "<final_answer>" in str(first_messages[0]["content"])
    assert "multiple tool calls in the same turn" in str(first_messages[0]["content"])
    assert result.answer == "src/api/validation.py:1-2"
    assert [citation.label() for citation in result.citations] == [
        "src/api/validation.py:1-2"
    ]


def test_final_citations_preserve_adjacent_definitions(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def a(): pass\ndef b(): pass\n")
    settings = Settings(base_url="http://test/v1", model="mock")
    client = ChatClient(
        settings,
        transport=_mock_transport(iter([_message_response("a.py#a\na.py#b")]), []),
    )
    result = explore(
        ExploreRequest("Where are the functions?", tmp_path), settings, client=client
    )
    assert result.answer == "a.py:1\na.py:2"
    assert len(result.raw_locations) == 2


def test_raw_location_truncation_is_reported(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "big.py").write_text("abcdef\n", encoding="utf-8")
    settings = Settings(max_read_bytes=3)

    result = explore(ExploreRequest(query="Use big.py:1", repo_root=repo), settings)

    assert result.answer == "big.py:1"
    assert result.raw_locations == [RawLocation("big.py", 1, 1, "abc", truncated=True)]
    assert "raw location truncated" in result.warnings


def test_unreadable_raw_location_is_omitted_with_warning(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".env").write_text("SECRET_TOKEN=abc\n", encoding="utf-8")
    warnings: list[str] = []

    raw_locations = agent_module._extract_raw_locations(
        [Citation(".env", 1, 1)],
        repo_root=repo,
        settings=Settings(),
        warnings=warnings,
    )

    assert raw_locations == []
    assert warnings == ["raw location could not be read"]


def test_hallucinated_citation_is_rejected(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    settings = Settings(base_url="http://test/v1", model="test-model")
    responses: Iterator[dict[str, object]] = iter(
        [_message_response("src/missing.py:1"), _message_response("NO_CITATIONS_FOUND")]
    )
    client = ChatClient(settings, transport=_mock_transport(responses, []))

    result = explore(
        ExploreRequest(query="Find request validation", repo_root=repo),
        settings,
        client=client,
    )

    assert result.answer == "NO_CITATIONS_FOUND"
    assert result.citations == []
    assert "invalid citation rejected" in result.warnings


def test_unparsed_line_anchor_uses_bounded_window(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "src" / "api").mkdir(parents=True)
    (repo / "src" / "api" / "validation.py").write_text(
        "".join(f"line {line}\n" for line in range(1, 61)),
        encoding="utf-8",
    )
    responses: Iterator[dict[str, object]] = iter(
        [
            _tool_response(
                "call_1",
                "read_file",
                {"path": "src/api/validation.py", "start_line": 1, "end_line": 2},
            ),
            _message_response("src/api/validation.py:50"),
        ]
    )
    settings = Settings(base_url="http://test/v1", model="test-model")
    client = ChatClient(settings, transport=_mock_transport(responses, []))

    result = explore(
        ExploreRequest(query="Find request validation", repo_root=repo),
        settings,
        client=client,
    )

    assert [citation.label() for citation in result.citations] == [
        "src/api/validation.py:45-55"
    ]


def test_unsupported_tool_call_is_fatal(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    settings = Settings(base_url="http://test/v1", model="test-model")
    responses: Iterator[dict[str, object]] = iter(
        [_tool_response("call_1", "write_file", {"path": "x"})]
    )
    client = ChatClient(settings, transport=_mock_transport(responses, []))

    with pytest.raises(ExplorerError) as exc_info:
        explore(ExploreRequest(query="write", repo_root=repo), settings, client=client)

    assert exc_info.value.code == "UNSUPPORTED_TOOL_CALL"


def test_max_turns_returns_partial_answer_when_model_provided_content(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "validation.py").write_text(
        "def validate_request(payload):\n    return bool(payload)\n",
        encoding="utf-8",
    )
    settings = Settings(base_url="http://test/v1", model="test-model", max_turns=1)
    responses: Iterator[dict[str, object]] = iter(
        [
            _tool_response(
                "call_1",
                "read_file",
                {"path": "validation.py"},
                content="validation.py contains request validation.",
            )
        ]
    )
    client = ChatClient(settings, transport=_mock_transport(responses, []))

    result = explore(
        ExploreRequest(
            query="Find request validation",
            repo_root=repo,
            max_turns=1,
        ),
        settings,
        client=client,
    )

    assert result.answer == "NO_CITATIONS_FOUND"
    assert result.citations == []
    assert "max turns exceeded after partial answer" in result.warnings


def test_model_observation_payload_numbers_read_content() -> None:
    payload = _model_observation_payload(
        ToolObservation(
            path="src/flash_context/types.py",
            line_range="135-136",
            content="def validate(self) -> None:\n    pass\n",
        )
    )

    assert payload["content"] == "135: def validate(self) -> None:\n136:     pass\n"


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


def _mock_transport(
    responses: Iterator[dict[str, object]],
    seen_payloads: list[dict[str, object]],
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen_payloads.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(200, json=next(responses))

    return httpx.MockTransport(handler)


def _last_tool_payload(seen_payloads: list[dict[str, object]]) -> dict[str, object]:
    messages = cast(list[dict[str, Any]], seen_payloads[-1]["messages"])
    tool_messages = [message for message in messages if message.get("role") == "tool"]
    assert tool_messages
    return cast(dict[str, object], json.loads(str(tool_messages[-1]["content"])))


def _tool_response(
    call_id: str,
    name: str,
    arguments: dict[str, object],
    *,
    content: str | None = None,
) -> dict[str, object]:
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(arguments),
                            },
                        }
                    ],
                }
            }
        ]
    }


def _multi_tool_response(
    calls: list[tuple[str, str, dict[str, object]]],
    *,
    content: str | None = None,
) -> dict[str, object]:
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(arguments),
                            },
                        }
                        for call_id, name, arguments in calls
                    ],
                }
            }
        ]
    }


def _message_response(content: str) -> dict[str, object]:
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": content,
                }
            }
        ]
    }


@pytest.mark.parametrize(
    ("query", "path"),
    [
        ("pkg/base.py", "pkg/base.py"),
        ('"pkg/base.py"', "pkg/base.py"),
        ("'base.py'", "base.py"),
        ("`README.md`", "README.md"),
        ("LICENSE", "LICENSE"),
    ],
)
def test_bare_path_returns_bounded_preview_without_endpoint(
    tmp_path: Path, query: str, path: str
) -> None:
    file = tmp_path / path
    file.parent.mkdir(exist_ok=True)
    file.write_text("one\ntwo\nthree\n")
    result = explore(
        ExploreRequest(query=query, repo_root=tmp_path), Settings(max_read_lines=2)
    )
    assert result.turns_used == 0
    assert result.answer == f"{path}:1-2"
    assert result.raw_locations == [RawLocation(path, 1, 2, "one\ntwo\n")]
    assert result.truncated


@pytest.mark.parametrize("query", ["missing.py", "empty.py", ".env.local", "../out.py"])
def test_unusable_bare_path_retains_model_routing(tmp_path: Path, query: str) -> None:
    (tmp_path / "empty.py").touch()
    (tmp_path / ".env.local").write_text("SECRET")
    with pytest.raises(ExplorerError, match="CONFIG_MISSING_ENDPOINT") as error:
        explore(ExploreRequest(query=query, repo_root=tmp_path), Settings())
    assert "SECRET" not in str(error.value)


def test_unique_definition_ignores_reference_match_cap(tmp_path: Path) -> None:
    (tmp_path / "a_refs.py").write_text("ref = BaseTransport\n" * 20)
    (tmp_path / "z_base.py").write_text("class BaseTransport:\n    pass\n")
    result = explore(
        ExploreRequest(query="BaseTransport", repo_root=tmp_path), Settings()
    )
    assert result.turns_used == 0
    assert result.answer == "z_base.py:1"


@pytest.mark.parametrize("incomplete", [False, True])
def test_unique_definition_requires_complete_unambiguous_source_and_stubs(
    tmp_path: Path, incomplete: bool
) -> None:
    (tmp_path / "a.py").write_text("class Target: pass\n")
    if incomplete:
        (tmp_path / "z.py").write_text("# padding\n" * 20)
    else:
        (tmp_path / "a.pyi").write_text("class Target: ...\n")
    with pytest.raises(ExplorerError, match="CONFIG_MISSING_ENDPOINT"):
        explore(
            ExploreRequest(query="Target", repo_root=tmp_path),
            Settings(max_scan_bytes=30 if incomplete else 1000),
        )


@pytest.mark.parametrize("exhausted", [False, True])
def test_model_search_scan_failure_reaches_shared_result(
    tmp_path: Path, exhausted: bool
) -> None:
    (tmp_path / "a.py").write_text("padding\n" * 20)
    responses = iter(
        [
            _tool_response("1", "repo_grep", {"pattern": "not_here"}),
            _message_response("NO_CITATIONS_FOUND"),
        ]
    )
    settings = Settings(
        base_url="http://test/v1",
        model="mock",
        max_scan_bytes=10 if exhausted else 1000,
    )
    seen: list[dict[str, object]] = []
    client = ChatClient(settings, transport=_mock_transport(responses, seen))
    try:
        result = explore(
            ExploreRequest(query="How is this implemented?", repo_root=tmp_path),
            settings,
            client=client,
        )
    finally:
        client.close()
    assert result.answer == "NO_CITATIONS_FOUND"
    assert result.truncated is exhausted
    assert result.warnings == (["grep scan budget exhausted"] if exhausted else [])
    assert _last_tool_payload(seen)["truncated"] is exhausted


def test_capped_initial_file_sample_is_not_search_failure(tmp_path: Path) -> None:
    for name in ("a.py", "b.py"):
        (tmp_path / name).write_text("answer\n")
    settings = Settings(base_url="http://test/v1", model="mock", max_grep_results=1)
    responses = iter([_message_response("NO_CITATIONS_FOUND")])
    seen: list[dict[str, object]] = []
    client = ChatClient(settings, transport=_mock_transport(responses, seen))
    try:
        result = explore(
            ExploreRequest(query="How is this implemented?", repo_root=tmp_path),
            settings,
            client=client,
        )
    finally:
        client.close()
    assert not result.truncated
    assert result.warnings == []


def test_exact_documentation_path_stays_endpoint_free(tmp_path: Path) -> None:
    (tmp_path / "guide.md").write_text("Handler overview\n")
    result = explore(ExploreRequest(query="guide.md:1", repo_root=tmp_path), Settings())
    assert result.turns_used == 0
    assert result.answer == "guide.md:1"
    assert not result.warnings


@pytest.mark.parametrize("citation", [False, True])
def test_unselected_source_reads_do_not_replace_documentation(
    tmp_path: Path,
    citation: bool,
) -> None:
    (tmp_path / "guide.md").write_text("Handler overview\n")
    (tmp_path / "handler.py").write_text("def handler(): pass\n")
    responses = iter(
        [
            _tool_response(
                "source", "read_file", {"path": "handler.py"}, content="guide.md:1"
            ),
            _message_response("Unverified documentation claim in guide.md:1"),
        ]
    )
    settings = Settings(base_url="http://test/v1", model="test-model", max_turns=2)
    result = explore(
        ExploreRequest(
            query="Where is the message handler implemented?",
            repo_root=tmp_path,
            citation=citation,
        ),
        settings,
        client=ChatClient(settings, transport=_mock_transport(responses, [])),
    )
    assert result.answer == "guide.md:1"
    assert (
        "implementation source not verified; returning documentation evidence"
        in result.warnings
    )


@pytest.mark.parametrize("citation", [True, False])
@pytest.mark.parametrize("ending", ["direct", "absent", "repeat", "turn", "recover"])
def test_symbol_evidence_cannot_fall_back_to_unrelated_reads(
    tmp_path: Path,
    citation: bool,
    ending: str,
) -> None:
    (tmp_path / "config.py").write_text("class Existing: pass\n")
    (tmp_path / "real.js").write_text("const RetryConfig = {};\n")
    read = _tool_response("read", "read_file", {"path": "config.py"})
    responses_list = {
        "direct": [_message_response("config.py:1"), _message_response(NO_RESULT)],
        "absent": [read, _message_response(NO_RESULT)],
        "repeat": [read, read],
        "turn": [read],
        "recover": [_message_response("config.py:1"), _message_response("real.js:1")],
    }[ending]
    payloads: list[dict[str, object]] = []
    settings = Settings(
        base_url="http://test/v1", model="test", max_turns=len(responses_list)
    )
    client = ChatClient(
        settings, transport=_mock_transport(iter(responses_list), payloads)
    )
    try:
        result = explore(
            ExploreRequest(query="RetryConfig", repo_root=tmp_path, citation=citation),
            settings,
            client=client,
        )
    finally:
        client.close()
    if ending == "recover":
        assert result.citations == [Citation("real.js", 1, 1)]
    else:
        assert result.answer == NO_RESULT
        assert not result.citations and not result.raw_locations
        assert "query symbol not found in verified evidence" in result.warnings
    messages = cast(list[dict[str, Any]], payloads[0]["messages"])
    assert "scan for RetryConfig: missing" in json.dumps(messages)
    assert "other languages" in json.dumps(messages)


NO_RESULT = "NO_CITATIONS_FOUND"


@pytest.mark.parametrize(
    "text", ["RetryConfigExtra", "retryconfig", "xRetryConfig", "other"]
)
def test_symbol_rejection_checks_cached_cited_lines(
    tmp_path: Path,
    text: str,
) -> None:
    (tmp_path / "config.py").write_text(f"RetryConfig = 1\n{text}\n")
    responses = iter(
        [
            _tool_response("read", "read_file", {"path": "config.py"}),
            _message_response("config.py:2"),
            _message_response(NO_RESULT),
        ]
    )
    settings = Settings(base_url="http://test/v1", model="test")
    client = ChatClient(settings, transport=_mock_transport(responses, []))
    try:
        result = explore(
            ExploreRequest(query="RetryConfig", repo_root=tmp_path),
            settings,
            client=client,
        )
    finally:
        client.close()
    # The rejected subrange cannot be accepted just because the cached read
    # contains the token elsewhere. The full read remains valid fallback evidence.
    assert result.citations != [Citation("config.py", 2, 2)]
    assert "invalid citation rejected" in result.warnings


@pytest.mark.parametrize(
    "filename,text",
    [
        ("config.py", "RetryConfig = object()\n"),
        ("config.py", "from other import RetryConfig\n"),
        ("guide.md", "Use RetryConfig here.\n"),
        ("config.js", "const RetryConfig = {};\n"),
    ],
)
def test_symbol_accepts_lexical_evidence_without_python_definition(
    tmp_path: Path,
    filename: str,
    text: str,
) -> None:
    (tmp_path / filename).write_text(text)
    settings = Settings(base_url="http://test/v1", model="test")
    client = ChatClient(
        settings,
        transport=_mock_transport(iter([_message_response(f"{filename}:1")]), []),
    )
    try:
        result = explore(
            ExploreRequest(query="RetryConfig", repo_root=tmp_path),
            settings,
            client=client,
        )
    finally:
        client.close()
    assert result.citations == [Citation(filename, 1, 1)]
    assert result.raw_locations[0].text == text


@pytest.mark.parametrize("complete", [True, False])
def test_symbol_preflight_reports_scan_completeness(
    tmp_path: Path, complete: bool
) -> None:
    (tmp_path / "config.py").write_text("# padding\n" * 30)
    settings = Settings(
        base_url="http://test/v1", model="test", max_scan_bytes=1000 if complete else 20
    )
    payloads: list[dict[str, object]] = []
    client = ChatClient(
        settings,
        transport=_mock_transport(iter([_message_response(NO_RESULT)]), payloads),
    )
    try:
        result = explore(
            ExploreRequest(query="RetryConfig", repo_root=tmp_path),
            settings,
            client=client,
        )
    finally:
        client.close()
    status = "missing" if complete else "incomplete"
    assert f"scan for RetryConfig: {status}" in json.dumps(payloads)
    assert result.truncated is (not complete)
    assert ("grep scan budget exhausted" in result.warnings) is (not complete)


@pytest.mark.parametrize("valid", [False, True])
def test_symbol_token_limited_completion_filters_evidence(
    tmp_path: Path, valid: bool
) -> None:
    (tmp_path / "config.py").write_text(
        "RetryConfig = 1\n" if valid else "unrelated = 1\n"
    )
    response = _message_response("config.py:1")
    cast(list[dict[str, Any]], response["choices"])[0]["finish_reason"] = "length"
    settings = Settings(base_url="http://test/v1", model="test")
    client = ChatClient(settings, transport=_mock_transport(iter([response]), []))
    try:
        if valid:
            result = explore(
                ExploreRequest(query="RetryConfig", repo_root=tmp_path),
                settings,
                client=client,
            )
            assert result.citations == [Citation("config.py", 1, 1)]
            assert result.truncated
        else:
            with pytest.raises(ExplorerError, match="without evidence"):
                explore(
                    ExploreRequest(query="RetryConfig", repo_root=tmp_path),
                    settings,
                    client=client,
                )
    finally:
        client.close()


def test_symbol_cut_at_read_cap_is_unverified(tmp_path: Path) -> None:
    (tmp_path / "config.py").write_text("RetryConfiguration = 1\n")
    settings = Settings(
        base_url="http://test/v1",
        model="test",
        max_read_bytes=len("RetryConfig"),
        max_turns=1,
    )
    client = ChatClient(
        settings,
        transport=_mock_transport(iter([_message_response("config.py:1")]), []),
    )
    try:
        result = explore(
            ExploreRequest(query="RetryConfig", repo_root=tmp_path),
            settings,
            client=client,
        )
    finally:
        client.close()
    assert not result.citations


def test_scoped_symbol_query_rejects_plausible_home_file(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src/config.py").write_text("RetryConfiguration = 1\n")
    settings = Settings(base_url="http://test/v1", model="test", max_turns=1)
    client = ChatClient(
        settings,
        transport=_mock_transport(iter([_message_response("src/config.py:1")]), []),
    )
    try:
        result = explore(
            ExploreRequest(
                query="Find `RetryConfig` in src/config.py", repo_root=tmp_path
            ),
            settings,
            client=client,
        )
    finally:
        client.close()
    assert result.answer == NO_RESULT
    assert not result.citations

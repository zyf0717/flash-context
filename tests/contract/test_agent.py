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
    assert result.raw_locations == [
        RawLocation("agent.py", 1, 2, "line 1\nline 2\n")
    ]


def test_explicit_path_symbol_fast_path_returns_matching_line(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "config.py").write_text(
        "class Settings:\n"
        "    max_parallel_tools: int = 4\n",
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
        "def explore():\n"
        "    pass\n",
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
        "```python\n"
        "def explore():\n"
        "    pass\n"
        "```\n",
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
            _message_response("src/api/validation.py:1-2\nValidation entrypoint."),
        ]
    )
    seen_payloads: list[dict[str, object]] = []
    settings = Settings(base_url="http://test/v1", model="test-model")
    client = ChatClient(settings, transport=_mock_transport(responses, seen_payloads))

    result = explore(
        ExploreRequest(query="Find validation", repo_root=repo),
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
        ExploreRequest(query="Find validation", repo_root=repo),
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
                content="src/api/validation.py:1-2",
            ),
        ]
    )
    seen_payloads: list[dict[str, object]] = []
    settings = Settings(base_url="http://test/v1", model="test-model")
    client = ChatClient(settings, transport=_mock_transport(responses, seen_payloads))

    result = explore(
        ExploreRequest(query="Find validation", repo_root=repo),
        settings,
        client=client,
    )

    assert result.turns_used == 2
    assert len(seen_payloads) == 2
    assert [citation.label() for citation in result.citations] == [
        "src/api/validation.py:1-2"
    ]
    assert "ignored trailing tool calls after valid citations" in result.warnings


def test_repeated_read_breaks_loop_with_best_evidence(tmp_path: Path) -> None:
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
        ExploreRequest(query="Find validation", repo_root=repo),
        settings,
        client=client,
    )

    assert result.turns_used == 2
    assert [citation.label() for citation in result.citations] == [
        "src/api/validation.py:1-2"
    ]
    assert "repeated tool call stopped exploration" in result.warnings


def test_duplicate_same_turn_tool_call_stops_before_scheduling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    responses: Iterator[dict[str, object]] = iter(
        [
            _multi_tool_response(
                [
                    ("call_1", "repo_glob", {"pattern": "**/*.py"}),
                    ("call_2", "repo_glob", {"pattern": "**/*.py"}),
                ]
            )
        ]
    )
    seen_payloads: list[dict[str, object]] = []
    settings = Settings(base_url="http://test/v1", model="test-model")
    client = ChatClient(settings, transport=_mock_transport(responses, seen_payloads))

    def fail_if_scheduled(
        tool_calls: list[ToolCall],
        *,
        repo_root: Path,
        settings: Settings,
    ) -> list[ToolObservation]:
        raise AssertionError("duplicate same-turn calls must not be scheduled")

    monkeypatch.setattr(
        agent_module,
        "_execute_tool_calls_parallel",
        fail_if_scheduled,
    )

    result = explore(
        ExploreRequest(query="Find files", repo_root=repo),
        settings,
        client=client,
    )

    assert len(seen_payloads) == 1
    assert result.answer == "NO_CITATIONS_FOUND"
    assert "repeated tool call stopped exploration" in result.warnings


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
        ExploreRequest(query="Find answer", repo_root=repo),
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
        ExploreRequest(query="Find answer", repo_root=repo),
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
        ExploreRequest(query="Find answer", repo_root=repo),
        settings,
        client=client,
    )

    assert len(seen_payloads) == 2
    assert [citation.label() for citation in result.citations] == ["agent.py:5-7"]
    assert "sufficient narrow evidence stopped broad read" in result.warnings


def test_final_prose_without_citations_uses_best_read_evidence(tmp_path: Path) -> None:
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

    assert result.answer.splitlines() == [
        "src/flash_context/agent.py:1-120",
        "src/flash_context/agent.py:352-365",
    ]
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
                "Here is the answer:\n\n"
                "src/api/validation.py:1-2\n\n"
                "This is where validation happens."
            )
        ]
    )
    settings = Settings(base_url="http://test/v1", model="test-model")
    client = ChatClient(settings, transport=_mock_transport(responses, []))

    result = explore(
        ExploreRequest(query="Find validation", repo_root=repo),
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
                "Done.\n<final_answer>\n"
                "src/api/validation.py:1-2\n"
                "</final_answer>"
            )
        ]
    )
    seen_payloads: list[dict[str, object]] = []
    settings = Settings(base_url="http://test/v1", model="test-model")
    client = ChatClient(settings, transport=_mock_transport(responses, seen_payloads))

    result = explore(
        ExploreRequest(query="Find validation", repo_root=repo),
        settings,
        client=client,
    )

    first_messages = cast(list[dict[str, Any]], seen_payloads[0]["messages"])
    assert "<final_answer>" in str(first_messages[0]["content"])
    assert "multiple tool calls in the same turn" in str(
        first_messages[0]["content"]
    )
    assert result.answer == "src/api/validation.py:1-2"
    assert [citation.label() for citation in result.citations] == [
        "src/api/validation.py:1-2"
    ]


def test_final_citations_merge_and_raw_locations_use_merged_range(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text(
        "".join(f"line {line}\n" for line in range(1, 11)),
        encoding="utf-8",
    )
    responses: Iterator[dict[str, object]] = iter(
        [
            _message_response(
                "<final_answer>\n"
                "a.py:1-3\n"
                "a.py:4-8\n"
                "a.py:7-10\n"
                "</final_answer>"
            )
        ]
    )
    settings = Settings(base_url="http://test/v1", model="test-model")
    client = ChatClient(settings, transport=_mock_transport(responses, []))

    result = explore(
        ExploreRequest(query="Find lines", repo_root=repo),
        settings,
        client=client,
    )

    assert result.answer == "a.py:1-10"
    assert [citation.label() for citation in result.citations] == ["a.py:1-10"]
    assert result.raw_locations == [
        RawLocation(
            path="a.py",
            start_line=1,
            end_line=10,
            text="".join(f"line {line}\n" for line in range(1, 11)),
        )
    ]


def test_raw_location_truncation_is_reported(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "big.py").write_text("abcdef\n", encoding="utf-8")
    settings = Settings(max_read_bytes=3)

    result = explore(ExploreRequest(query="Use big.py:1", repo_root=repo), settings)

    assert result.answer == "big.py:1"
    assert result.raw_locations == [
        RawLocation("big.py", 1, 1, "abc", truncated=True)
    ]
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
        [_message_response("src/missing.py:1-10")]
    )
    client = ChatClient(settings, transport=_mock_transport(responses, []))

    result = explore(
        ExploreRequest(query="Find validation", repo_root=repo),
        settings,
        client=client,
    )

    assert result.answer == "NO_CITATIONS_FOUND"
    assert result.citations == []
    assert "invalid citation rejected" in result.warnings


def test_unseen_citation_range_is_verified_by_bounded_read(tmp_path: Path) -> None:
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
            _message_response("src/api/validation.py:50-60"),
        ]
    )
    settings = Settings(base_url="http://test/v1", model="test-model")
    client = ChatClient(settings, transport=_mock_transport(responses, []))

    result = explore(
        ExploreRequest(query="Find validation", repo_root=repo),
        settings,
        client=client,
    )

    assert [citation.label() for citation in result.citations] == [
        "src/api/validation.py:50-60"
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

    assert result.answer == "validation.py:1-2"
    assert result.citations[0].path == "validation.py"
    assert result.warnings == ["max turns exceeded after partial answer"]


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
    responses: Iterator[dict[str, object]] = iter(
        [_message_response("answer.py:1")]
    )
    client = ChatClient(settings, transport=_mock_transport(responses, []))

    explore(
        ExploreRequest(query="find answer", repo_root=repo),
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

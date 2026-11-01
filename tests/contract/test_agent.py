from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest

from flash_context.agent import search
from flash_context.config import Settings
from flash_context.llm import ChatClient
from flash_context.types import (
    SearchError,
    SearchRequest,
)
from tests.helpers import (
    _last_tool_payload,
    _message_response,
    _mock_transport,
    _tool_response,
)


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

    result = search(
        SearchRequest(query="Find `max_parallel_tools`", repo_root=repo),
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
    (repo / "a" / "agent.py").write_text("def search():\n    pass\n", encoding="utf-8")
    (repo / "b" / "agent.py").write_text("def search():\n    pass\n", encoding="utf-8")
    responses: Iterator[dict[str, object]] = iter(
        [_message_response("NO_CITATIONS_FOUND")]
    )
    seen_payloads: list[dict[str, object]] = []
    settings = Settings(base_url="http://test/v1", model="test-model")
    client = ChatClient(settings, transport=_mock_transport(responses, seen_payloads))

    result = search(
        SearchRequest(query="Find `search`", repo_root=repo),
        settings,
        client=client,
    )

    assert result.turns_used == 1
    assert result.answer == "NO_CITATIONS_FOUND"
    assert len(seen_payloads) == 1


def test_model_loop_without_endpoint_still_requires_endpoint(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    settings = Settings()

    with pytest.raises(SearchError) as exc_info:
        search(
            SearchRequest(query="Find missing_symbol", repo_root=repo),
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

    result = search(
        SearchRequest(query="Find request validation", repo_root=repo),
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


def test_unsupported_tool_call_is_fatal(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    settings = Settings(base_url="http://test/v1", model="test-model")
    responses: Iterator[dict[str, object]] = iter(
        [_tool_response("call_1", "write_file", {"path": "x"})]
    )
    client = ChatClient(settings, transport=_mock_transport(responses, []))

    with pytest.raises(SearchError) as exc_info:
        search(SearchRequest(query="write", repo_root=repo), settings, client=client)

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

    result = search(
        SearchRequest(
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
        result = search(
            SearchRequest(query="How is this implemented?", repo_root=tmp_path),
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
        result = search(
            SearchRequest(query="How is this implemented?", repo_root=tmp_path),
            settings,
            client=client,
        )
    finally:
        client.close()
    assert not result.truncated
    assert result.warnings == []

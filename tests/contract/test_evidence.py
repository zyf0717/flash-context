from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest

import flash_context.agent as agent_module
from flash_context.agent import NO_CITATIONS_FOUND as NO_RESULT
from flash_context.agent import format_text_result, search
from flash_context.config import Settings
from flash_context.llm import ChatClient
from flash_context.types import (
    Citation,
    Diagnostic,
    RawLocation,
    SearchError,
    SearchRequest,
)
from tests.helpers import (
    _message_response,
    _mock_transport,
    _tool_response,
)


def test_semantic_query_with_exact_symbol_uses_model_loop(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "agent.py").write_text("def search():\n    pass\n", encoding="utf-8")
    responses: Iterator[dict[str, object]] = iter(
        [_message_response("NO_CITATIONS_FOUND")]
    )
    seen_payloads: list[dict[str, object]] = []
    settings = Settings(base_url="http://test/v1", model="test-model")
    client = ChatClient(settings, transport=_mock_transport(responses, seen_payloads))

    result = search(
        SearchRequest(query="How does `search` work?", repo_root=repo),
        settings,
        client=client,
    )

    assert result.turns_used == 1
    assert result.answer == "NO_CITATIONS_FOUND"
    assert len(seen_payloads) == 1


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

    result = search(
        SearchRequest(query="Find request validation", repo_root=repo),
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
            _message_response("NO_CITATIONS_FOUND"),
        ]
    )
    settings = Settings(base_url="http://test/v1", model="test-model", max_turns=6)
    client = ChatClient(settings, transport=_mock_transport(responses, []))

    result = search(
        SearchRequest(query="Find request validation", repo_root=repo),
        settings,
        client=client,
    )

    assert result.turns_used == 3
    assert result.citations == []
    assert "repeated tool call stopped search" in result.warnings


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
    result = search(
        SearchRequest(
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
    result = search(
        SearchRequest(
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
    result = search(
        SearchRequest(query="Find the handler documentation", repo_root=tmp_path),
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
    result = search(
        SearchRequest(
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

    result = search(
        SearchRequest(query="Find `line`", repo_root=repo),
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
            _message_response("The helper is at line 352."),
        ]
    )
    settings = Settings(base_url="http://test/v1", model="test-model")
    client = ChatClient(settings, transport=_mock_transport(responses, []))

    result = search(
        SearchRequest(query="Find citation validation", repo_root=repo),
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

    result = search(
        SearchRequest(query="Find request validation", repo_root=repo),
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

    result = search(
        SearchRequest(query="Find request validation", repo_root=repo),
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
    result = search(
        SearchRequest("Where are the functions?", tmp_path), settings, client=client
    )
    assert result.answer == "a.py:1\na.py:2"
    assert len(result.raw_locations) == 2


def test_raw_location_truncation_is_reported(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "big.py").write_text("abcdef\n", encoding="utf-8")
    settings = Settings(max_read_bytes=3)

    result = search(SearchRequest(query="Use big.py:1", repo_root=repo), settings)

    assert result.answer == "big.py:1"
    assert result.raw_locations == [RawLocation("big.py", 1, 1, "abc", truncated=True)]
    assert "raw location truncated" in result.warnings


def test_unreadable_raw_location_is_omitted_with_warning(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".env").write_text("SECRET_TOKEN=abc\n", encoding="utf-8")
    warnings: list[Diagnostic] = []

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

    result = search(
        SearchRequest(query="Find request validation", repo_root=repo),
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

    result = search(
        SearchRequest(query="Find request validation", repo_root=repo),
        settings,
        client=client,
    )

    assert [citation.label() for citation in result.citations] == [
        "src/api/validation.py:45-55"
    ]


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
    result = search(
        SearchRequest(
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
        result = search(
            SearchRequest(query="RetryConfig", repo_root=tmp_path, citation=citation),
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
        result = search(
            SearchRequest(query="RetryConfig", repo_root=tmp_path),
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
        result = search(
            SearchRequest(query="RetryConfig", repo_root=tmp_path),
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
        result = search(
            SearchRequest(query="RetryConfig", repo_root=tmp_path),
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
            result = search(
                SearchRequest(query="RetryConfig", repo_root=tmp_path),
                settings,
                client=client,
            )
            assert result.citations == [Citation("config.py", 1, 1)]
            assert result.truncated
        else:
            with pytest.raises(SearchError, match="without evidence"):
                search(
                    SearchRequest(query="RetryConfig", repo_root=tmp_path),
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
        result = search(
            SearchRequest(query="RetryConfig", repo_root=tmp_path),
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
        result = search(
            SearchRequest(
                query="Find `RetryConfig` in src/config.py", repo_root=tmp_path
            ),
            settings,
            client=client,
        )
    finally:
        client.close()
    assert result.answer == NO_RESULT
    assert not result.citations

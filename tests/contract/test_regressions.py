"""Regressions for strict chat templates and bounded final selection."""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from flash_context.agent import search
from flash_context.citations import CitationResolver
from flash_context.config import Settings
from flash_context.llm import ChatClient
from flash_context.types import Diagnostic, SearchError, SearchRequest
from tests.helpers import _message_response, _multi_tool_response, _tool_response


@pytest.mark.parametrize("status", ["missing", "ambiguous", "incomplete"])
def test_preflight_uses_one_leading_system(tmp_path: Path, status: str) -> None:
    text = "def Target(): pass\n" if status == "ambiguous" else "# padding\n" * 20
    for name in ("a.py", "b.py"):
        (tmp_path / name).write_text(text)
    settings = Settings(
        base_url="http://test/v1",
        model="mock",
        max_scan_bytes=10 if status == "incomplete" else 1000,
    )

    def handle(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert [m["role"] for m in payload["messages"]] == ["system", "user"]
        assert f"scan for Target: {status}" in payload["messages"][0]["content"]
        return httpx.Response(200, json=_message_response("NO_CITATIONS_FOUND"))

    with_client = ChatClient(settings, transport=httpx.MockTransport(handle))
    try:
        result = search(
            SearchRequest("Target", tmp_path), settings, client=with_client
        )
    finally:
        with_client.close()
    assert result.answer == "NO_CITATIONS_FOUND"
    assert Diagnostic.SYMBOL_MISSING in result.warnings
    assert result.truncated is (status == "incomplete")


@pytest.mark.parametrize("ending", ["budget", "prose", "repeat", "ignored_tool"])
def test_selection_is_bounded_and_tool_free(tmp_path: Path, ending: str) -> None:
    (tmp_path / "a.py").write_text("def answer():\n    return 1\n")
    read = _tool_response("read", "read_file", {"path": "a.py"})
    replies = [read]
    if ending == "prose":
        replies.append(_message_response("The implementation is here."))
    elif ending == "repeat":
        replies.append(read)
    replies.append(read if ending == "ignored_tool" else _message_response("a.py:1"))
    seen: list[dict[str, Any]] = []
    settings = Settings(base_url="http://test/v1", model="mock", max_turns=len(replies))

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=replies[len(seen) - 1])

    client = ChatClient(settings, transport=httpx.MockTransport(handle))
    try:
        result = search(
            SearchRequest("How does it work?", tmp_path), settings, client=client
        )
    finally:
        client.close()
    assert result.turns_used == len(replies) == len(seen)
    assert {t["function"]["name"] for t in seen[0]["tools"]} == {
        "repo_grep",
        "repo_glob",
    }
    assert "tools" not in seen[-1] and "tool_choice" not in seen[-1]
    assert [m["role"] for m in seen[-1]["messages"]] == ["system", "user"]
    assert "1: def answer" in seen[-1]["messages"][1]["content"]
    assert bool(result.citations) is (ending != "ignored_tool")
    if ending == "ignored_tool":
        assert result.truncated


def test_shifted_reads_select_after_coverage_stalls(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def answer():\n" + "    pass\n" * 8)
    calls = [
        _tool_response("search", "repo_glob", {"pattern": "*.py"}),
        *(
            _tool_response(
                f"read_{number}",
                "read_file",
                {"path": "a.py", "start_line": start, "end_line": end},
            )
            for number, (start, end) in enumerate(
                [(1, 4), (4, 7), (3, 5), (5, 7), (2, 6)], start=1
            )
        ),
        _message_response("a.py:1"),
    ]
    seen: list[dict[str, Any]] = []
    settings = Settings(
        base_url="http://test/v1",
        model="mock",
        max_turns=10,
        traj_dir=tmp_path.parent / f"{tmp_path.name}-trajectory",
    )

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=calls[len(seen) - 1])

    client = ChatClient(settings, transport=httpx.MockTransport(handle))
    try:
        result = search(
            SearchRequest("How does the answer work?", tmp_path, max_turns=10),
            settings,
            client=client,
        )
    finally:
        client.close()
    assert result.turns_used == 7
    assert [c.label() for c in result.citations] == ["a.py:1-9"]
    assert all("tools" in request for request in seen[:-1])
    assert "tools" not in seen[-1]
    selection = seen[-1]["messages"][1]["content"]
    assert selection.count("4:     pass") == 1
    assert "tool_call_id" not in selection
    traj_dir = tmp_path.parent / f"{tmp_path.name}-trajectory"
    log = json.loads(next(traj_dir.glob("*.json")).read_text())
    assert (
        next(t for t in log["turns"] if t.get("phase") == "selection")[
            "selection_reason"
        ]
        == "stalled_reads"
    )


def test_fresh_sibling_prevents_premature_selection(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def answer():\n" + "    pass\n" * 8)
    replies = [
        _tool_response("search", "repo_glob", {"pattern": "*.py"}),
        _tool_response(
            "first", "read_file", {"path": "a.py", "start_line": 1, "end_line": 4}
        ),
        _multi_tool_response(
            [
                (
                    "old_1",
                    "read_file",
                    {"path": "a.py", "start_line": 2, "end_line": 3},
                ),
                (
                    "old_2",
                    "read_file",
                    {"path": "a.py", "start_line": 1, "end_line": 2},
                ),
                ("new", "read_file", {"path": "a.py", "start_line": 4, "end_line": 6}),
            ]
        ),
        _tool_response(
            "more", "read_file", {"path": "a.py", "start_line": 6, "end_line": 8}
        ),
        _message_response("a.py:1"),
    ]
    seen: list[dict[str, Any]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=replies[len(seen) - 1])

    settings = Settings(base_url="http://test/v1", model="mock", max_turns=10)
    client = ChatClient(settings, transport=httpx.MockTransport(handle))
    try:
        result = search(
            SearchRequest("How does the answer work?", tmp_path, max_turns=10),
            settings,
            client=client,
        )
    finally:
        client.close()
    assert result.turns_used == 5
    assert "tools" in seen[3]
    assert [c.label() for c in result.citations] == ["a.py:1-9"]


def test_token_limited_completion_selects_prior_read(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def answer():\n    return 1\n")
    replies = [
        _tool_response("search", "repo_glob", {"pattern": "*.py"}),
        _tool_response("read", "read_file", {"path": "a.py"}),
        {
            "choices": [
                {
                    "message": {"role": "assistant", "content": "unfinished"},
                    "finish_reason": "length",
                }
            ]
        },
        _message_response("a.py:1"),
    ]
    seen: list[dict[str, Any]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=replies[len(seen) - 1])

    settings = Settings(base_url="http://test/v1", model="mock", max_turns=6)
    client = ChatClient(settings, transport=httpx.MockTransport(handle))
    try:
        result = search(
            SearchRequest("How does the answer work?", tmp_path),
            settings,
            client=client,
        )
    finally:
        client.close()
    assert result.turns_used == 4
    assert [c.label() for c in result.citations] == ["a.py:1-2"]
    assert Diagnostic.TOKEN_LIMIT in result.warnings
    assert result.truncated
    assert "tools" not in seen[-1]


def test_endpoint_error_metadata_remains_private(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    settings = Settings(
        base_url="http://test/v1", model="mock", traj_dir=tmp_path / "logs"
    )

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="PRIVATE_ENDPOINT_BODY")

    client = ChatClient(settings, transport=httpx.MockTransport(handle))
    try:
        with pytest.raises(SearchError, match="ENDPOINT_BAD_RESPONSE"):
            search(SearchRequest("MissingSymbol", repo), settings, client=client)
    finally:
        client.close()
    text = next((tmp_path / "logs").glob("*.json")).read_text()
    data = json.loads(text)
    assert data["status_code"] == 500
    assert data["turns"][0]["message_roles"] == ["system", "user"]
    assert "PRIVATE_ENDPOINT_BODY" not in text and "MissingSymbol" not in text


def test_range_expansion_is_atomic_and_renders_all_units(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text(
        "@cache\ndef a():\n    return 1\n\ndef b():\n    return 2\n"
    )
    resolver = CitationResolver(tmp_path, Settings(), None)
    result = resolver.parse("a.py:1-6")
    assert result.render("Found a.py:1-6") == "Found a.py:1-3, a.py:5-6"
    limited = CitationResolver(tmp_path, Settings(max_total_citation_lines=3), None)
    result = limited.parse("a.py:1-6")
    assert not result.citations and result.feedback
    assert "Example" in result.feedback[0]
    exact = CitationResolver(tmp_path, Settings(), "b").parse("a.py:1-6")
    assert [c.label() for c in exact.citations] == ["a.py:5-6"]
    for anchor in ("a.py:6-1", "a.py:1-99", "../a.py:1-6"):
        assert not resolver.parse(anchor).citations


def test_httpx_timeout_range_and_interior() -> None:
    resolver = CitationResolver(Path("tests/fixtures/httpx_0_28_1"), Settings(), None)
    for anchor in ("httpx/_client.py:580-610", "httpx/_client.py:585-589"):
        result = resolver.parse(anchor)
        assert [c.label() for c in result.citations] == ["httpx/_client.py:584-591"]


@pytest.mark.parametrize(
    "scenario,exit_code", [("missing", 0), ("limited", 6), ("endpoint", 5)]
)
def test_missing_symbol_cli_exit_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    scenario: str,
    exit_code: int,
) -> None:
    from flash_context import cli
    from flash_context.types import SearchResult

    (tmp_path / "a.py").write_text("# padding\n" * 20)
    settings = Settings(
        base_url="http://test/v1",
        model="mock",
        max_scan_bytes=10 if scenario == "limited" else 1000,
    )

    def handle(request: httpx.Request) -> httpx.Response:
        if scenario == "endpoint":
            return httpx.Response(500, text="PRIVATE_BODY")
        return httpx.Response(200, json=_message_response("NO_CITATIONS_FOUND"))

    def load(**kwargs: object) -> Settings:
        return settings

    client = ChatClient(settings, transport=httpx.MockTransport(handle))

    def run(request: SearchRequest, settings: Settings) -> SearchResult:
        return search(request, settings, client=client)

    monkeypatch.setattr(cli, "load_settings", load)
    monkeypatch.setattr(cli, "search", run)
    try:
        assert (
            cli.main(
                [
                    "search",
                    "--repo",
                    str(tmp_path),
                    "--query",
                    "MissingSymbol",
                    "--format",
                    "json",
                ]
            )
            == exit_code
        )
    finally:
        client.close()
    output = capsys.readouterr()
    assert "PRIVATE_BODY" not in output.err
    if scenario == "endpoint":
        assert not output.out and "ENDPOINT_BAD_RESPONSE" in output.err
    else:
        assert json.loads(output.out)["answer"] == "NO_CITATIONS_FOUND"
        assert "query symbol not found in verified evidence" in output.err

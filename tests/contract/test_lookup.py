from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from flash_context.agent import search
from flash_context.citations import CitationResolver, Resolution
from flash_context.config import Settings
from flash_context.llm import ChatClient
from flash_context.queries import QueryIntent
from flash_context.types import (
    Diagnostic,
    RawLocation,
    SearchError,
    SearchRequest,
)
from tests.helpers import (
    _message_response,
    _mock_transport,
)


def test_exact_citation_fast_path_skips_endpoint_config(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "agent.py").write_text("line 1\nline 2\n", encoding="utf-8")
    settings = Settings()

    result = search(
        SearchRequest(query="Use agent.py:1-2", repo_root=repo),
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

    result = search(
        SearchRequest(
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

    result = search(
        SearchRequest(
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
        "def search():\n    pass\n",
        encoding="utf-8",
    )
    settings = Settings()

    result = search(
        SearchRequest(query="Find `search`", repo_root=repo),
        settings,
    )

    assert result.turns_used == 0
    assert result.answer == "src/agent.py:1"


def test_pathless_definition_in_markdown_does_not_fast_path(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "guide.md").write_text(
        "```python\ndef search():\n    pass\n```\n",
        encoding="utf-8",
    )
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

    result = search(
        SearchRequest(query="Find `SECRET` in .env", repo_root=repo),
        settings,
        client=client,
    )

    assert result.turns_used == 1
    assert result.answer == "NO_CITATIONS_FOUND"
    assert "SECRET=1" not in json.dumps(seen_payloads)


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
    result = search(
        SearchRequest(query=query, repo_root=tmp_path), Settings(max_read_lines=2)
    )
    assert result.turns_used == 0
    assert result.answer == f"{path}:1-2"
    assert result.raw_locations == [RawLocation(path, 1, 2, "one\ntwo\n")]
    assert result.truncated


@pytest.mark.parametrize("query", ["missing.py", "empty.py", ".env.local", "../out.py"])
def test_unusable_bare_path_retains_model_routing(tmp_path: Path, query: str) -> None:
    (tmp_path / "empty.py").touch()
    (tmp_path / ".env.local").write_text("SECRET")
    with pytest.raises(SearchError, match="CONFIG_MISSING_ENDPOINT") as error:
        search(SearchRequest(query=query, repo_root=tmp_path), Settings())
    assert "SECRET" not in str(error.value)


def test_unique_definition_ignores_reference_match_cap(tmp_path: Path) -> None:
    (tmp_path / "a_refs.py").write_text("ref = BaseTransport\n" * 20)
    (tmp_path / "z_base.py").write_text("class BaseTransport:\n    pass\n")
    result = search(
        SearchRequest(query="BaseTransport", repo_root=tmp_path), Settings()
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
    with pytest.raises(SearchError, match="CONFIG_MISSING_ENDPOINT"):
        search(
            SearchRequest(query="Target", repo_root=tmp_path),
            Settings(max_scan_bytes=30 if incomplete else 1000),
        )


def test_exact_documentation_path_stays_endpoint_free(tmp_path: Path) -> None:
    (tmp_path / "guide.md").write_text("Handler overview\n")
    result = search(SearchRequest(query="guide.md:1", repo_root=tmp_path), Settings())
    assert result.turns_used == 0
    assert result.answer == "guide.md:1"
    assert not result.warnings


@pytest.mark.parametrize(
    "query",
    [
        "httpx/_client.py#BaseClient._redirect_method",
        "`httpx/_client.py#_redirect_method`",
        "'httpx/_client.py#BaseClient._redirect_method'",
        '"httpx/_client.py#_redirect_method"',
    ],
)
def test_symbol_anchor_resolves_httpx_without_endpoint(query: str) -> None:
    root = Path("tests/fixtures/httpx_0_28_1").resolve()
    result = search(SearchRequest(query, root), Settings())
    assert result.turns_used == 0
    assert result.answer == "httpx/_client.py:494-515"
    precision = result.citations[0].precision
    assert precision is not None
    assert precision.boundary_kind == "definition"
    assert precision.symbol == "BaseClient._redirect_method"
    assert result.raw_locations[0].text == "".join(
        (root / "httpx/_client.py").read_text().splitlines(keepends=True)[493:515]
    )
    assert not result.truncated and not result.warnings


@pytest.mark.parametrize(
    "filename,source",
    [
        ("a.py", "def calculate():\n    return 42\n"),
        ("a.js", "export function calculate() { return 42; }\n"),
    ],
)
def test_root_symbol_anchor_uses_snapshot_and_snippet_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, filename: str, source: str
) -> None:
    path = tmp_path / filename
    path.write_text(source)
    parse = CitationResolver.parse

    def changed_after_parse(self: CitationResolver, content: str) -> Resolution:
        result = parse(self, content)
        path.write_text("changed = True\n")
        return result

    monkeypatch.setattr(CitationResolver, "parse", changed_after_parse)
    result = search(
        SearchRequest(f"{filename}#calculate", tmp_path), Settings(max_read_bytes=8)
    )
    assert result.turns_used == 0
    assert result.raw_locations[0].text == source[:8]
    assert result.truncated and Diagnostic.RAW_TRUNCATED in result.warnings
    assert path.read_text() == "changed = True\n"


@pytest.mark.parametrize(
    "filename,source,settings",
    [
        ("a.py", "def other(): pass\n", Settings()),
        (
            "a.py",
            "class A:\n    def f(self): pass\nclass B:\n    def f(self): pass\n",
            Settings(),
        ),
        ("a.txt", "def f(): pass\n", Settings()),
        ("a.py", "def f():\n    pass\n", Settings(max_citation_lines=1)),
        ("a.py", "def f(): pass\n", Settings(ignore=["a.py"])),
    ],
)
def test_unresolved_symbol_anchor_retains_model_routing(
    tmp_path: Path, filename: str, source: str, settings: Settings
) -> None:
    (tmp_path / filename).write_text(source)
    with pytest.raises(SearchError, match="CONFIG_MISSING_ENDPOINT"):
        search(SearchRequest(f"{filename}#f", tmp_path), settings)


@pytest.mark.parametrize("query", [".env#f", "../outside.py#f", "alias.py#f"])
def test_symbol_anchor_safety_does_not_leak_source(tmp_path: Path, query: str) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    private = "def f(): return 'PRIVATE_SOURCE'\n"
    (repo / ".env").write_text(private)
    (tmp_path / "outside.py").write_text(private)
    (repo / "alias.py").symlink_to(tmp_path / "outside.py")
    payloads: list[dict[str, object]] = []
    settings = Settings(base_url="http://test/v1", model="mock")
    client = ChatClient(
        settings,
        transport=_mock_transport(
            iter([_message_response("NO_CITATIONS_FOUND")]), payloads
        ),
    )
    try:
        result = search(SearchRequest(query, repo), settings, client=client)
    finally:
        client.close()
    assert result.turns_used == 1 and not result.citations
    assert "PRIVATE_SOURCE" not in json.dumps(payloads)
    assert "PRIVATE_SOURCE" not in json.dumps(result.to_dict())


def test_symbol_anchor_parser_limit_survives_model_fallback(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def f():\n    pass\n")
    settings = Settings(base_url="http://test/v1", model="mock", max_parse_bytes=4)
    client = ChatClient(
        settings,
        transport=_mock_transport(iter([_message_response("NO_CITATIONS_FOUND")])),
    )
    try:
        result = search(SearchRequest("a.py#f", tmp_path), settings, client=client)
    finally:
        client.close()
    assert result.turns_used == 1 and not result.citations
    assert result.truncated and Diagnostic.PARSER_INPUT_LIMIT in result.warnings


def test_anchor_fast_path_only_accepts_one_complete_query() -> None:
    for query in ("Explain a.py#f", "a.py#f a.py#g", "a.py#f trailing"):
        assert QueryIntent.parse(query).symbol_anchor is None

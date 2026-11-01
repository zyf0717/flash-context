from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from flash_context.agent import explore
from flash_context.config import Settings
from flash_context.llm import ChatClient
from flash_context.types import (
    ExploreRequest,
    ExplorerError,
    RawLocation,
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


def test_exact_documentation_path_stays_endpoint_free(tmp_path: Path) -> None:
    (tmp_path / "guide.md").write_text("Handler overview\n")
    result = explore(ExploreRequest(query="guide.md:1", repo_root=tmp_path), Settings())
    assert result.turns_used == 0
    assert result.answer == "guide.md:1"
    assert not result.warnings

from pathlib import Path

import pytest

import flash_context.citations as boundaries
from flash_context.agent import explore
from flash_context.citations import CitationResolver
from flash_context.config import Settings
from flash_context.execution import _model_observation_payload
from flash_context.llm import ChatClient
from flash_context.types import Diagnostic, ExploreRequest, ToolObservation
from scripts.citation_benchmark import cases
from tests.helpers import _message_response, _mock_transport, _tool_response


@pytest.mark.parametrize("prose", [False, True])
def test_repair_feedback_does_not_survive_tool_only_turn(
    tmp_path: Path, prose: bool
) -> None:
    (tmp_path / "a.py").write_text("def f():\n    return 1\n")
    replies = iter(
        [
            _message_response("a.py:1-999"),
            _tool_response("read", "read_file", {"path": "a.py"}),
            _message_response("Found a.py#f"),
        ]
    )
    settings = Settings(base_url="http://test/v1", model="mock", max_turns=3)
    client = ChatClient(settings, transport=_mock_transport(replies))
    try:
        result = explore(
            ExploreRequest("Where is behavior?", tmp_path, citation=not prose),
            settings,
            client=client,
        )
    finally:
        client.close()
    assert result.answer == ("Found a.py:1-2" if prose else "a.py:1-2")
    assert not result.truncated
    assert Diagnostic.PRECISION_LIMIT not in result.warnings


@pytest.mark.parametrize("anchors", ["a.py:1\na.py:2", "a.py#C\na.py#C.f"])
def test_overlapping_anchors_keep_their_resolved_identity(
    tmp_path: Path, anchors: str
) -> None:
    (tmp_path / "a.py").write_text(
        "class C:\n    def f(self):\n        return 1\n"
        "    def g(self):\n        return 2\n"
    )
    result = CitationResolver(tmp_path, Settings(), None).parse(anchors)
    assert result.render(anchors) == "a.py:1-5\na.py:2-3"


def test_unicode_separators_are_not_source_lines(tmp_path: Path) -> None:
    text = 'a="x\u0085y\u2028z"\r\nz=1\r\n'
    (tmp_path / "a.py").write_bytes(text.encode())
    observation = ToolObservation(path="a.py", line_range="1-2", content=text)
    payload = _model_observation_payload(observation)
    assert payload["content"] == '1: a="x\u0085y\u2028z"\n2: z=1\n'
    resolver = CitationResolver(tmp_path, Settings(), None)
    result = resolver.parse("a.py:2")
    assert result.citations[0].label() == "a.py:2"
    assert resolver.snippet(result.citations[0]).text == "z=1\r\n"


def test_snippets_use_the_verified_source_snapshot(tmp_path: Path) -> None:
    path = tmp_path / "a.py"
    path.write_text("def f():\n    return 1\n")
    resolver = CitationResolver(tmp_path, Settings(), None)
    result = resolver.parse("a.py#f")
    path.write_text("unrelated = 2\n")
    assert resolver.snippet(result.citations[0]).text == "def f():\n    return 1\n"


@pytest.mark.parametrize(
    "suffix,text,cap,status",
    [
        ("txt", "one\ntwo\nthree\n", 100, "unsupported"),
        ("py", "def broken(:\n    pass\n", 100, "invalid"),
        ("py", "def f():\n    pass\n", 10, "limited"),
        ("py", "def f():\n    pass\n", 100, "parsed"),
    ],
)
def test_parser_outcomes_are_explicit(
    tmp_path: Path, suffix: str, text: str, cap: int, status: str
) -> None:
    path = f"a.{suffix}"
    (tmp_path / path).write_text(text)
    resolver = CitationResolver(tmp_path, Settings(max_parse_bytes=cap), None)
    result = resolver.parse(f"{path}:1")
    assert resolver.sources[path].status == status
    assert (Diagnostic.PARSER_INPUT_LIMIT in result.warnings) == (status == "limited")
    assert result.citations


def test_parser_deadline_and_cumulative_budget_are_diagnostic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("a.py", "b.py"):
        (tmp_path / name).write_text("def f(): pass\n")

    def timeout(*args: object, **kwargs: object) -> None:
        raise ValueError("native parser timeout")

    monkeypatch.setattr(boundaries, "Parser", timeout)
    resolver = CitationResolver(tmp_path, Settings(max_scan_bytes=14), None)
    assert Diagnostic.PARSER_TIMEOUT in resolver.parse("a.py:1").warnings
    assert resolver.sources["a.py"].status == "timeout"
    limited = resolver.parse("b.py:1")
    assert Diagnostic.READ_LIMIT in limited.warnings
    assert not limited.citations


def test_explicit_no_result_does_not_restore_matching_reads(tmp_path: Path) -> None:
    (tmp_path / "a.js").write_text("const MissingPythonName = 1;\n")
    settings = Settings(base_url="http://test/v1", model="mock")
    replies = iter(
        [
            _tool_response("read", "read_file", {"path": "a.js"}),
            _message_response("NO_CITATIONS_FOUND"),
        ]
    )
    client = ChatClient(settings, transport=_mock_transport(replies))
    try:
        result = explore(
            ExploreRequest("Find `MissingPythonName`", tmp_path),
            settings,
            client=client,
        )
    finally:
        client.close()
    assert not result.citations
    assert result.answer == "NO_CITATIONS_FOUND"


@pytest.mark.parametrize("case", cases(), ids=lambda c: c["name"])
def test_resolver_matches_independent_golden_ranges(case: dict[str, object]) -> None:
    import hashlib
    from typing import Any, cast

    golden = cast(dict[str, Any], case)
    root = Path(golden["root"])
    assert (
        hashlib.sha256((root / golden["path"]).read_bytes()).hexdigest()
        == golden["sha256"]
    )
    resolver = CitationResolver(root, Settings(), None)
    result = resolver.parse(
        "\n".join(f"{golden['path']}#{r['symbol']}" for r in golden["expected"])
    )
    assert not result.feedback
    assert [(c.start_line, c.end_line) for c in result.citations] == [
        (r["start_line"], r["end_line"]) for r in golden["expected"]
    ]


def test_snippet_cap_inside_utf8_keeps_valid_bounds(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("α\n")
    resolver = CitationResolver(tmp_path, Settings(max_read_bytes=1), None)
    citation = resolver.parse("a.txt:1").citations[0]
    raw = resolver.snippet(citation)
    assert (raw.start_line, raw.end_line, raw.text, raw.truncated) == (1, 1, "", True)

import os
import socket
from pathlib import Path

import httpx
import pytest

from flash_context.agent import explore
from flash_context.citations import CitationResolver
from flash_context.config import Settings
from flash_context.llm import ChatClient
from flash_context.types import Citation, ExploreRequest, ExplorerError

SAMPLES = {
    "py": "def sample():\n    return 1\n",
    "js": "export const sample = () => 1;",
    "ts": "export function sample(): number { return 1; }",
    "tsx": "export const sample = () => <div/>;",
    "go": "package main\nfunc sample() int { return 1 }",
    "rs": "fn sample() -> i32 { 1 }",
    "java": "class Example { int sample() { return 1; } }",
    "c": "int sample(void) { return 1; }",
    "cpp": "class Example { public: int sample() { return 1; } };",
    "cs": "class Example { int sample() { return 1; } }",
    "rb": "def sample\n  1\nend",
    "php": "<?php function sample() { return 1; }",
    "sh": "sample() { echo 1; }",
    "lua": "function sample() return 1 end",
    "kt": "fun sample(): Int { return 1 }",
    "swift": "func sample() -> Int { return 1 }",
}


@pytest.mark.parametrize("extension,source", SAMPLES.items())
def test_major_language_symbols(
    tmp_path: Path, extension: str, source: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        socket, "socket", lambda *a, **kw: pytest.fail("parser network access")
    )
    path = f"example.{extension}"
    (tmp_path / path).write_text(source)
    resolver = CitationResolver(tmp_path, Settings(), None)
    citation = _citation(resolver, path, symbol="sample")
    assert citation is not None
    assert citation.precision is not None
    assert citation.precision.boundary_kind == "definition"


def test_httpx_redirects() -> None:
    root = Path("tests/fixtures/httpx_0_28_1").resolve()
    resolver = CitationResolver(root, Settings(), None)
    symbols = [
        "BaseClient._build_redirect_request",
        "BaseClient._redirect_method",
        "BaseClient._redirect_url",
        "BaseClient._redirect_headers",
        "BaseClient._redirect_stream",
        "Client._send_handling_redirects",
    ]
    citations = resolver.parse(
        "\n".join("httpx/_client.py#" + s for s in symbols)
    ).citations
    assert len(citations) == 6
    assert sum(c.precision.range_lines for c in citations if c.precision) == 140
    source = resolver.source("httpx/_client.py")
    assert source is not None and source.regions is not None
    assert (
        sum(
            r.kind == "definition" and r.start >= 470 and r.end <= 1000
            for r in source.regions
        )
        == 15
    )
    assert resolver.parse("httpx/_client.py:470-1000").citations == []


def test_large_definition_line_and_header(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def large():\n" + "    x = 1\n" * 130)
    resolver = CitationResolver(tmp_path, Settings(), None)
    assert _citation(resolver, "a.py", symbol="large") is None
    assert _citation(resolver, "a.py", line=70).label() == "a.py:70"  # type: ignore[union-attr]
    assert _citation(resolver, "a.py", line=1).end_line == 1  # type: ignore[union-attr]


def test_ambiguity_and_adjacent_definitions(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text(
        "class A:\n    def f(self): pass\nclass B:\n    def f(self): pass\n"
    )
    resolver = CitationResolver(tmp_path, Settings(), None)
    assert _citation(resolver, "a.py", symbol="f") is None
    assert len(resolver.parse("a.py#A.f\na.py#B.f").citations) == 2


@pytest.mark.parametrize("path", ["../secret.py", ".env", "escape.py"])
def test_parser_safety(tmp_path: Path, path: str) -> None:
    secret = tmp_path.parent / "secret.py"
    secret.write_text("def secret(): pass\n")
    (tmp_path / ".env").write_text("SECRET=1")
    (tmp_path / "escape.py").symlink_to(secret)
    resolver = CitationResolver(tmp_path, Settings(), None)
    assert _citation(resolver, path, symbol="secret") is None
    assert "SECRET" not in str(resolver.parse(path + "#secret").feedback)


def test_budgets_and_deduplication(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def a():\n    pass\ndef b():\n    pass\n")
    resolver = CitationResolver(tmp_path, Settings(max_total_citation_lines=2), None)
    resolution = resolver.parse("a.py#a\na.py#a\na.py#b")
    assert len(resolution.citations) == 1
    assert resolution.feedback
    limited = CitationResolver(tmp_path, Settings(max_parse_bytes=4), None)
    assert _citation(limited, "a.py", symbol="a") is None


def test_range_repair_and_no_fallback_bypass(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def a():\n    return 1\n")
    payloads = []
    responses = iter(["a.py:1-200", "a.py#a"])

    def handle(request: httpx.Request) -> httpx.Response:
        payloads.append(request.content)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": next(responses)}}]}
        )

    settings = Settings(base_url="http://test/v1", model="mock")
    client = ChatClient(settings, transport=httpx.MockTransport(handle))
    try:
        result = explore(
            ExploreRequest("Where is the behavior?", tmp_path), settings, client=client
        )
    finally:
        client.close()
    assert result.answer == "a.py:1-2"
    assert result.turns_used == 2
    assert b"Model ranges are unsupported" in payloads[-1]


@pytest.mark.parametrize(
    "name,section",
    [
        ("max_citation_lines", "explorer"),
        ("max_total_citation_lines", "explorer"),
        ("max_parse_bytes", "tools"),
    ],
)
def test_precision_configuration_precedence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str, section: str
) -> None:
    from flash_context import config

    monkeypatch.setattr(config, "_project_root", lambda: tmp_path)
    (tmp_path / "config.yaml").write_text(f"{section}:\n  {name}: 15\n")
    for key in list(os.environ):
        if key.startswith("FLASH_CONTEXT_"):
            monkeypatch.delenv(key)
    assert getattr(config.load_settings(), name) == 15
    env = "FLASH_CONTEXT_" + name.upper()
    monkeypatch.setenv(env, "20")
    assert getattr(config.load_settings(), name) == 20
    overrides = config.SettingsOverrides()
    object.__setattr__(overrides, name, 25)
    assert getattr(config.load_settings(overrides=overrides), name) == 25
    monkeypatch.setenv(env, "0")
    with pytest.raises(ExplorerError, match="must be positive"):
        config.load_settings()


@pytest.mark.parametrize("citation_mode", [True, False])
def test_rejected_range_at_turn_limit_is_empty(
    tmp_path: Path, citation_mode: bool
) -> None:
    (tmp_path / "a.py").write_text("def a(): pass\n")
    settings = Settings(base_url="http://test/v1", model="mock", max_turns=1)
    client = ChatClient(
        settings,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"choices": [{"message": {"content": "a.py:1-1000"}}]}
            )
        ),
    )
    try:
        result = explore(
            ExploreRequest("Where is behavior?", tmp_path, citation=citation_mode),
            settings,
            client=client,
        )
    finally:
        client.close()
    assert result.answer == "NO_CITATIONS_FOUND"
    assert result.citations == []
    assert result.truncated


def test_decorators_crlf_and_exact_tokens(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_bytes(
        b'@cache\r\ndef f():\r\n    return "\xc2\x85value"\r\n'
    )
    resolver = CitationResolver(tmp_path, Settings(), "f")
    citation = _citation(resolver, "a.py", symbol="f")
    assert citation is not None and citation.label() == "a.py:1-3"
    assert citation.precision is not None
    assert citation.precision.query_token_in_range is True
    wrong = CitationResolver(tmp_path, Settings(), "F")
    assert _citation(wrong, "a.py", symbol="f") is None
    assert resolver.parse("/a.py#f").citations == []


def test_prose_uses_resolved_labels(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def a():\n    return 1\n")
    settings = Settings(base_url="http://test/v1", model="mock")
    client = ChatClient(
        settings,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": (
                                    "The implementation is here.\n"
                                    "<final_answer>\na.py#a\n</final_answer>"
                                )
                            }
                        }
                    ]
                },
            )
        ),
    )
    try:
        result = explore(
            ExploreRequest("Where is behavior?", tmp_path, citation=False),
            settings,
            client=client,
        )
    finally:
        client.close()
    assert result.answer == "The implementation is here.\n\na.py:1-2"


def test_impl_scopes(tmp_path: Path) -> None:
    (tmp_path / "a.rs").write_text(
        "struct A;\nimpl A { fn f() {} }\nstruct B;\nimpl B { fn f() {} }\n"
    )
    resolver = CitationResolver(tmp_path, Settings(), None)
    assert _citation(resolver, "a.rs", symbol="f") is None
    assert _citation(resolver, "a.rs", symbol="A.f") is not None


def _citation(
    resolver: CitationResolver,
    path: str,
    *,
    symbol: str | None = None,
    line: int | None = None,
) -> Citation | None:
    result = resolver.parse(f"{path}#{symbol}" if symbol else f"{path}:{line}")
    return result.citations[0] if result.citations else None

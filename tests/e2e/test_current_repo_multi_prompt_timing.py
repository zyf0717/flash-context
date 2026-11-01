from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Literal

import pytest

from flash_context.agent import NO_CITATIONS_FOUND, explore, format_text_result
from flash_context.config import SettingsOverrides, load_settings
from flash_context.types import Citation, ExploreRequest, ExplorerError

pytestmark = pytest.mark.e2e

RUN_E2E_ENV = "FLASH_CONTEXT_RUN_E2E"
E2E_IGNORE = [".flash-context/**"]


@dataclass(frozen=True, slots=True)
class PromptCase:
    name: str
    query: str
    expected_path: str
    expected_text: str


@dataclass(frozen=True, slots=True)
class MixedPromptCase:
    name: str
    query: str
    expected_mode: Literal["fast", "model_loop"]
    expected_text: str | None = None
    expected_path: str | None = None
    allow_no_citations: bool = False


PROMPT_CASES = (
    PromptCase(
        name="config observation cap",
        query=(
            "In src/flash_context/config.py, find where the Settings model defines "
            "`max_observation_chars`. Return citations only."
        ),
        expected_path="src/flash_context/config.py",
        expected_text="max_observation_chars",
    ),
    PromptCase(
        name="llm completion limits",
        query=(
            "In src/flash_context/llm.py, find where chat completion payloads set "
            "`max_tokens`. Return citations only."
        ),
        expected_path="src/flash_context/llm.py",
        expected_text="max_tokens",
    ),
    PromptCase(
        name="path safety class",
        query=(
            "In src/flash_context/tools/safety.py, find the definition of "
            "`PathSafety`. Return citations only."
        ),
        expected_path="src/flash_context/tools/safety.py",
        expected_text="class PathSafety",
    ),
    PromptCase(
        name="read tool entrypoint",
        query=(
            "In src/flash_context/tools/read.py, find the `read_file` function "
            "definition. Return citations only."
        ),
        expected_path="src/flash_context/tools/read.py",
        expected_text="def read_file",
    ),
    PromptCase(
        name="mcp handler",
        query=(
            "In src/flash_context/mcp_server.py, find the "
            "`explore_repository_handler` function definition. Return citations only."
        ),
        expected_path="src/flash_context/mcp_server.py",
        expected_text="def explore_repository_handler",
    ),
)

FAST_PATH_CASES = (
    PromptCase(
        name="fast path explicit citation",
        query="Return src/flash_context/agent.py:1175-1183 citations only.",
        expected_path="src/flash_context/agent.py",
        expected_text="def _execute_tool_calls_parallel",
    ),
    PromptCase(
        name="fast path unique symbol",
        query="Find `_cap_text`.",
        expected_path="src/flash_context/tools/grep.py",
        expected_text="def _cap_text",
    ),
)

MIXED_EDGE_CASES = (
    MixedPromptCase(
        name="explicit citation fast path",
        query="Return src/flash_context/types.py:46-64 citations only.",
        expected_mode="fast",
        expected_path="src/flash_context/types.py",
        expected_text="class Citation",
    ),
    MixedPromptCase(
        name="explicit file quoted text fast path",
        query='Find "tool_choice" in src/flash_context/llm.py. Return citations only.',
        expected_mode="fast",
        expected_path="src/flash_context/llm.py",
        expected_text="tool_choice",
    ),
    MixedPromptCase(
        name="explicit file assignment fast path",
        query=(
            "In src/flash_context/tools/grep.py, find `MAX_HIT_TEXT`. "
            "Return citations only."
        ),
        expected_mode="fast",
        expected_path="src/flash_context/tools/grep.py",
        expected_text="MAX_HIT_TEXT = 240",
    ),
    MixedPromptCase(
        name="pathless unique function fast path",
        query="Find `_chat_completions_url`. Return citations only.",
        expected_mode="fast",
        expected_path="src/flash_context/llm.py",
        expected_text="def _chat_completions_url",
    ),
    MixedPromptCase(
        name="pathless unique class fast path",
        query="Find `TrajectoryRecorder`. Return citations only.",
        expected_mode="fast",
        expected_path="src/flash_context/logging.py",
        expected_text="class TrajectoryRecorder",
    ),
    MixedPromptCase(
        name="semantic symbol model loop",
        query=(
            "How does `_execute_tool_calls_parallel` preserve observation order? "
            "Return citations only."
        ),
        expected_mode="model_loop",
        expected_path="src/flash_context/agent.py",
        expected_text="def _execute_tool_calls_parallel",
        allow_no_citations=True,
    ),
    MixedPromptCase(
        name="pathless assignment model loop",
        query="Find `FLASH_CONTEXT_MAX_PARALLEL_TOOLS`. Return citations only.",
        expected_mode="model_loop",
    ),
    MixedPromptCase(
        name="ambiguous definition model loop",
        query="Find `_mock_transport`. Return citations only.",
        expected_mode="model_loop",
    ),
    MixedPromptCase(
        name="missing explicit file target model loop",
        query=(
            "In src/flash_context/agent.py, find `definitely_missing_symbol`. "
            "Return citations only."
        ),
        expected_mode="model_loop",
        allow_no_citations=True,
    ),
    MixedPromptCase(
        name="invalid explicit citation model loop",
        query="Return src/flash_context/agent.py:999999-1000000 citations only.",
        expected_mode="model_loop",
        allow_no_citations=True,
    ),
)


def test_current_repo_multi_prompt_timing_e2e() -> None:
    if os.environ.get(RUN_E2E_ENV) != "1":
        pytest.skip(f"set {RUN_E2E_ENV}=1 to run endpoint-backed e2e tests")

    repo_root = Path(__file__).resolve().parents[2]
    settings = load_settings(
        repo_root=repo_root,
        overrides=SettingsOverrides(max_turns=6, traj_dir=None, ignore=E2E_IGNORE),
    )
    try:
        settings.require_endpoint()
    except ExplorerError as exc:
        pytest.skip(f"Model endpoint config missing: {exc.code}")

    timings: list[tuple[PromptCase, float, str, int, list[str]]] = []
    total_start = perf_counter()
    for case in PROMPT_CASES:
        started = perf_counter()
        result = explore(
            ExploreRequest(
                query=case.query,
                repo_root=repo_root,
                max_turns=settings.max_turns,
                citation=True,
            ),
            settings,
        )
        elapsed = perf_counter() - started
        rendered = format_text_result(result, citation=True)
        timings.append(
            (case, elapsed, rendered, result.turns_used, list(result.warnings))
        )

        assert result.answer != NO_CITATIONS_FOUND, case.name
        assert result.citations, case.name
        assert rendered == result.answer
        assert result.answer == "\n".join(
            citation.label() for citation in result.citations
        )
        assert any(
            citation.path == case.expected_path for citation in result.citations
        ), case.name
        cited_text = _read_cited_text(
            repo_root=repo_root,
            citations=result.citations,
            expected_path=case.expected_path,
        )
        assert case.expected_text in cited_text, case.name

    total_elapsed = perf_counter() - total_start
    _print_timing_summary(timings, total_elapsed)


def test_current_repo_exact_fast_path_timing_e2e() -> None:
    if os.environ.get(RUN_E2E_ENV) != "1":
        pytest.skip(f"set {RUN_E2E_ENV}=1 to run endpoint-backed e2e tests")

    repo_root = Path(__file__).resolve().parents[2]
    settings = load_settings(
        repo_root=repo_root,
        overrides=SettingsOverrides(max_turns=6, traj_dir=None, ignore=E2E_IGNORE),
    )

    timings: list[tuple[PromptCase, float, str, int, list[str]]] = []
    total_start = perf_counter()
    for case in FAST_PATH_CASES:
        started = perf_counter()
        result = explore(
            ExploreRequest(
                query=case.query,
                repo_root=repo_root,
                max_turns=settings.max_turns,
                citation=True,
            ),
            settings,
        )
        elapsed = perf_counter() - started
        rendered = format_text_result(result, citation=True)
        timings.append(
            (case, elapsed, rendered, result.turns_used, list(result.warnings))
        )

        assert result.turns_used == 0, case.name
        assert result.answer != NO_CITATIONS_FOUND, case.name
        assert rendered == result.answer
        assert any(
            citation.path == case.expected_path for citation in result.citations
        ), case.name
        cited_text = _read_cited_text(
            repo_root=repo_root,
            citations=result.citations,
            expected_path=case.expected_path,
        )
        assert case.expected_text in cited_text, case.name

    total_elapsed = perf_counter() - total_start
    _print_timing_summary(timings, total_elapsed)


def test_current_repo_mixed_edge_case_timing_e2e() -> None:
    if os.environ.get(RUN_E2E_ENV) != "1":
        pytest.skip(f"set {RUN_E2E_ENV}=1 to run endpoint-backed e2e tests")

    repo_root = Path(__file__).resolve().parents[2]
    settings = load_settings(
        repo_root=repo_root,
        overrides=SettingsOverrides(max_turns=3, traj_dir=None, ignore=E2E_IGNORE),
    )
    try:
        settings.require_endpoint()
    except ExplorerError as exc:
        pytest.skip(f"Model endpoint config missing: {exc.code}")

    timings: list[tuple[MixedPromptCase, float, str, int, list[str]]] = []
    total_start = perf_counter()
    for case in MIXED_EDGE_CASES:
        started = perf_counter()
        result = explore(
            ExploreRequest(
                query=case.query,
                repo_root=repo_root,
                max_turns=settings.max_turns,
                citation=True,
            ),
            settings,
        )
        elapsed = perf_counter() - started
        rendered = format_text_result(result, citation=True)
        timings.append(
            (case, elapsed, rendered, result.turns_used, list(result.warnings))
        )

        assert rendered == result.answer, case.name
        if case.expected_mode == "fast":
            assert result.turns_used == 0, case.name
            assert result.citations, case.name
        else:
            assert result.turns_used > 0, case.name

        if case.allow_no_citations and not result.citations:
            assert result.answer == NO_CITATIONS_FOUND, case.name
            continue
        assert result.citations, case.name

        if case.expected_path is not None:
            assert any(
                citation.path == case.expected_path for citation in result.citations
            ), case.name
        if case.expected_text is not None:
            cited_text = _read_cited_text(
                repo_root=repo_root,
                citations=result.citations,
                expected_path=case.expected_path,
            )
            assert case.expected_text in cited_text, case.name

    total_elapsed = perf_counter() - total_start
    _print_mixed_timing_summary(timings, total_elapsed)


def _read_cited_text(
    *,
    repo_root: Path,
    citations: list[Citation],
    expected_path: str | None,
) -> str:
    chunks: list[str] = []
    for citation in citations:
        if expected_path is not None and citation.path != expected_path:
            continue
        if citation.start_line is None or citation.end_line is None:
            continue
        lines = (repo_root / citation.path).read_text(encoding="utf-8").splitlines()
        chunks.append("\n".join(lines[citation.start_line - 1 : citation.end_line]))
    return "\n".join(chunks)


def _print_timing_summary(
    timings: list[tuple[PromptCase, float, str, int, list[str]]],
    total_elapsed: float,
) -> None:
    print("\ncurrent-repo multi-prompt e2e timings:")
    for case, elapsed, rendered, turns_used, warnings in timings:
        warning_text = ", ".join(warnings) if warnings else "-"
        print(
            f"- {case.name}: {elapsed:.2f}s, turns={turns_used}, "
            f"citations={rendered}, warnings={warning_text}"
        )
    print(f"total: {total_elapsed:.2f}s")


def _print_mixed_timing_summary(
    timings: list[tuple[MixedPromptCase, float, str, int, list[str]]],
    total_elapsed: float,
) -> None:
    print("\ncurrent-repo mixed edge-case e2e timings:")
    for case, elapsed, rendered, turns_used, warnings in timings:
        warning_text = ", ".join(warnings) if warnings else "-"
        print(
            f"- {case.name} [{case.expected_mode}]: {elapsed:.2f}s, "
            f"turns={turns_used}, citations={rendered}, warnings={warning_text}"
        )
    print(f"total: {total_elapsed:.2f}s")

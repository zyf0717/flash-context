from __future__ import annotations

import os
from pathlib import Path

import pytest

from flash_context.agent import NO_CITATIONS_FOUND, explore, format_text_result
from flash_context.config import SettingsOverrides, load_settings
from flash_context.types import ExploreRequest, ExplorerError

pytestmark = pytest.mark.e2e

RUN_E2E_ENV = "FLASH_CONTEXT_RUN_E2E"
QUERY = (
    "In src/flash_context/agent.py, find the definition of `EvidenceState`. "
    "Return citations only."
)


def test_current_repo_e2e_returns_controller_validated_citation() -> None:
    if os.environ.get(RUN_E2E_ENV) != "1":
        pytest.skip(f"set {RUN_E2E_ENV}=1 to run endpoint-backed e2e tests")

    repo_root = Path(__file__).resolve().parents[2]
    settings = load_settings(
        repo_root=repo_root,
        overrides=SettingsOverrides(max_turns=6, traj_dir=None),
    )
    try:
        settings.require_endpoint()
    except ExplorerError as exc:
        pytest.skip(f"FastContext endpoint config missing: {exc.code}")

    result = explore(
        ExploreRequest(
            query=QUERY,
            repo_root=repo_root,
            max_turns=settings.max_turns,
            citation=True,
        ),
        settings,
    )

    assert result.answer != NO_CITATIONS_FOUND
    assert result.citations
    assert format_text_result(result, citation=True) == result.answer
    assert result.answer == "\n".join(
        citation.label() for citation in result.citations
    )
    assert any(
        citation.path == "src/flash_context/agent.py" for citation in result.citations
    )

    for citation in result.citations:
        assert not Path(citation.path).is_absolute()
        assert ".." not in Path(citation.path).parts
        assert (repo_root / citation.path).is_file()
        assert citation.start_line is not None
        assert citation.end_line is not None
        assert citation.start_line > 0
        assert citation.end_line >= citation.start_line

    cited_text = "\n".join(
        _read_cited_lines(
            repo_root / citation.path,
            citation.start_line,
            citation.end_line,
        )
        for citation in result.citations
        if citation.start_line is not None and citation.end_line is not None
    )
    assert "EvidenceState" in cited_text


def _read_cited_lines(path: Path, start_line: int, end_line: int) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    return "\n".join(lines[start_line - 1 : end_line])

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from flash_context import cli
from flash_context import config as config_module
from flash_context.config import Settings
from flash_context.llm import ChatClient
from flash_context.types import Citation, ExploreRequest, ExploreResult, RawLocation


@pytest.fixture(autouse=True)
def _isolated_config_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in list(os.environ):
        if key.startswith("FLASH_CONTEXT_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(
        config_module,
        "_project_root",
        lambda: tmp_path,
    )
    monkeypatch.chdir(tmp_path)


def test_cli_text_output_is_citation_first(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    def fake_explore(request: ExploreRequest, settings: Settings) -> ExploreResult:
        assert request.query == "Find validation"
        assert settings.max_turns == 6
        return ExploreResult(
            query=request.query,
            repo_root=str(repo),
            answer="src/api/validation.py:1-2\nValidation entrypoint.",
            citations=[Citation("src/api/validation.py", 1, 2)],
            turns_used=1,
        )

    monkeypatch.setattr(cli, "explore", fake_explore)

    code = cli.main(["explore", "--query", "Find validation", "--repo", str(repo)])

    assert code == 0
    assert capsys.readouterr().out.splitlines()[0] == "src/api/validation.py:1-2"


def test_cli_json_output_shape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    def fake_explore(request: ExploreRequest, settings: Settings) -> ExploreResult:
        return ExploreResult(
            query=request.query,
            repo_root=str(repo),
            answer="src/api/validation.py:1",
            citations=[Citation("src/api/validation.py", 1, 1)],
            raw_locations=[
                RawLocation("src/api/validation.py", 1, 1, "def validate():\n")
            ],
            turns_used=1,
        )

    monkeypatch.setattr(cli, "explore", fake_explore)

    code = cli.main(
        [
            "explore",
            "--query",
            "Find validation",
            "--repo",
            str(repo),
            "--format",
            "json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["query"] == "Find validation"
    assert payload["citations"][0]["path"] == "src/api/validation.py"
    assert payload["raw_locations"] == [
        {
            "path": "src/api/validation.py",
            "start_line": 1,
            "end_line": 1,
            "text": "def validate():\n",
            "truncated": False,
        }
    ]


def test_cli_missing_endpoint_is_configuration_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for key in ("FLASH_CONTEXT_BASE_URL", "FLASH_CONTEXT_MODEL"):
        monkeypatch.delenv(key, raising=False)
    repo = tmp_path / "repo"
    repo.mkdir()

    code = cli.main(["explore", "--query", "Find validation", "--repo", str(repo)])

    captured = capsys.readouterr()
    assert code == 3
    assert "CONFIG_MISSING_ENDPOINT" in captured.err


def test_cli_uses_project_root_config_and_dotenv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (tmp_path / "config.yaml").write_text(
        """
model:
  base_url: "http://yaml/v1"
  model: "yaml-model"
""",
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text(
        "FLASH_CONTEXT_BASE_URL=http://dotenv/v1\n",
        encoding="utf-8",
    )

    def fake_explore(request: ExploreRequest, settings: Settings) -> ExploreResult:
        assert settings.base_url == "http://dotenv/v1"
        assert settings.model == "yaml-model"
        return ExploreResult(
            query=request.query,
            repo_root=str(repo),
            answer="answer.py:1",
            citations=[Citation("answer.py", 1, 1)],
            turns_used=1,
        )

    monkeypatch.setattr(cli, "explore", fake_explore)

    code = cli.main(
        [
            "explore",
            "--query",
            "Find answer",
            "--repo",
            str(repo),
        ]
    )

    assert code == 0
    assert capsys.readouterr().out.strip() == "answer.py:1"


def test_cli_rejects_config_option() -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.main(
            [
                "explore",
                "--query",
                "Find answer",
                "--repo",
                ".",
                "--config",
                "external.yaml",
            ]
        )

    assert exc_info.value.code == 2


def test_cli_exact_fast_path_text_without_endpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for key in ("FLASH_CONTEXT_BASE_URL", "FLASH_CONTEXT_MODEL"):
        monkeypatch.delenv(key, raising=False)
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "agent.py").write_text("def explore():\n    pass\n", encoding="utf-8")

    code = cli.main(
        [
            "explore",
            "--query",
            "Find `explore`",
            "--repo",
            str(repo),
        ]
    )

    assert code == 0
    assert capsys.readouterr().out.strip() == "agent.py:1"


def test_cli_exact_fast_path_json_reports_zero_turns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for key in ("FLASH_CONTEXT_BASE_URL", "FLASH_CONTEXT_MODEL"):
        monkeypatch.delenv(key, raising=False)
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "agent.py").write_text("def explore():\n    pass\n", encoding="utf-8")

    code = cli.main(
        [
            "explore",
            "--query",
            "Find `explore`",
            "--repo",
            str(repo),
            "--format",
            "json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["answer"] == "agent.py:1"
    assert payload["turns_used"] == 0
    assert payload["citations"] == [
        {"path": "agent.py", "start_line": 1, "end_line": 1}
    ]


@pytest.mark.parametrize("output_format", ["text", "json"])
@pytest.mark.parametrize(
    ("max_entries", "cited", "expected_code"),
    [(1, False, 6), (1, True, 0), (100, False, 0)],
)
def test_cli_reports_scan_exhaustion_without_losing_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    output_format: str,
    max_entries: int,
    cited: bool,
    expected_code: int,
) -> None:
    from flash_context.agent import explore

    (tmp_path / "a.py").write_text("answer\n")
    (tmp_path / "b.py").write_text("other\n")
    settings = Settings(
        base_url="http://test/v1", model="mock", max_scan_entries=max_entries
    )
    response = {
        "choices": [
            {"message": {"content": "a.py:1" if cited else "NO_CITATIONS_FOUND"}}
        ]
    }
    client = ChatClient(
        settings,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=response)
        ),
    )
    monkeypatch.setattr(cli, "load_settings", lambda **kwargs: settings)

    def core(request: ExploreRequest, settings: Settings) -> ExploreResult:
        return explore(request, settings, client=client)

    monkeypatch.setattr(cli, "explore", core)
    try:
        code = cli.main(
            [
                "explore",
                "--repo",
                str(tmp_path),
                "--query",
                "How is this implemented?",
                "--format",
                output_format,
            ]
        )
    finally:
        client.close()
    captured = capsys.readouterr()
    assert code == expected_code
    expected_answer = "a.py:1" if cited else "NO_CITATIONS_FOUND"
    if output_format == "json":
        payload = json.loads(captured.out)
        assert payload["answer"] == expected_answer
        assert payload["truncated"] is (max_entries == 1)
        assert payload["warnings"] == (
            ["glob scan budget exhausted"] if max_entries == 1 else []
        )
    else:
        assert captured.out.strip() == expected_answer
    assert captured.err == (
        "WARNING: glob scan budget exhausted\n" if max_entries == 1 else ""
    )


def test_cli_warns_for_bare_path_preview_truncation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "a.py").write_text("a\nb\n")
    monkeypatch.setenv("FLASH_CONTEXT_MAX_READ_LINES", "1")
    assert cli.main(["explore", "--repo", str(tmp_path), "--query", "a.py"]) == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == "a.py:1"
    assert captured.err == "WARNING: Result truncated\n"


@pytest.mark.parametrize("output_format", ["text", "json"])
@pytest.mark.parametrize("failure", ["grep", "read", "verification"])
def test_cli_empty_tool_budget_failure_exits_six(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    output_format: str,
    failure: str,
) -> None:
    from flash_context.agent import explore

    (tmp_path / "a.py").write_text("padding\n" * 20)
    settings = Settings(base_url="http://test/v1", model="mock", max_scan_bytes=10)
    final: dict[str, object] = {
        "choices": [{"message": {"content": "NO_CITATIONS_FOUND"}}]
    }
    responses: Iterator[dict[str, object]]
    if failure == "verification":
        responses = iter([{"choices": [{"message": {"content": "a.py:10"}}]}])
    else:
        tool = "repo_grep" if failure == "grep" else "read_file"
        arguments = (
            {"pattern": "missing"}
            if failure == "grep"
            else {
                "path": "a.py",
                "start_line": 10,
            }
        )
        responses = iter(
            [
                {
                    "choices": [
                        {
                            "message": {
                                "tool_calls": [
                                    {
                                        "id": "1",
                                        "function": {
                                            "name": tool,
                                            "arguments": json.dumps(arguments),
                                        },
                                    }
                                ]
                            }
                        }
                    ]
                },
                final,
            ]
        )
    client = ChatClient(
        settings,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=next(responses))
        ),
    )
    monkeypatch.setattr(cli, "load_settings", lambda **kwargs: settings)

    def core(request: ExploreRequest, settings: Settings) -> ExploreResult:
        return explore(request, settings, client=client)

    monkeypatch.setattr(cli, "explore", core)
    try:
        code = cli.main(
            [
                "explore",
                "--repo",
                str(tmp_path),
                "--query",
                "How is this implemented?",
                "--format",
                output_format,
            ]
        )
    finally:
        client.close()
    captured = capsys.readouterr()
    assert code == 6
    warning = (
        "grep scan budget exhausted"
        if failure == "grep"
        else "read scan budget exhausted"
    )
    assert f"WARNING: {warning}" in captured.err
    if output_format == "json":
        result = json.loads(captured.out)
        assert result["answer"] == "NO_CITATIONS_FOUND"
        assert result["truncated"]
        assert warning in result["warnings"]
    else:
        assert captured.out.strip() == "NO_CITATIONS_FOUND"

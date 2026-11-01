from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from flash_context import cli
from flash_context import config as config_module
from flash_context.config import Settings
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

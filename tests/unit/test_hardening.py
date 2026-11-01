from __future__ import annotations

import json
import os
import tracemalloc
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import httpx
import pytest

from flash_context.agent import explore
from flash_context.config import Settings, SettingsOverrides, load_settings
from flash_context.llm import ChatClient
from flash_context.logging import TrajectoryRecorder
from flash_context.tools import read_file, repo_glob, repo_grep
from flash_context.tools.safety import ScanLimits
from flash_context.types import (
    ExploreRequest,
    ExplorerError,
    SearchHit,
    ToolObservation,
)


@pytest.mark.parametrize("path", [".envrc", "id_ecdsa", ".flash-context/run.json"])
def test_sensitive_names_are_denied(tmp_path: Path, path: str) -> None:
    file = tmp_path / path
    file.parent.mkdir(exist_ok=True)
    file.write_text("secret")
    with pytest.raises(ExplorerError, match="PATH_DENIED"):
        read_file(repo_root=tmp_path, path=path, max_bytes=100)
    assert repo_glob(repo_root=tmp_path, pattern="**/*", max_results=20).matches == []
    assert not repo_grep(repo_root=tmp_path, pattern="secret", max_results=20).hits


def test_both_symlink_names_are_checked(tmp_path: Path) -> None:
    (tmp_path / "public.txt").write_text("test")
    (tmp_path / ".env").symlink_to("public.txt")
    with pytest.raises(ExplorerError, match="PATH_DENIED"):
        read_file(repo_root=tmp_path, path=".env", max_bytes=10)
    (tmp_path / "alias").symlink_to(".env")
    # Resolution through a denied alias must not hide its lexical name.
    (tmp_path / "safe.txt").symlink_to("public.txt")
    result = repo_glob(repo_root=tmp_path, pattern="**/*", max_results=20)
    assert result.matches == ["public.txt"]


def test_read_memory_is_bounded_and_ranges_are_exact(tmp_path: Path) -> None:
    file = tmp_path / "large.txt"
    file.write_bytes(b"x" * (8 * 1024 * 1024))
    tracemalloc.start()
    try:
        result = read_file(repo_root=tmp_path, path=file.name, max_bytes=3)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert result.content == "xxx" and result.truncated
    assert peak < 1024 * 1024
    file.write_text("a\nb\n")
    result = read_file(repo_root=tmp_path, path=file.name, max_bytes=2)
    assert result.line_range == "1-1"


def test_scan_limits_preserve_partial_results(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hit\n" + "x" * 100)
    result = repo_grep(
        repo_root=tmp_path,
        pattern="hit",
        max_results=10,
        limits=ScanLimits(max_scan_bytes=10),
    )
    assert result.hits[0].line == 1
    assert result.truncated and result.warnings
    result = repo_glob(
        repo_root=tmp_path,
        pattern="**/*",
        max_results=10,
        limits=ScanLimits(max_scan_entries=0),
    )
    assert result.truncated and result.warnings


def test_regex_timeout_and_oversized_lines(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("a" * 10000 + "!\n")
    result = repo_grep(
        repo_root=tmp_path,
        pattern="(a|aa)+$",
        max_results=10,
        limits=ScanLimits(tool_timeout_seconds=0.01),
    )
    assert result.truncated and "grep match timed out" in result.warnings
    (tmp_path / "a.txt").write_text("x" * 70000 + "\nneedle\n")
    result = repo_grep(repo_root=tmp_path, pattern="needle", max_results=10)
    assert [hit.line for hit in result.hits] == [2]
    assert result.truncated


def test_unreadable_file_is_structured(tmp_path: Path) -> None:
    (tmp_path / "a.txt").touch()
    with patch.object(Path, "open", side_effect=PermissionError):
        with pytest.raises(ExplorerError, match="PATH_UNREADABLE"):
            read_file(repo_root=tmp_path, path="a.txt", max_bytes=10)
        result = repo_grep(repo_root=tmp_path, pattern="x", max_results=1)
        assert result.truncated and result.warnings


def test_trajectory_rejects_repository_destination_and_omits_text(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    request = ExploreRequest(query="SECRET_QUERY", repo_root=repo)
    with pytest.raises(ExplorerError, match="CONFIG_INVALID"):
        explore(request, Settings(traj_dir=repo / "logs"))
    recorder = TrajectoryRecorder(tmp_path / "logs", request)
    recorder.record_model_turn(
        1, {"content": "SECRET_MODEL", "arguments": "SECRET_ARG"}
    )
    recorder.record_observation(
        1, "repo_grep", ToolObservation(hits=[SearchHit("a.py", 1, "SECRET_SOURCE")])
    )
    recorder.record_observation(
        1, "repo_glob", ToolObservation(matches=["SECRET_PATH"])
    )
    recorder.record_observation(
        2, "read_file", ToolObservation(content="SECRET_SOURCE")
    )
    recorder.finish()
    content = next((tmp_path / "logs").glob("*.json")).read_text()
    assert "SECRET" not in content
    observations = json.loads(content)["turns"][1:]
    assert observations == [
        {
            "turn": 1,
            "tool": "repo_grep",
            "ok": True,
            "truncated": False,
            "hit_count": 1,
        },
        {
            "turn": 1,
            "tool": "repo_glob",
            "ok": True,
            "truncated": False,
            "match_count": 1,
        },
        {
            "turn": 2,
            "tool": "read_file",
            "ok": True,
            "truncated": False,
            "content_length": 13,
        },
    ]
    assert not list(repo.iterdir())


@pytest.mark.parametrize(
    "query",
    [
        "Find `alpha` and `beta`.",
        "Find all callers of `alpha`.",
        "Find all usages of `alpha`.",
    ],
)
def test_ambiguous_intent_uses_model(tmp_path: Path, query: str) -> None:
    (tmp_path / "a.py").write_text("def alpha(): pass\ndef beta(): pass\n")
    with pytest.raises(ExplorerError, match="CONFIG_MISSING_ENDPOINT"):
        explore(ExploreRequest(query=query, repo_root=tmp_path), Settings())


def test_config_diagnostics_and_explicit_log_disable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from flash_context import config

    monkeypatch.setattr(config, "_project_root", lambda: tmp_path)
    for key in list(os.environ):
        if key.startswith("FLASH_CONTEXT_"):
            monkeypatch.delenv(key)
    yaml = tmp_path / "config.yaml"
    yaml.write_text("model:\n  api_key: [SECRET_VALUE\n")
    with pytest.raises(ExplorerError) as error:
        load_settings()
    assert "SECRET_VALUE" not in json.dumps(error.value.to_dict())
    yaml.write_text("explorer:\n  traj_dir: logs\ntools:\n  max_scan_bytes: 100\n")
    monkeypatch.setenv("FLASH_CONTEXT_TRAJ_DIR", "")
    monkeypatch.setenv("FLASH_CONTEXT_MAX_SCAN_BYTES", "200")
    assert load_settings().traj_dir is None
    assert (
        load_settings(overrides=SettingsOverrides(max_scan_bytes=300)).max_scan_bytes
        == 300
    )
    monkeypatch.delenv("FLASH_CONTEXT_TRAJ_DIR")
    assert load_settings(overrides=SettingsOverrides(traj_dir=None)).traj_dir is None
    monkeypatch.setenv("FLASH_CONTEXT_TOOL_TIMEOUT_SECONDS", "nan")
    with pytest.raises(ExplorerError, match="CONFIG_INVALID"):
        load_settings()


def test_model_ranges_and_endpoint_termination(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("a\nb\nc\n")
    settings = Settings(base_url="http://test/v1", model="test")
    responses = iter(
        [
            {
                "content": None,
                "tool_calls": [
                    {
                        "id": "1",
                        "function": {
                            "name": "read_file",
                            "arguments": '{"path":"a.txt","end_line":2}',
                        },
                    }
                ],
            },
            {"content": "a.txt:1"},
        ]
    )
    payloads: list[dict[str, object]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": next(responses)}]})

    with_client = ChatClient(settings, transport=httpx.MockTransport(handle))
    try:
        result = explore(
            ExploreRequest(query="Find the relevant answer", repo_root=tmp_path),
            settings,
            client=with_client,
        )
    finally:
        with_client.close()
    assert not result.truncated
    assert result.answer == "a.txt:1-3"
    for message in ({"content": None}, {"content": "", "tool_calls": []}):
        client = ChatClient(
            settings,
            transport=httpx.MockTransport(
                lambda request, current=message: httpx.Response(
                    200,
                    json={"choices": [{"message": current, "finish_reason": "length"}]},
                )
            ),
        )
        try:
            with pytest.raises(ExplorerError, match="ENDPOINT_BAD_RESPONSE"):
                explore(
                    ExploreRequest(
                        query="Find the relevant answer", repo_root=tmp_path
                    ),
                    settings,
                    client=client,
                )
        finally:
            client.close()
    too_many = {"content": None, "tool_calls": [{"id": str(i)} for i in range(17)]}
    client = ChatClient(
        settings,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"choices": [{"message": too_many}]}
            )
        ),
    )
    try:
        with pytest.raises(ExplorerError, match="Too many tool calls"):
            explore(
                ExploreRequest(query="Find the relevant answer", repo_root=tmp_path),
                settings,
                client=client,
            )
    finally:
        client.close()


def test_short_preview_and_partial_completion(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("a\nb\n")
    settings = Settings(base_url="http://test/v1", model="mock")
    response = iter(
        [
            {
                "message": {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "1",
                            "function": {
                                "name": "read_file",
                                "arguments": '{"path":"a.txt"}',
                            },
                        }
                    ],
                }
            },
            {"message": {"content": "a.txt:1"}, "finish_reason": "length"},
        ]
    )
    sent: list[dict[str, object]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [next(response)]})

    client = ChatClient(settings, transport=httpx.MockTransport(handle))
    try:
        result = explore(
            ExploreRequest(query="Find the relevant answer", repo_root=tmp_path),
            settings,
            client=client,
        )
    finally:
        client.close()
    assert result.answer == "a.txt:1-2" and result.truncated
    assert "endpoint completion token limit reached" in result.warnings
    # A complete short preview must not tell the model to keep expanding it.
    messages = cast(list[dict[str, Any]], sent[-1]["messages"])
    assert json.loads(messages[-1]["content"])["truncated"] is False


def test_array_observation_caps_and_logging_failure(tmp_path: Path) -> None:
    from flash_context.agent import _model_observation_payload
    from flash_context.types import Citation, ExploreResult

    observation = ToolObservation(
        hits=[SearchHit("a.py", i, "x" * 240) for i in range(50)]
    )
    payload = _model_observation_payload(observation, max_chars=600)
    assert payload["truncated"]
    assert len(json.dumps(payload["hits"])) < 650
    recorder = TrajectoryRecorder(
        tmp_path / "logs", ExploreRequest(query="test", repo_root=tmp_path / "repo")
    )
    result = ExploreResult("test", str(tmp_path), "a.py:1", [Citation("a.py", 1, 1)], 1)
    with patch.object(Path, "mkdir", side_effect=PermissionError):
        recorder.finish(result=result)
    assert result.warnings == ["trajectory log could not be written"]


def test_denied_directories_are_pruned(tmp_path: Path) -> None:
    import os

    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "data").write_text("secret")
    original = os.scandir
    with patch("flash_context.tools.safety.os.scandir", wraps=original) as scan:
        result = repo_glob(repo_root=tmp_path, pattern="**/*", max_results=20)
    assert not result.matches
    assert scan.call_count == 1


def test_cli_and_mcp_reject_internal_logging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from flash_context import cli
    from flash_context.mcp_server import explore_repository_handler

    settings = Settings(traj_dir=tmp_path / "logs")
    monkeypatch.setattr(cli, "load_settings", lambda **kwargs: settings)
    assert cli.main(["explore", "--query", "Find answer", "--repo", str(tmp_path)]) == 3
    assert "CONFIG_INVALID" in capsys.readouterr().err
    result = explore_repository_handler(
        query="Find the relevant answer", repo_root=str(tmp_path), settings=settings
    )
    assert cast(dict[str, object], result["error"])["code"] == "CONFIG_INVALID"
    assert not (tmp_path / "logs").exists()


@pytest.mark.parametrize("pattern", ["pkg/base.py", "pkg/*.py", "pkg/**/*.py"])
def test_scoped_searches_do_not_scan_unrelated_directories(
    tmp_path: Path, pattern: str
) -> None:
    (tmp_path / "docs").mkdir()
    for i in range(20):
        (tmp_path / "docs" / f"{i}.md").write_text("noise")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "base.py").write_text("class Target: pass\n")
    limits = ScanLimits(max_scan_entries=3)
    with patch("flash_context.tools.safety.os.scandir", wraps=os.scandir) as scan:
        glob = repo_glob(
            repo_root=tmp_path, pattern=pattern, max_results=10, limits=limits
        )
        grep = repo_grep(
            repo_root=tmp_path,
            pattern="Target",
            glob=pattern,
            max_results=10,
            limits=limits,
        )
    assert glob.matches == ["pkg/base.py"]
    assert [hit.path for hit in grep.hits] == ["pkg/base.py"]
    assert not glob.truncated and not grep.truncated
    assert all(call.args[0] == tmp_path / "pkg" for call in scan.call_args_list)
    if pattern == "pkg/base.py":
        scan.assert_not_called()


@pytest.mark.parametrize("suffix", ["base.py", "*.py", "**/*.py"])
@pytest.mark.parametrize("blocked", ["deny", "ignore", "symlink"])
def test_scoped_search_prefix_preserves_directory_policy(
    tmp_path: Path, suffix: str, blocked: str
) -> None:
    directory = "secrets" if blocked == "deny" else "parent/pkg"
    if blocked == "symlink":
        (tmp_path / "target").mkdir()
        (tmp_path / "target" / "base.py").write_text("SECRET")
        (tmp_path / directory).parent.mkdir(exist_ok=True)
        (tmp_path / directory).symlink_to(tmp_path / "target", target_is_directory=True)
    else:
        (tmp_path / directory).mkdir(parents=True)
        (tmp_path / directory / "base.py").write_text("SECRET")
    ignore = [directory] if blocked == "ignore" else []
    with patch("flash_context.tools.safety.os.scandir", wraps=os.scandir) as scan:
        result = repo_grep(
            repo_root=tmp_path,
            pattern="SECRET",
            glob=f"{directory}/{suffix}",
            max_results=10,
            ignore=ignore,
        )
    assert not result.hits
    assert not result.truncated
    scan.assert_not_called()


@pytest.mark.parametrize("target", ["../outside.py", ".env.local"])
def test_literal_search_rejects_unsafe_resolved_files(
    tmp_path: Path, target: str
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / target).write_text("SECRET")
    (repo / "alias.py").symlink_to(target)
    result = repo_grep(
        repo_root=repo, pattern="SECRET", glob="alias.py", max_results=10
    )
    assert not result.hits
    assert "SECRET" not in json.dumps(result.to_dict())

from __future__ import annotations

import os
from pathlib import Path

import pytest

from flash_context.tools import read_file, repo_glob, repo_grep
from flash_context.types import SearchError


def test_read_file_returns_relative_path_and_line_range(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("one\ntwo\nthree\n", encoding="utf-8")

    observation = read_file(
        repo_root=repo,
        path="app.py",
        start_line=2,
        end_line=3,
        max_bytes=100,
    )

    assert observation.path == "app.py"
    assert observation.line_range == "2-3"
    assert observation.content == "two\nthree\n"
    assert not observation.truncated


def test_read_file_rejects_path_traversal(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("do-not-read", encoding="utf-8")

    with pytest.raises(SearchError) as exc_info:
        read_file(
            repo_root=repo,
            path="../secret.txt",
            max_bytes=100,
        )

    assert exc_info.value.code == "PATH_OUTSIDE_ROOT"
    assert "do-not-read" not in str(exc_info.value.to_dict())


def test_read_file_rejects_normalized_path_traversal(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "safe").mkdir(parents=True)
    (repo / "app.py").write_text("print('ok')\n", encoding="utf-8")

    with pytest.raises(SearchError) as exc_info:
        read_file(
            repo_root=repo,
            path="safe/../app.py",
            max_bytes=100,
        )

    assert exc_info.value.code == "PATH_OUTSIDE_ROOT"


def test_read_file_rejects_symlink_escape(tmp_path: Path) -> None:
    if not hasattr(os, "symlink"):
        pytest.skip("symlink unavailable")
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("do-not-read", encoding="utf-8")
    (repo / "link.txt").symlink_to(outside)

    with pytest.raises(SearchError) as exc_info:
        read_file(repo_root=repo, path="link.txt", max_bytes=100)

    assert exc_info.value.code == "PATH_OUTSIDE_ROOT"
    assert "do-not-read" not in str(exc_info.value.to_dict())


def test_read_file_rejects_denylist_without_content_leak(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".env").write_text("SECRET_TOKEN=abc", encoding="utf-8")

    with pytest.raises(SearchError) as exc_info:
        read_file(repo_root=repo, path=".env", max_bytes=100)

    assert exc_info.value.code == "PATH_DENIED"
    assert "SECRET_TOKEN" not in str(exc_info.value.to_dict())


def test_read_file_caps_bytes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "large.txt").write_text("abcdef\n", encoding="utf-8")

    observation = read_file(repo_root=repo, path="large.txt", max_bytes=3)

    assert observation.content == "abc"
    assert observation.truncated


def test_read_file_rejects_start_line_beyond_eof(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "short.txt").write_text("one\ntwo\n", encoding="utf-8")

    with pytest.raises(SearchError) as exc_info:
        read_file(repo_root=repo, path="short.txt", start_line=3, max_bytes=100)

    assert exc_info.value.code == "INVALID_TOOL_ARGUMENTS"
    assert exc_info.value.details == {
        "path": "short.txt",
        "start_line": 3,
        "total_lines": 2,
    }


def test_repo_glob_omits_denylisted_matches(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / "src").mkdir()
    (repo / ".git" / "config").write_text("secret", encoding="utf-8")
    (repo / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")

    observation = repo_glob(repo_root=repo, pattern="**/*", max_results=20)

    assert observation.matches == ["src/app.py"]


def test_repo_grep_caps_results(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("needle\nneedle\nneedle\n", encoding="utf-8")

    observation = repo_grep(repo_root=repo, pattern="needle", max_results=2)

    assert [hit.line for hit in observation.hits] == [1, 2]
    assert observation.truncated


def test_repo_grep_rejects_invalid_regex(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("needle\n", encoding="utf-8")

    with pytest.raises(SearchError) as exc_info:
        repo_grep(repo_root=repo, pattern="[", max_results=2)

    assert exc_info.value.code == "INVALID_GREP_PATTERN"

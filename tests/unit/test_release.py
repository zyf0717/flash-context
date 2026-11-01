from __future__ import annotations

import hashlib
import json
import runpy
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

ROOT = Path(__file__).resolve().parents[2]
NOTES_SCRIPT = ROOT / "scripts/release_notes.py"
extract_notes = cast(
    Callable[[str, str], str], runpy.run_path(str(NOTES_SCRIPT))["extract_notes"]
)


def test_curated_notes_exclude_other_versions() -> None:
    text = (
        "# Changelog\n## [Unreleased]\n- Future\n"
        "## [0.2.0] - 2026-11-01\n### Migration\n- Disable local logs.\n"
        "## [0.1.0] - 2026-11-01\n- Initial release\n"
    )
    assert extract_notes(text, "0.2.0") == "### Migration\n- Disable local logs.\n"


@pytest.mark.parametrize(
    "text",
    [
        "## [Unreleased]\n- Something\n",
        "## [0.2.0]\n- Missing date\n",
        "## [0.2.0] - 2026-02-30\n- Invalid date\n",
        "## [0.2.0] - 2026-11-01\n### Added\n",
        "## [0.2.0] - 2026-11-01\n- One\n## [0.2.0] - 2026-11-01\n- Two\n",
    ],
)
def test_missing_malformed_empty_and_duplicate_entries_fail(text: str) -> None:
    with pytest.raises(ValueError):
        extract_notes(text, "0.2.0")


def test_tag_validation_uses_project_version(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nversion="0.2.0"\n')
    (tmp_path / "CHANGELOG.md").write_text("## [0.2.0] - 2026-11-01\n- Fixed\n")
    valid = subprocess.run(
        [sys.executable, str(NOTES_SCRIPT), "v0.2.0"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert valid.returncode == 0 and valid.stdout == "- Fixed\n"
    invalid = subprocess.run(
        [sys.executable, str(NOTES_SCRIPT), "v0.1.0"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert invalid.returncode != 0 and "Tag must match" in invalid.stderr


@pytest.fixture
def publisher(tmp_path: Path) -> tuple[Any, Path, Path, list[tuple[str, ...]]]:
    namespace = runpy.run_path(str(ROOT / "scripts/github_release.py"))
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "pkg.whl").write_bytes(b"wheel")
    (dist / "pkg.tar.gz").write_bytes(b"source")
    notes = tmp_path / "notes.md"
    notes.write_text("Curated notes\n")
    calls: list[tuple[str, ...]] = []
    publish = namespace["publish"]

    def fake_gh(*args: str) -> str:
        calls.append(args)
        return ""

    publish.__globals__["gh"] = fake_gh
    return publish, notes, dist, calls


@pytest.mark.parametrize("tag,prerelease", [("v0.2.0", False), ("v0.3.0rc1", True)])
def test_new_release_uploads_before_publishing(
    publisher: tuple[Any, Path, Path, list[tuple[str, ...]]],
    tag: str,
    prerelease: bool,
) -> None:
    publish, notes, dist, calls = publisher
    publish("owner/repo", tag, notes, dist)
    assert "--paginate" in calls[0]
    assert calls[1][:2] == ("release", "create") and "--draft" in calls[1]
    assert ("--prerelease" in calls[1]) is prerelease
    assert [call[1] for call in calls[2:]] == ["upload", "upload", "edit"]
    assert "--draft=false" in calls[-1]


@pytest.mark.parametrize("draft", [False, True])
def test_existing_release_preserves_notes_and_matching_assets(
    publisher: tuple[Any, Path, Path, list[tuple[str, ...]]],
    draft: bool,
) -> None:
    publish, notes, dist, calls = publisher
    assets = [
        {
            "name": f.name,
            "digest": "sha256:" + hashlib.sha256(f.read_bytes()).hexdigest(),
        }
        for f in dist.iterdir()
    ]

    def existing(*args: str) -> str:
        calls.append(args)
        return json.dumps({"draft": draft, "assets": assets})

    publish.__globals__["gh"] = existing
    publish("owner/repo", "v0.2.0", notes, dist)
    assert len(calls) == (2 if draft else 1)
    if draft:
        assert calls[-1][1] == "edit"


def test_resume_partial_upload_and_reject_mismatch(
    publisher: tuple[Any, Path, Path, list[tuple[str, ...]]],
) -> None:
    publish, notes, dist, calls = publisher
    file = dist / "pkg.whl"
    asset = {
        "name": file.name,
        "digest": "sha256:" + hashlib.sha256(file.read_bytes()).hexdigest(),
    }

    def existing(*args: str) -> str:
        calls.append(args)
        return json.dumps({"draft": True, "assets": [asset]})

    publish.__globals__["gh"] = existing
    publish("owner/repo", "v0.2.0", notes, dist)
    assert [call[1] for call in calls[1:]] == ["upload", "edit"]
    assert "pkg.tar.gz" in calls[1][3]
    asset["digest"] = "sha256:wrong"
    calls.clear()
    with pytest.raises(ValueError, match="differs"):
        publish("owner/repo", "v0.2.0", notes, dist)
    assert len(calls) == 1


def test_lookup_failure_does_not_create_release(
    publisher: tuple[Any, Path, Path, list[tuple[str, ...]]],
) -> None:
    publish, notes, dist, calls = publisher

    def denied(*args: str) -> str:
        calls.append(args)
        raise subprocess.CalledProcessError(1, "gh", stderr="HTTP 403")

    publish.__globals__["gh"] = denied
    with pytest.raises(subprocess.CalledProcessError):
        publish("owner/repo", "v0.2.0", notes, dist)
    assert len(calls) == 1


def test_workflow_gates_publication_and_limits_write_permission() -> None:
    import yaml

    release = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text())
    jobs = release["jobs"]
    assert jobs["github-release"]["needs"] == "verify-pypi"
    assert release["permissions"] == {"contents": "read"}
    assert [
        name
        for name, job in jobs.items()
        if job.get("permissions", {}).get("contents") == "write"
    ] == ["github-release"]
    for name in ["verify-testpypi", "verify-pypi"]:
        install = next(step["run"] for step in jobs[name]["steps"] if "run" in step)
        assert "--refresh-package flash-context" in install
    ci = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    commands = [step.get("run", "") for step in ci["jobs"]["build"]["steps"]]
    validation = next(
        i for i, command in enumerate(commands) if "release_notes.py" in command
    )
    assert validation < commands.index("uv build")

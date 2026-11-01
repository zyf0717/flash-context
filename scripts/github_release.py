"""Create or resume a GitHub release without overwriting notes or artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path


def gh(*args: str) -> str:
    return subprocess.check_output(["gh", *args], text=True, stderr=subprocess.PIPE)


def publish(repo: str, tag: str, notes: Path, dist: Path) -> None:
    files = sorted(dist.iterdir())
    if (
        len(files) != 2
        or not any(p.suffix == ".whl" for p in files)
        or not any(p.name.endswith(".tar.gz") for p in files)
    ):
        raise ValueError("Expected exactly one wheel and one source distribution")
    # Listing includes drafts, unlike the published-release-by-tag endpoint.
    found = gh(
        "api",
        "--paginate",
        f"repos/{repo}/releases?per_page=100",
        "--jq",
        f".[] | select(.tag_name == {json.dumps(tag)})",
    )
    release = json.loads(found) if found.strip() else None
    if release is None:
        options = ["--prerelease"] if re.search(r"(?:a|b|rc|dev)\d", tag) else []
        gh(
            "release",
            "create",
            tag,
            "--repo",
            repo,
            "--verify-tag",
            "--draft",
            "--title",
            tag,
            "--notes-file",
            str(notes),
            *options,
        )
        release = {"draft": True, "assets": []}
    assets = {asset["name"]: asset for asset in release["assets"]}
    # Check every existing asset before uploading anything new.
    for file in files:
        if file.name in assets:
            digest = "sha256:" + hashlib.sha256(file.read_bytes()).hexdigest()
            if assets[file.name].get("digest") != digest:
                raise ValueError(f"Existing release asset differs: {file.name}")
    for file in files:
        if file.name not in assets:
            gh("release", "upload", tag, str(file), "--repo", repo)
    if release["draft"]:
        gh("release", "edit", tag, "--repo", repo, "--draft=false")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--notes", required=True, type=Path)
    parser.add_argument("--dist", required=True, type=Path)
    args = parser.parse_args()
    try:
        publish(args.repo, args.tag, args.notes, args.dist)
    except subprocess.CalledProcessError as exc:
        parser.exit(1, exc.stderr)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()

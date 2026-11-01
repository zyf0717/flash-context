"""Validate the package/tag/changelog contract and print curated release notes."""

from __future__ import annotations

import argparse
import re
import tomllib
from datetime import date
from pathlib import Path


def extract_notes(changelog: str, version: str) -> str:
    headings = list(re.finditer(r"^## .+$", changelog, re.MULTILINE))
    matches = [
        (i, heading)
        for i, heading in enumerate(headings)
        if heading.group().startswith(f"## [{version}]")
    ]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one changelog entry for {version}")
    index, heading = matches[0]
    dated = re.fullmatch(r"## \[.+\] - (\d{4}-\d{2}-\d{2})", heading.group())
    if dated is None:
        raise ValueError(f"Changelog entry for {version} needs a YYYY-MM-DD date")
    date.fromisoformat(dated[1])
    end = headings[index + 1].start() if index + 1 < len(headings) else len(changelog)
    notes = changelog[heading.end() : end].strip()
    if not any(
        line.strip() and not line.startswith("#") for line in notes.splitlines()
    ):
        raise ValueError(f"Changelog entry for {version} is empty")
    return notes + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "tag", nargs="?", help="Optional tag, exactly v plus package version"
    )
    args = parser.parse_args()
    try:
        version = tomllib.loads(Path("pyproject.toml").read_text())["project"][
            "version"
        ]
        if args.tag and args.tag != f"v{version}":
            raise ValueError(f"Tag must match package version v{version}")
        print(extract_notes(Path("CHANGELOG.md").read_text(), version), end="")
    except (OSError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()

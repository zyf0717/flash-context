"""Opt-in model quality trends against independently annotated, pinned sources."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from time import perf_counter
from typing import Any

from flash_context.agent import explore
from flash_context.config import Settings, load_settings
from flash_context.types import ExploreRequest

PROJECT = Path(__file__).resolve().parents[1]


def cases() -> list[dict[str, Any]]:
    return json.loads((PROJECT / "benchmarks/citations.json").read_text())  # type: ignore[no-any-return]


def evaluate(case: dict[str, Any], settings: Settings) -> dict[str, object]:
    root = PROJECT / case["root"]
    path = case["path"]
    assert hashlib.sha256((root / path).read_bytes()).hexdigest() == case["sha256"]
    truth = [
        {(path, n) for n in range(region["start_line"], region["end_line"] + 1)}
        for region in case["expected"]
    ]
    started = perf_counter()
    result = explore(
        ExploreRequest(case["query"], root, max_turns=settings.max_turns), settings
    )
    coverage = {
        (c.path, n)
        for c in result.citations
        for n in range(c.start_line or 1, (c.end_line or 0) + 1)
    }
    hits = sum(bool(region & coverage) for region in truth)
    return {
        "case": case["name"],
        "fixture_sha256": case["sha256"],
        "hit": hits == len(truth),
        "region_recall": hits / len(truth),
        "tightness": len(set.union(*truth) & coverage) / len(coverage)
        if coverage
        else None,
        "cited_lines": len(coverage),
        "turns": result.turns_used,
        "source_bytes": sum(len(r.text.encode()) for r in result.raw_locations),
        "result_bytes": len(json.dumps(result.to_dict()).encode()),
        "seconds": perf_counter() - started,
        "truncated": result.truncated,
        "warnings": result.warnings,
    }


def metadata(settings: Settings) -> dict[str, object]:
    packages: dict[str, str | None] = {}
    for name in ("flash-context", "tree-sitter", "tree-sitter-language-pack"):
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            packages[name] = None
    return {
        "packages": packages,
        "settings": {
            k: v
            for k, v in asdict(settings).items()
            if k not in {"api_key", "base_url", "traj_dir"}
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repetitions", type=int, default=3)
    args = parser.parse_args()
    if args.repetitions < 1:
        parser.error("--repetitions must be positive")
    settings = load_settings()
    settings.require_endpoint()
    context = metadata(settings)
    for case in cases():
        for repetition in range(args.repetitions):
            print(
                json.dumps(
                    {**context, "repetition": repetition, **evaluate(case, settings)}
                )
            )


if __name__ == "__main__":
    main()

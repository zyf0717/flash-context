"""Opt-in model quality trend: uv run python scripts/citation_benchmark.py."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from time import perf_counter
from typing import Any

from flash_context.agent import explore
from flash_context.citations import CitationResolver
from flash_context.config import load_settings
from flash_context.types import ExploreRequest


def main() -> None:
    project = Path(__file__).resolve().parents[1]
    cases: list[dict[str, Any]] = json.loads(
        (project / "benchmarks/citations.json").read_text()
    )
    for case in cases:
        root = project / case["root"]
        path = case["path"]
        assert hashlib.sha256((root / path).read_bytes()).hexdigest() == case["sha256"]
        settings = load_settings()
        resolver = CitationResolver(root, settings, None)
        expected = [resolver.resolve(path, symbol=s) for s in case["symbols"]]
        assert all(expected)
        truth = [
            {(c.path, n) for n in range(c.start_line or 1, (c.end_line or 0) + 1)}
            for c in expected
            if c is not None
        ]
        for repetition in range(3):
            started = perf_counter()
            result = explore(ExploreRequest(case["query"], root), settings)
            coverage = {
                (c.path, n)
                for c in result.citations
                for n in range(c.start_line or 1, (c.end_line or 0) + 1)
            }
            hits = sum(bool(region & coverage) for region in truth)
            print(
                json.dumps(
                    {
                        "case": case["name"],
                        "repetition": repetition,
                        "fixture_sha256": case["sha256"],
                        "model": settings.model,
                        "temperature": settings.temperature,
                        "max_turns": settings.max_turns,
                        "hit": hits == len(truth),
                        "symbol_recall": hits / len(truth),
                        "tightness": (
                            len(set.union(*truth) & coverage) / len(coverage)
                            if coverage
                            else None
                        ),
                        "cited_lines": len(coverage),
                        "turns": result.turns_used,
                        "source_bytes": sum(
                            len(r.text.encode()) for r in result.raw_locations
                        ),
                        "result_bytes": len(json.dumps(result.to_dict()).encode()),
                        "seconds": perf_counter() - started,
                    }
                )
            )


if __name__ == "__main__":
    main()

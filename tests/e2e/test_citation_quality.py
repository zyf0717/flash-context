"""Optional live probes share the benchmark's pinned fixtures and independent truth."""

import json
import os
from typing import Any

import pytest

from flash_context.config import load_settings
from scripts.citation_benchmark import cases, evaluate, metadata

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        os.environ.get("FLASH_CONTEXT_RUN_E2E") != "1",
        reason="set FLASH_CONTEXT_RUN_E2E=1 with an endpoint for live probes",
    ),
]


@pytest.mark.parametrize("case", cases(), ids=lambda case: case["name"])
def test_citation_quality(case: dict[str, Any]) -> None:
    settings = load_settings()
    settings.require_endpoint()
    result = evaluate(case, settings)
    print(json.dumps({**metadata(settings), **result}))
    assert result["hit"], result

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from flash_context.agent import explore
from flash_context.config import Settings
from flash_context.llm import ChatClient
from flash_context.types import ExploreRequest
from tests.helpers import _message_response, _mock_transport, _tool_response


def test_fixture_repository_returns_validation_citation() -> None:
    repo = Path("tests/fixtures/sample_repo").resolve()
    settings = Settings(base_url="http://test/v1", model="test-model")
    responses: Iterator[dict[str, object]] = iter(
        [
            _tool_response(
                "call_1",
                "repo_grep",
                {"pattern": "validate_request", "glob": "**/*.py"},
            ),
            _message_response("src/api/validation.py:1\ntests/test_validation.py:4"),
        ]
    )
    client = ChatClient(settings, transport=_mock_transport(responses))

    result = explore(
        ExploreRequest(query="Find validation logic", repo_root=repo),
        settings,
        client=client,
    )

    assert [citation.path for citation in result.citations] == [
        "src/api/validation.py",
        "tests/test_validation.py",
    ]

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import httpx

from flash_context.agent import explore
from flash_context.config import Settings
from flash_context.llm import ChatClient
from flash_context.types import ExploreRequest


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


def _mock_transport(responses: Iterator[dict[str, object]]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=next(responses))

    return httpx.MockTransport(handler)


def _tool_response(
    call_id: str,
    name: str,
    arguments: dict[str, object],
) -> dict[str, object]:
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(arguments),
                            },
                        }
                    ],
                }
            }
        ]
    }


def _message_response(content: str) -> dict[str, object]:
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": content,
                }
            }
        ]
    }

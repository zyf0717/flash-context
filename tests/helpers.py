from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any, cast

import httpx


def _mock_transport(
    responses: Iterator[dict[str, object]],
    seen_payloads: list[dict[str, object]] | None = None,
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen_payloads is not None:
            seen_payloads.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(200, json=next(responses))

    return httpx.MockTransport(handler)


def _last_tool_payload(seen_payloads: list[dict[str, object]]) -> dict[str, object]:
    messages = cast(list[dict[str, Any]], seen_payloads[-1]["messages"])
    tool_messages = [message for message in messages if message.get("role") == "tool"]
    assert tool_messages
    return cast(dict[str, object], json.loads(str(tool_messages[-1]["content"])))


def _tool_response(
    call_id: str,
    name: str,
    arguments: dict[str, object],
    *,
    content: str | None = None,
) -> dict[str, object]:
    return _multi_tool_response([(call_id, name, arguments)], content=content)


def _multi_tool_response(
    calls: list[tuple[str, str, dict[str, object]]],
    *,
    content: str | None = None,
) -> dict[str, object]:
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(arguments),
                            },
                        }
                        for call_id, name, arguments in calls
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

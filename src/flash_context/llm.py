from __future__ import annotations

from typing import Any

import httpx

from flash_context.config import Settings
from flash_context.types import ExplorerError, JsonObject


class ChatClient:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._client = httpx.Client(
            timeout=settings.timeout_seconds,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def chat_completion(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> JsonObject:
        url = _chat_completions_url(self._settings.base_url)
        headers = {"Content-Type": "application/json"}
        if self._settings.api_key:
            headers["Authorization"] = f"Bearer {self._settings.api_key}"
        payload: JsonObject = {
            "model": self._settings.model,
            "messages": messages,
            "max_tokens": self._settings.max_completion_tokens,
            "temperature": self._settings.temperature,
        }
        if tools:
            payload.update(tools=tools, tool_choice="auto")
        try:
            response = self._client.post(url, headers=headers, json=payload)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise ExplorerError(
                "ENDPOINT_TIMEOUT",
                "Endpoint request timed out",
                retryable=True,
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise ExplorerError(
                "ENDPOINT_BAD_RESPONSE",
                "Endpoint returned an unsuccessful status",
                retryable=500 <= exc.response.status_code < 600,
                details={"status_code": exc.response.status_code},
            ) from exc
        except httpx.HTTPError as exc:
            raise ExplorerError(
                "ENDPOINT_UNREACHABLE",
                "Endpoint request failed",
                retryable=True,
            ) from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise ExplorerError(
                "ENDPOINT_BAD_RESPONSE",
                "Endpoint returned invalid JSON",
            ) from exc
        if not isinstance(data, dict):
            raise ExplorerError(
                "ENDPOINT_BAD_RESPONSE",
                "Endpoint response must be a JSON object",
            )
        return data


def _chat_completions_url(base_url: str) -> str:
    trimmed = base_url.rstrip("/")
    if trimmed.endswith("/chat/completions"):
        return trimmed
    return f"{trimmed}/chat/completions"

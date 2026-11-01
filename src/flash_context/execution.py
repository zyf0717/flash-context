"""Validate endpoint messages and execute the approved read-only tool batch."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, cast

from flash_context.config import Settings
from flash_context.tools import read_file, repo_glob, repo_grep
from flash_context.types import (
    Diagnostic,
    ExplorerError,
    ToolCall,
    ToolName,
    ToolObservation,
    source_lines,
)

ALLOWED_TOOLS: set[ToolName] = {"read_file", "repo_glob", "repo_grep"}


def tool_schemas() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a bounded line range from a repository file.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": (
                                "Repository-relative file path with no leading "
                                "slash, e.g. src/flash_context/types.py."
                            ),
                        },
                        "start_line": {"type": "integer", "minimum": 1},
                        "end_line": {"type": "integer", "minimum": 1},
                    },
                    "required": ["path"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "repo_glob",
                "description": "List repository files matching a glob pattern.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pattern": {
                            "type": "string",
                            "description": (
                                "Repository-relative glob with no leading "
                                "slash, e.g. src/**/*.py."
                            ),
                        }
                    },
                    "required": ["pattern"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "repo_grep",
                "description": (
                    "Search repository text files with a regular expression."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string"},
                        "glob": {
                            "type": "string",
                            "description": (
                                "Optional repository-relative glob with no "
                                "leading slash, e.g. src/**/*.py."
                            ),
                        },
                        "max_results": {"type": "integer", "minimum": 1},
                    },
                    "required": ["pattern"],
                    "additionalProperties": False,
                },
            },
        },
    ]


def _tool_call_fingerprint(tool_call: ToolCall) -> str:
    return json.dumps(
        {
            "name": tool_call.name,
            "arguments": tool_call.arguments,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _extract_message(response: dict[str, Any]) -> dict[str, Any]:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ExplorerError(
            "ENDPOINT_BAD_RESPONSE",
            "Endpoint response has no choices",
        )
    first = choices[0]
    if not isinstance(first, dict):
        raise ExplorerError(
            "ENDPOINT_BAD_RESPONSE", "Endpoint choice must be an object"
        )
    message = first.get("message")
    if not isinstance(message, dict):
        raise ExplorerError(
            "ENDPOINT_BAD_RESPONSE", "Endpoint message must be an object"
        )
    content = message.get("content")
    if content is not None and not isinstance(content, str):
        raise ExplorerError("ENDPOINT_BAD_RESPONSE", "Message content must be text")
    if (
        (not content or not content.strip())
        and not message.get("tool_calls")
        and first.get("finish_reason") != "length"
    ):
        raise ExplorerError(
            "ENDPOINT_BAD_RESPONSE", "Endpoint returned an empty message"
        )
    return cast(dict[str, Any], message)


def _extract_tool_calls(message: dict[str, Any]) -> list[ToolCall]:
    raw_calls = message.get("tool_calls")
    if raw_calls is None:
        return []
    if not isinstance(raw_calls, list):
        raise ExplorerError("ENDPOINT_BAD_RESPONSE", "tool_calls must be a list")
    calls: list[ToolCall] = []
    for raw_call in raw_calls:
        calls.append(_parse_tool_call(raw_call))
    return calls


def _parse_tool_call(raw_call: object) -> ToolCall:
    if not isinstance(raw_call, dict):
        raise ExplorerError("ENDPOINT_BAD_RESPONSE", "tool call must be an object")
    call_id = raw_call.get("id")
    function = raw_call.get("function")
    if not isinstance(call_id, str) or not isinstance(function, dict):
        raise ExplorerError(
            "ENDPOINT_BAD_RESPONSE",
            "tool call is missing id/function",
        )
    name = function.get("name")
    if not isinstance(name, str) or name not in ALLOWED_TOOLS:
        raise ExplorerError(
            "UNSUPPORTED_TOOL_CALL",
            "Endpoint requested an unsupported tool",
            details={"tool": name or "<missing>"},
        )
    raw_arguments = function.get("arguments", "{}")
    if not isinstance(raw_arguments, str):
        raise ExplorerError(
            "ENDPOINT_BAD_RESPONSE",
            "tool arguments must be JSON text",
        )
    try:
        arguments = json.loads(raw_arguments)
    except json.JSONDecodeError as exc:
        raise ExplorerError(
            "ENDPOINT_BAD_RESPONSE",
            "tool arguments must be valid JSON",
        ) from exc
    if not isinstance(arguments, dict):
        raise ExplorerError(
            "ENDPOINT_BAD_RESPONSE",
            "tool arguments must be an object",
        )
    return ToolCall(
        id=call_id,
        name=name,
        arguments=cast(dict[str, object], arguments),
    )


def _assistant_tool_message(message: dict[str, Any]) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": message.get("content"),
        "tool_calls": message.get("tool_calls"),
    }


def _model_observation_payload(
    observation: ToolObservation,
    *,
    max_chars: int | None = None,
) -> dict[str, object]:
    payload = observation.to_dict()
    if (
        observation.ok
        and observation.content is not None
        and observation.line_range is not None
    ):
        payload["content"] = _with_line_numbers(
            observation.content,
            observation.line_range,
        )
    if max_chars is not None:
        _cap_payload_content(payload, max_chars)
    return payload


def _cap_payload_content(payload: dict[str, object], max_chars: int) -> None:
    for key in ("hits", "matches"):
        rows = payload.get(key)
        if isinstance(rows, list):
            kept = []
            size = 0
            for row in rows:
                size += len(json.dumps(row))
                if size > max_chars:
                    payload["truncated"] = True
                    break
                kept.append(row)
            payload[key] = kept
    content = payload.get("content")
    if not isinstance(content, str) or len(content) <= max_chars:
        return
    payload["content"] = content[:max_chars]
    payload["content_truncated_by_chars"] = True
    payload["truncated"] = True


def _with_line_numbers(content: str, line_range: str) -> str:
    line_number = int(line_range.partition("-")[0])
    lines: list[str] = []
    for offset, line in enumerate(source_lines(content), start=0):
        line = line.removesuffix("\r\n").removesuffix("\n")
        lines.append(f"{line_number + offset}: {line}")
    if content.endswith("\n"):
        return "\n".join(lines) + "\n"
    return "\n".join(lines)


def _execute_tool_calls_parallel(
    tool_calls: list[ToolCall],
    *,
    repo_root: Path,
    settings: Settings,
) -> list[ToolObservation]:
    if len(tool_calls) <= 1 or settings.max_parallel_tools <= 1:
        return [
            _execute_tool_call(
                tool_call,
                repo_root=repo_root,
                settings=settings,
            )
            for tool_call in tool_calls
        ]
    worker_count = min(settings.max_parallel_tools, len(tool_calls))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [
            executor.submit(
                _execute_tool_call,
                tool_call,
                repo_root=repo_root,
                settings=settings,
            )
            for tool_call in tool_calls
        ]
        return [future.result() for future in futures]


def _execute_tool_call(
    tool_call: ToolCall,
    *,
    repo_root: Path,
    settings: Settings,
) -> ToolObservation:
    try:
        if tool_call.name == "read_file":
            start_line, end_line, clamped = _bounded_read_lines(
                tool_call.arguments,
                settings,
            )
            observation = read_file(
                repo_root=repo_root,
                path=_required_str(tool_call.arguments, "path"),
                start_line=start_line,
                end_line=end_line,
                max_bytes=settings.max_read_bytes,
                ignore=settings.ignore,
                limits=settings.limits,
                preview=clamped,
            )
            return observation
        if tool_call.name == "repo_glob":
            return repo_glob(
                repo_root=repo_root,
                pattern=_required_str(tool_call.arguments, "pattern"),
                max_results=settings.max_grep_results,
                ignore=settings.ignore,
                limits=settings.limits,
            )
        if tool_call.name == "repo_grep":
            requested_max = _optional_int(tool_call.arguments, "max_results")
            return repo_grep(
                repo_root=repo_root,
                pattern=_required_str(tool_call.arguments, "pattern"),
                glob=_optional_str(tool_call.arguments, "glob") or "**/*",
                max_results=requested_max or settings.max_grep_results,
                configured_max_results=settings.max_grep_results,
                ignore=settings.ignore,
                limits=settings.limits,
            )
    except ExplorerError as exc:
        observation = ToolObservation.from_error(exc, tool_call_id=tool_call.id)
        if exc.code == "TOOL_LIMIT_EXCEEDED":
            observation.truncated = True
            observation.warnings.append(Diagnostic.READ_LIMIT)
        return observation
    raise AssertionError(f"unhandled tool: {tool_call.name}")


def _required_str(arguments: dict[str, object], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value:
        raise ExplorerError("INVALID_TOOL_ARGUMENTS", f"{key} is required")
    return value


def _optional_str(arguments: dict[str, object], key: str) -> str | None:
    value = arguments.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ExplorerError("INVALID_TOOL_ARGUMENTS", f"{key} must be a string")
    return value


def _optional_int(arguments: dict[str, object], key: str) -> int | None:
    value = arguments.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ExplorerError("INVALID_TOOL_ARGUMENTS", f"{key} must be an integer")
    return value


def _bounded_read_lines(
    arguments: dict[str, object],
    settings: Settings,
) -> tuple[int | None, int | None, bool]:
    start_line = _optional_int(arguments, "start_line")
    end_line = _optional_int(arguments, "end_line")
    start_line = 1 if start_line is None else start_line
    if start_line <= 0 or (end_line is not None and end_line < start_line):
        raise ExplorerError("INVALID_TOOL_ARGUMENTS", "Invalid read line range")
    max_end = start_line + settings.max_read_lines - 1
    return (
        start_line,
        min(end_line, max_end) if end_line is not None else max_end,
        (end_line is None or end_line > max_end),
    )

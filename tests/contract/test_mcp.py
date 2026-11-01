from __future__ import annotations

import asyncio
import os
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from flash_context import config as config_module
from flash_context import mcp_server
from flash_context.agent import explore
from flash_context.config import Settings
from flash_context.llm import ChatClient
from flash_context.mcp_server import explore_repository_handler
from flash_context.types import Citation, ExploreRequest, ExploreResult, RawLocation


@pytest.mark.parametrize(
    "warning",
    [
        "implementation source not verified; returning documentation evidence",
        "query symbol not found in verified evidence",
    ],
)
def test_mcp_handler_delegates_to_core(tmp_path: Path, warning: str) -> None:
    captured: dict[str, object] = {}
    settings = Settings(base_url="http://test/v1", model="test-model")

    def fake_core(request: ExploreRequest, core_settings: Settings) -> ExploreResult:
        captured["request"] = request
        captured["settings"] = core_settings
        return ExploreResult(
            query=request.query,
            repo_root=str(tmp_path),
            answer="src/api/validation.py:1",
            citations=[Citation("src/api/validation.py", 1, 1)],
            raw_locations=[
                RawLocation("src/api/validation.py", 1, 1, "def validate():\n")
            ],
            turns_used=1,
            truncated=True,
            warnings=[warning],
        )

    result = explore_repository_handler(
        query="Find request validation",
        repo_root=str(tmp_path),
        max_turns=2,
        citation=True,
        settings=settings,
        core=fake_core,
    )

    assert result["truncated"] is True
    assert result["warnings"] == [warning]
    request = captured["request"]
    assert isinstance(request, ExploreRequest)
    assert request.max_turns == 2
    assert result["citations"] == [
        {
            "path": "src/api/validation.py",
            "start_line": 1,
            "end_line": 1,
        }
    ]
    assert result["raw_locations"] == [
        {
            "path": "src/api/validation.py",
            "start_line": 1,
            "end_line": 1,
            "text": "def validate():\n",
            "truncated": False,
        }
    ]


def test_mcp_handler_returns_structured_error_for_invalid_root(tmp_path: Path) -> None:
    settings = Settings(base_url="http://test/v1", model="test-model")

    result = explore_repository_handler(
        query="Find request validation",
        repo_root=str(tmp_path / "missing"),
        settings=settings,
    )

    assert result["error"]["code"] == "REPO_NOT_FOUND"  # type: ignore[index]


def test_mcp_handler_uses_project_root_config_and_dotenv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    for key in list(os.environ):
        if key.startswith("FLASH_CONTEXT_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(config_module, "_project_root", lambda: tmp_path)
    (tmp_path / "config.yaml").write_text(
        """
model:
  base_url: "http://yaml/v1"
  model: "yaml-model"
""",
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text(
        "FLASH_CONTEXT_BASE_URL=http://dotenv/v1\n",
        encoding="utf-8",
    )

    def fake_core(request: ExploreRequest, core_settings: Settings) -> ExploreResult:
        captured["settings"] = core_settings
        return ExploreResult(
            query=request.query,
            repo_root=str(tmp_path),
            answer="src/api/validation.py:1",
            citations=[Citation("src/api/validation.py", 1, 1)],
            turns_used=1,
        )

    result = explore_repository_handler(
        query="Find request validation",
        repo_root=str(tmp_path),
        core=fake_core,
    )

    settings = captured["settings"]
    assert isinstance(settings, Settings)
    assert settings.base_url == "http://dotenv/v1"
    assert settings.model == "yaml-model"
    assert result["answer"] == "src/api/validation.py:1"


def test_mcp_handler_returns_core_normalized_citation_result(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    (repo / "src" / "api").mkdir(parents=True)
    (repo / "src" / "api" / "validation.py").write_text(
        "def validate_request(payload):\n    return bool(payload)\n",
        encoding="utf-8",
    )
    responses: Iterator[dict[str, object]] = iter(
        [
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": (
                                "Here is the answer:\n"
                                "src/api/validation.py:1\n"
                                "Validation entrypoint."
                            ),
                        }
                    }
                ]
            }
        ]
    )
    settings = Settings(base_url="http://test/v1", model="test-model")
    client = ChatClient(settings, transport=_mock_transport(responses))

    def core(request: ExploreRequest, core_settings: Settings) -> ExploreResult:
        return explore(request, core_settings, client=client)

    result = explore_repository_handler(
        query="Find request validation",
        repo_root=str(repo),
        settings=settings,
        core=core,
    )

    assert result["answer"] == "src/api/validation.py:1-2"
    assert result["citations"] == [
        {
            "path": "src/api/validation.py",
            "start_line": 1,
            "end_line": 2,
            "precision": {
                "range_lines": 2,
                "boundary_kind": "definition",
                "symbol": "validate_request",
                "query_token_in_range": None,
                "definitions_spanned": 1,
            },
        }
    ]
    assert result["raw_locations"] == [
        {
            "path": "src/api/validation.py",
            "start_line": 1,
            "end_line": 2,
            "text": "def validate_request(payload):\n    return bool(payload)\n",
            "truncated": False,
        }
    ]


def test_mcp_server_registers_explore_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeServer:
        def __init__(self, name: str) -> None:
            self.name = name
            self._mcp_server = SimpleNamespace(version=None)
            self.tools: dict[str, Callable[..., object]] = {}

        def tool(self) -> Callable[[Callable[..., object]], Callable[..., object]]:
            def decorator(func: Callable[..., object]) -> Callable[..., object]:
                self.tools[func.__name__] = func
                return func

            return decorator

    monkeypatch.setattr(
        mcp_server,
        "import_module",
        lambda name: SimpleNamespace(FastMCP=FakeServer),
    )

    server = mcp_server.create_server()

    assert server.name == "flash-context"
    assert "explore_repository" in server.tools


def _mock_transport(responses: Iterator[dict[str, object]]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        _ = request
        return httpx.Response(200, json=next(responses))

    return httpx.MockTransport(handler)


def test_real_mcp_discovery_describes_repository_exploration() -> None:
    pytest.importorskip("mcp")
    tools = asyncio.run(mcp_server.create_server().list_tools())
    assert [tool.name for tool in tools] == ["explore_repository"]
    assert tools[0].inputSchema["required"] == ["query"]
    description = tools[0].description.lower()
    assert "read-only" in description
    assert "citations" in description and "snippets" in description


def test_real_mcp_initialization_reports_package_version() -> None:
    pytest.importorskip("mcp")
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    from flash_context import __version__

    async def initialize() -> None:
        params = StdioServerParameters(command="flash-context", args=["mcp"])
        async with (
            stdio_client(params) as (read, write),
            ClientSession(read, write) as session,
        ):
            result = await session.initialize()
            assert result.serverInfo.name == "flash-context"
            assert result.serverInfo.version == __version__

    asyncio.run(initialize())

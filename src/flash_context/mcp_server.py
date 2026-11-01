from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from importlib import import_module
from pathlib import Path
from typing import Any

from flash_context import __version__
from flash_context.agent import search
from flash_context.config import Settings, SettingsOverrides, load_settings
from flash_context.types import SearchError, SearchRequest, SearchResult

CoreFn = Callable[[SearchRequest, Settings], SearchResult]


def search_repository_handler(
    *,
    query: str,
    repo_root: str | None = None,
    max_turns: int | None = None,
    citation: bool | None = None,
    settings: Settings | None = None,
    core: CoreFn = search,
) -> dict[str, object]:
    root = Path(repo_root) if repo_root is not None else Path.cwd()
    try:
        effective_settings = settings or load_settings(
            overrides=SettingsOverrides(max_turns=max_turns),
        )
        if max_turns is not None and settings is not None:
            effective_settings = replace(settings, max_turns=max_turns)
        request = SearchRequest(
            query=query,
            repo_root=root,
            max_turns=effective_settings.max_turns,
            citation=True if citation is None else citation,
        )
        return core(request, effective_settings).to_dict()
    except SearchError as exc:
        return {"error": exc.to_dict()}


def create_server() -> Any:
    try:
        fastmcp_module = import_module("mcp.server.fastmcp")
    except ImportError as exc:
        raise SearchError(
            "CONFIG_INVALID",
            "MCP SDK is not installed; install flash-context[mcp]",
        ) from exc
    fast_mcp = fastmcp_module.FastMCP
    server = fast_mcp("flash-context")
    # FastMCP exposes no version argument; the low-level default is the SDK version.
    server._mcp_server.version = __version__

    @server.tool()  # type: ignore[untyped-decorator]
    def search_repository(
        query: str,
        repo_root: str | None = None,
        max_turns: int | None = None,
        citation: bool | None = None,
    ) -> dict[str, object]:
        """Find code or local text relevant to a focused repository question.

        Search read-only when implementation locations or supporting evidence
        are unknown. Return validated file-line citations and bounded source
        snippets, with warnings for incomplete search. repo_root defaults
        to the server's working directory.
        """
        return search_repository_handler(
            query=query,
            repo_root=repo_root,
            max_turns=max_turns,
            citation=citation,
        )

    return server


def run_mcp(*, transport: str = "stdio") -> None:
    server = create_server()
    server.run(transport=transport)

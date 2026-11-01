from __future__ import annotations

from collections.abc import Callable
from importlib import import_module
from pathlib import Path
from typing import Any

from flash_context.agent import explore
from flash_context.config import Settings, SettingsOverrides, load_settings
from flash_context.types import ExploreRequest, ExplorerError, ExploreResult

CoreFn = Callable[[ExploreRequest, Settings], ExploreResult]


def explore_repository_handler(
    *,
    query: str,
    repo_root: str | None = None,
    max_turns: int | None = None,
    citation: bool | None = None,
    settings: Settings | None = None,
    core: CoreFn = explore,
) -> dict[str, object]:
    root = Path(repo_root) if repo_root is not None else Path.cwd()
    try:
        effective_settings = settings or load_settings(
            repo_root=root,
            overrides=SettingsOverrides(max_turns=max_turns),
        )
        if max_turns is not None and settings is not None:
            effective_settings = Settings(
                base_url=settings.base_url,
                model=settings.model,
                api_key=settings.api_key,
                max_turns=max_turns,
                max_read_bytes=settings.max_read_bytes,
                max_grep_results=settings.max_grep_results,
                traj_dir=settings.traj_dir,
                ignore=settings.ignore,
                timeout_seconds=settings.timeout_seconds,
                max_observation_chars=settings.max_observation_chars,
                max_read_lines=settings.max_read_lines,
                max_completion_tokens=settings.max_completion_tokens,
                temperature=settings.temperature,
                max_parallel_tools=settings.max_parallel_tools,
            )
        request = ExploreRequest(
            query=query,
            repo_root=root,
            max_turns=effective_settings.max_turns,
            citation=True if citation is None else citation,
            format="json",
        )
        return core(request, effective_settings).to_dict()
    except ExplorerError as exc:
        return {"error": exc.to_dict()}


def create_server() -> Any:
    try:
        fastmcp_module = import_module("mcp.server.fastmcp")
    except ImportError as exc:
        raise ExplorerError(
            "CONFIG_INVALID",
            "MCP SDK is not installed; install flash-context[mcp]",
        ) from exc
    fast_mcp = fastmcp_module.FastMCP
    server = fast_mcp("flash-context")

    @server.tool()  # type: ignore[untyped-decorator]
    def explore_repository(
        query: str,
        repo_root: str | None = None,
        max_turns: int | None = None,
        citation: bool | None = None,
    ) -> dict[str, object]:
        return explore_repository_handler(
            query=query,
            repo_root=repo_root,
            max_turns=max_turns,
            citation=citation,
        )

    return server


def run_mcp(*, transport: str = "stdio") -> None:
    server = create_server()
    server.run(transport=transport)

"""Check an installed distribution without importing the source checkout."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from flash_context import __version__
from flash_context.config import _project_root
from flash_context.mcp_server import create_server


async def check_mcp() -> None:
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    params = StdioServerParameters(command="flash-context", args=["mcp"])
    async with (
        stdio_client(params) as (read, write),
        ClientSession(read, write) as session,
    ):
        result = await session.initialize()
        assert result.serverInfo.name == "flash-context"
        assert result.serverInfo.version == __version__
    tools = await create_server().list_tools()
    assert [tool.name for tool in tools] == ["explore_repository"]
    assert tools[0].inputSchema["required"] == ["query"]
    assert tools[0].description


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version")
    parser.add_argument("--mcp", action="store_true")
    args = parser.parse_args()
    assert __version__ == args.version
    assert _project_root() is None, "Smoke checks must use an installed distribution"
    subprocess.run(["flash-context", "--help"], check=True, capture_output=True)
    with TemporaryDirectory() as directory:
        repo = Path(directory)
        source = "def sample():\n    return 42\n"
        (repo / "sample.py").write_text(source, encoding="utf-8")
        (repo / "a_refs.py").write_text("ref = sample\n" * 20, encoding="utf-8")
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("FLASH_CONTEXT_")
        }
        for query, end_line in [("sample.py:1-2", 2), ("sample.py", 2), ("sample", 1)]:
            result = subprocess.run(
                [
                    "flash-context",
                    "explore",
                    "--repo",
                    directory,
                    "--query",
                    query,
                    "--format",
                    "json",
                ],
                cwd=repo,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
            payload = json.loads(result.stdout)
            assert payload["turns_used"] == 0
            assert payload["answer"] == (
                "sample.py:1-2" if end_line == 2 else "sample.py:1"
            )
            assert payload["citations"] == [
                {
                    "path": "sample.py",
                    "start_line": 1,
                    "end_line": end_line,
                    "precision": {
                        "range_lines": end_line,
                        "boundary_kind": "preview"
                        if query == "sample.py"
                        else "explicit_range"
                        if ":" in query
                        else "exact_match",
                        "symbol": None,
                        "query_token_in_range": None,
                        "definitions_spanned": None,
                    },
                }
            ]
            assert payload["raw_locations"] == [
                {
                    "path": "sample.py",
                    "start_line": 1,
                    "end_line": end_line,
                    "text": "".join(source.splitlines(keepends=True)[:end_line]),
                    "truncated": False,
                }
            ]
    if args.mcp:
        asyncio.run(check_mcp())
    else:
        result = subprocess.run(
            ["flash-context", "mcp"], capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 3
        assert "install flash-context[mcp]" in result.stderr
    print(f"Installed flash-context {__version__} smoke checks passed")


if __name__ == "__main__":
    main()

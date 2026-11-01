from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from flash_context.agent import explore, format_text_result
from flash_context.config import SettingsOverrides, load_settings
from flash_context.mcp_server import run_mcp
from flash_context.types import ExploreRequest, ExplorerError

_SCAN_LIMIT_WARNINGS = frozenset(
    {
        "glob scan budget exhausted",
        "grep scan budget exhausted",
        "read scan budget exhausted",
        "grep match timed out",
    }
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "explore":
        return _run_explore(args)
    if args.command == "mcp":
        return _run_mcp(args)
    parser.print_help()
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="flash-context")
    subparsers = parser.add_subparsers(dest="command")

    explore_parser = subparsers.add_parser("explore", help="explore a repository")
    explore_parser.add_argument("--query", required=True)
    explore_parser.add_argument("--repo", required=True, type=Path)
    explore_parser.add_argument("--max-turns", type=int)
    explore_parser.add_argument("--citation", action="store_true", default=True)
    explore_parser.add_argument("--format", choices=("text", "json"), default="text")

    mcp_parser = subparsers.add_parser("mcp", help="run the MCP adapter")
    mcp_parser.add_argument("--transport", default="stdio", choices=("stdio",))
    return parser


def _run_explore(args: argparse.Namespace) -> int:
    try:
        repo_root = args.repo.resolve()
        overrides = SettingsOverrides(max_turns=args.max_turns)
        settings = load_settings(repo_root=repo_root, overrides=overrides)
        request = ExploreRequest(
            query=args.query,
            repo_root=repo_root,
            max_turns=settings.max_turns,
            citation=args.citation,
            format=args.format,
        )
        result = explore(request, settings)
    except ExplorerError as exc:
        print(f"{exc.code}: {exc.message}", file=sys.stderr)
        return _exit_code(exc)

    if args.format == "json":
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    else:
        print(format_text_result(result, citation=args.citation))
    for warning in result.warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    if result.truncated and not result.warnings:
        print("WARNING: Result truncated", file=sys.stderr)
    if not result.citations and _SCAN_LIMIT_WARNINGS.intersection(result.warnings):
        return 6
    return 0


def _run_mcp(args: argparse.Namespace) -> int:
    try:
        run_mcp(transport=args.transport)
    except ExplorerError as exc:
        print(f"{exc.code}: {exc.message}", file=sys.stderr)
        return _exit_code(exc)
    return 0


def _exit_code(error: ExplorerError) -> int:
    if error.code.startswith("CONFIG_") or error.code == "QUERY_EMPTY":
        return 3 if error.code.startswith("CONFIG_") else 2
    if error.code.startswith("PATH_") or error.code == "REPO_NOT_FOUND":
        return 4
    if error.code.startswith("ENDPOINT_"):
        return 5
    return 6


if __name__ == "__main__":
    raise SystemExit(main())

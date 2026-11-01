"""Resolve model anchors to bounded syntax evidence; never infer relevance."""

from __future__ import annotations

import re
import warnings
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import cast

from tree_sitter import Node, Parser
from tree_sitter_language_pack import SupportedLanguage, get_language

from flash_context.config import Settings
from flash_context.tools import read_file
from flash_context.tools.safety import ScanBudget
from flash_context.types import Citation, CitationPrecision, ExplorerError

LANGUAGES = {
    "py": "python",
    "pyi": "python",
    "js": "javascript",
    "jsx": "javascript",
    "mjs": "javascript",
    "cjs": "javascript",
    "ts": "typescript",
    "tsx": "tsx",
    "go": "go",
    "rs": "rust",
    "java": "java",
    "c": "c",
    "h": "cpp",
    "cpp": "cpp",
    "cc": "cpp",
    "cxx": "cpp",
    "hpp": "cpp",
    "hh": "cpp",
    "cs": "csharp",
    "rb": "ruby",
    "php": "php",
    "sh": "bash",
    "bash": "bash",
    "lua": "lua",
    "kt": "kotlin",
    "kts": "kotlin",
    "swift": "swift",
}
DEFINITIONS = frozenset(
    {
        "function_definition",
        "class_definition",
        "function_declaration",
        "method_definition",
        "method_declaration",
        "constructor_declaration",
        "class_declaration",
        "interface_declaration",
        "struct_item",
        "enum_item",
        "trait_item",
        "function_item",
        "class_specifier",
        "struct_specifier",
        "method",
        "singleton_method",
        "class",
        "module",
        "arrow_function",
        "function_expression",
        "anonymous_function",
        "protocol_declaration",
    }
)
PATH = r"(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+"
ANCHOR = re.compile(
    rf"(?<![\w./-])(?P<path>{PATH})(?:#(?P<symbol>[A-Za-z_$][\w$]*(?:[.:]+[\w$]+)*)|:(?P<line>[1-9][0-9]*)(?P<range>-[0-9]+)?)(?![\w-])"
)


@dataclass(frozen=True, slots=True)
class Region:
    start: int
    end: int
    kind: str
    symbol: str | None = None


@dataclass(slots=True)
class Source:
    lines: list[str]
    regions: list[Region] | None


def _name(node: Node) -> str | None:
    name = node.child_by_field_name("name")
    if name is not None:
        return name.text.decode("utf-8") if name.text else None
    declarator = node.child_by_field_name("declarator")
    while declarator is not None:
        if declarator.type in {
            "identifier",
            "field_identifier",
            "qualified_identifier",
        }:
            return declarator.text.decode("utf-8") if declarator.text else None
        declarator = declarator.child_by_field_name("declarator")
    if node.type in {"arrow_function", "function_expression", "anonymous_function"}:
        parent = node.parent
        if parent is not None and parent.type in {
            "variable_declarator",
            "assignment_expression",
        }:
            return _name(parent)
    # Kotlin and Swift use a named identifier child rather than a name field.
    for child in node.named_children:
        if child.type in {"simple_identifier", "type_identifier"}:
            return child.text.decode("utf-8") if child.text else None
    return None


def _end(node: Node) -> int:
    return node.end_point.row + int(node.end_point.column > 0)


class CitationResolver:
    def __init__(self, root: Path, settings: Settings, token: str | None) -> None:
        self.root = root
        self.settings = settings
        self.token = token
        self.sources: dict[str, Source | None] = {}
        self.bytes_read = 0
        self.feedback: list[str] = []
        self.warnings: list[str] = []
        self.repaired = False

    def source(self, path: str) -> Source | None:
        if path in self.sources:
            return self.sources[path]
        self.sources[path] = None
        cap = min(
            self.settings.max_parse_bytes,
            self.settings.max_scan_bytes - self.bytes_read,
        )
        if cap <= 0:
            return None
        try:
            observation = read_file(
                repo_root=self.root,
                path=path,
                max_bytes=cap,
                ignore=self.settings.ignore,
                limits=self.settings.limits,
            )
        except ExplorerError as exc:
            if exc.code == "TOOL_LIMIT_EXCEEDED":
                self.warnings.append("read scan budget exhausted")
            return None
        self.warnings.extend(observation.warnings)
        text = observation.content or ""
        self.bytes_read += len(text.encode("utf-8"))
        lines = list(StringIO(text, newline="\n"))
        if observation.truncated and lines and not lines[-1].endswith("\n"):
            lines.pop()
        language = LANGUAGES.get(Path(path).suffix.lstrip(".").lower())
        regions: list[Region] | None = None
        if language and not observation.truncated:
            grammar = get_language(cast(SupportedLanguage, language))
            data = text.encode("utf-8")
            budget = ScanBudget(self.settings.limits)
            try:
                # Native timeout avoids callback crashes on malformed input in 0.25.2.
                with warnings.catch_warnings(
                    action="ignore", category=DeprecationWarning
                ):
                    parser = Parser(
                        grammar,
                        timeout_micros=max(
                            1, int(budget.remaining_seconds() * 1_000_000)
                        ),
                    )
                tree = parser.parse(data)
                if not tree.root_node.has_error:
                    regions = []
                    stack: list[tuple[Node, tuple[str, ...]]] = [(tree.root_node, ())]
                    while stack:
                        budget.consume()
                        node, scope = stack.pop()
                        start, end = node.start_point.row + 1, _end(node)
                        name = _name(node) if node.type in DEFINITIONS else None
                        qualified = ".".join((*scope, name)) if name else None
                        if node.type in DEFINITIONS and name:
                            wrapper = node.parent
                            if wrapper and wrapper.type in {
                                "decorated_definition",
                                "export_statement",
                            }:
                                start, end = wrapper.start_point.row + 1, _end(wrapper)
                            regions.append(Region(start, end, "definition", qualified))
                            body = node.child_by_field_name("body")
                            if body is not None:
                                regions.append(
                                    Region(
                                        start,
                                        max(start, body.start_point.row),
                                        "syntax",
                                        qualified,
                                    )
                                )
                        elif (
                            (
                                node.parent is not None
                                and node.parent.type
                                in {"module", "program", "source_file"}
                            )
                            or node.type.endswith(("_statement", "_declaration"))
                            or node.type
                            in {
                                "block",
                                "assignment",
                                "return",
                                "lexical_declaration",
                            }
                        ):
                            regions.append(Region(start, end, "syntax"))
                        scope_name = name
                        if node.type in {
                            "impl_item",
                            "namespace_definition",
                            "namespace_declaration",
                        }:
                            scope_node = node.child_by_field_name(
                                "type"
                            ) or node.child_by_field_name("name")
                            if scope_node is not None and scope_node.text:
                                scope_name = scope_node.text.decode("utf-8").replace(
                                    "::", "."
                                )
                        child_scope = (*scope, scope_name) if scope_name else scope
                        stack.extend(
                            (child, child_scope)
                            for child in reversed(node.named_children)
                        )
            except (ValueError, ExplorerError):
                regions = None
        source = Source(lines, regions)
        self.sources[path] = source
        return source

    def resolve(
        self, path: str, *, symbol: str | None = None, line: int | None = None
    ) -> Citation | None:
        source = self.source(path)
        if source is None:
            self.feedback.append(
                "Anchor could not be read within repository safety and parser limits."
            )
            return None
        region = None
        if symbol:
            matches = [
                r
                for r in source.regions or []
                if r.kind == "definition"
                and (r.symbol == symbol or (r.symbol or "").split(".")[-1] == symbol)
            ]
            if len(matches) == 1:
                region = matches[0]
            else:
                self.feedback.append(
                    "Symbol missing, ambiguous, or unavailable: qualify its name or "
                    "choose a line anchor."
                )
                return None
        elif line is not None and 1 <= line <= len(source.lines):
            containing = [r for r in source.regions or [] if r.start <= line <= r.end]
            definitions = [r for r in containing if r.kind == "definition"]
            if definitions:
                region = min(definitions, key=lambda r: r.end - r.start)
            if (
                region is None
                or region.end - region.start + 1 > self.settings.max_citation_lines
            ):
                small = [
                    r
                    for r in containing
                    if r.kind == "syntax"
                    and r.end - r.start + 1 <= self.settings.max_citation_lines
                ]
                region = min(small, key=lambda r: r.end - r.start) if small else None
            if region is None and source.regions is None:
                radius = min(5, (self.settings.max_citation_lines - 1) // 2)
                region = Region(
                    max(1, line - radius),
                    min(len(source.lines), line + radius),
                    "line_window",
                )
        if region is None:
            self.feedback.append(
                "No bounded syntax region contains the anchor; choose another line."
            )
            return None
        count = region.end - region.start + 1
        if count > self.settings.max_citation_lines:
            self.feedback.append(
                f"Definition spans {count} lines, max "
                f"{self.settings.max_citation_lines}; "
                "choose a line inside a smaller syntax region."
            )
            return None
        text = "".join(source.lines[region.start - 1 : region.end])
        present = (
            bool(re.search(rf"\b{re.escape(self.token)}\b", text))
            if self.token
            else None
        )
        if present is False:
            self.feedback.append(
                "Cited region must contain the exact whole query token."
            )
            return None
        definitions_spanned = (
            sum(
                r.kind == "definition"
                and r.start >= region.start
                and r.end <= region.end
                for r in source.regions
            )
            if source.regions is not None
            else None
        )
        return Citation(
            path,
            region.start,
            region.end,
            CitationPrecision(
                count, region.kind, region.symbol, present, definitions_spanned
            ),
        )

    def parse(self, content: str) -> list[Citation]:
        self.feedback.clear()
        citations = []
        for index, match in enumerate(ANCHOR.finditer(content)):
            if index >= 16:
                self.feedback.append("At most 16 anchor candidates can be verified.")
                break
            if match["range"]:
                self.feedback.append(
                    "Model ranges are unsupported; name symbols or individual line "
                    "anchors."
                )
                continue
            citation = self.resolve(
                match["path"],
                symbol=match["symbol"],
                line=int(match["line"]) if match["line"] else None,
            )
            if citation is not None:
                citations.append(citation)
        return self.limit(citations)

    def limit(self, citations: list[Citation]) -> list[Citation]:
        accepted: list[Citation] = []
        coverage: set[tuple[str, int]] = set()
        for citation in citations:
            if citation in accepted:
                continue
            assert citation.start_line is not None and citation.end_line is not None
            lines = {
                (citation.path, n)
                for n in range(citation.start_line, citation.end_line + 1)
            }
            if (
                len(accepted) == 12
                or len(coverage | lines) > self.settings.max_total_citation_lines
            ):
                self.feedback.append(
                    f"Answer exceeds 12 citations or "
                    f"{self.settings.max_total_citation_lines} total lines; "
                    "select fewer anchors."
                )
                continue
            coverage |= lines
            accepted.append(citation)
        return accepted


def render_answer(answer: str, citations: list[Citation]) -> str:
    """Replace accepted anchors in prose without exposing unchecked references."""

    def render(match: re.Match[str]) -> str:
        if match["range"]:
            return ""
        for citation in citations:
            if citation.path != match["path"]:
                continue
            symbol = citation.precision.symbol if citation.precision else None
            if (
                match["symbol"]
                and symbol
                and match["symbol"] in {symbol, symbol.split(".")[-1]}
            ):
                return citation.label()
            if match["line"] and (citation.start_line or 0) <= int(match["line"]) <= (
                citation.end_line or 0
            ):
                return citation.label()
        return ""

    return (
        ANCHOR.sub(render, answer)
        .replace("<final_answer>", "")
        .replace("</final_answer>", "")
        .strip()
    )

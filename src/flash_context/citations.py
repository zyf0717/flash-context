"""Resolve model anchors to bounded syntax evidence; never infer relevance."""

from __future__ import annotations

import re
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, cast

from tree_sitter import Node, Parser
from tree_sitter_language_pack import SupportedLanguage, get_language

from flash_context.config import Settings
from flash_context.tools import read_file
from flash_context.tools.safety import ScanBudget
from flash_context.types import (
    MAX_ANCHORS,
    MAX_CITATIONS,
    Citation,
    CitationPrecision,
    Diagnostic,
    RawLocation,
    SearchError,
    source_lines,
)

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
    status: Literal["parsed", "unsupported", "invalid", "limited", "timeout"]
    warnings: list[Diagnostic] = field(default_factory=list)


@dataclass(slots=True)
class Resolution:
    citations: list[Citation] = field(default_factory=list)
    anchors: dict[str, list[Citation]] = field(default_factory=dict)
    feedback: list[str] = field(default_factory=list)
    warnings: list[Diagnostic] = field(default_factory=list)

    def render(self, answer: str) -> str:
        return (
            ANCHOR.sub(
                lambda m: ", ".join(c.label() for c in self.anchors.get(m[0], [])),
                answer,
            )
            .replace("<final_answer>", "")
            .replace("</final_answer>", "")
            .strip()
        )


class AnchorRejected(ValueError):
    """An anchor requires correction by the model."""


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
        self.sources: dict[str, Source] = {}
        self.bytes_read = 0

    def source(self, path: str) -> Source:
        if path in self.sources:
            return self.sources[path]
        cap = min(
            self.settings.max_parse_bytes,
            self.settings.max_scan_bytes - self.bytes_read,
        )
        if cap <= 0:
            source = Source([], None, "limited", [Diagnostic.READ_LIMIT])
            self.sources[path] = source
            return source
        try:
            observation = read_file(
                repo_root=self.root,
                path=path,
                max_bytes=cap,
                ignore=self.settings.ignore,
                limits=self.settings.limits,
            )
        except SearchError as exc:
            if exc.code == "TOOL_LIMIT_EXCEEDED":
                source = Source([], None, "limited", [Diagnostic.READ_LIMIT])
                self.sources[path] = source
                return source
            raise AnchorRejected(
                "Anchor could not be read within repository safety and parser limits."
            ) from exc
        text = observation.content or ""
        self.bytes_read += len(text.encode("utf-8"))
        lines = source_lines(text)
        if observation.truncated and lines and not lines[-1].endswith("\n"):
            lines.pop()
        language = LANGUAGES.get(Path(path).suffix.lstrip(".").lower())
        regions: list[Region] | None = None
        status: Literal["parsed", "unsupported", "invalid", "limited", "timeout"] = (
            "limited" if observation.truncated else "unsupported"
        )
        diagnostics = list(observation.warnings)
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
                status = "invalid" if tree.root_node.has_error else "parsed"
                if status == "parsed":
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
            except (ValueError, SearchError):
                regions = None
                status = "timeout"
        if status == "limited":
            diagnostics.append(Diagnostic.PARSER_INPUT_LIMIT)
        elif status == "timeout":
            diagnostics.append(Diagnostic.PARSER_TIMEOUT)
        source = Source(lines, regions, status, diagnostics)
        self.sources[path] = source
        return source

    def _resolve(
        self, path: str, *, symbol: str | None = None, line: int | None = None
    ) -> Citation:
        source = self.source(path)
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
                raise AnchorRejected(
                    "Symbol missing, ambiguous, or unavailable: qualify its name or "
                    "choose a line anchor."
                )
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
            raise AnchorRejected(
                "No bounded syntax region contains the anchor; choose another line."
            )
        return self._citation(path, source, region)

    def _citation(self, path: str, source: Source, region: Region) -> Citation:
        count = region.end - region.start + 1
        if count > self.settings.max_citation_lines:
            raise AnchorRejected(
                f"Definition spans {count} lines, max "
                f"{self.settings.max_citation_lines}; "
                "choose a line inside a smaller syntax region."
            )
        text = "".join(source.lines[region.start - 1 : region.end])
        present = (
            bool(re.search(rf"\b{re.escape(self.token)}\b", text))
            if self.token
            else None
        )
        if present is False:
            raise AnchorRejected(
                "Cited region must contain the exact whole query token."
            )
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

    def _range(self, path: str, start: int, end: int) -> list[Citation]:
        source = self.source(path)
        if not 1 <= start <= end <= len(source.lines):
            raise AnchorRejected("Range bounds must be ordered and within the file.")
        if source.regions is None:
            raise AnchorRejected(
                "Range has no parsed boundaries; choose a line anchor."
            )
        bounded = [
            r
            for r in source.regions
            if r.end - r.start + 1 <= self.settings.max_citation_lines
        ]
        contained = [r for r in bounded if start <= r.start and r.end <= end]
        candidates = [r for r in contained if r.kind == "definition"]
        if not candidates:
            enclosing = [r for r in bounded if r.start <= start and end <= r.end]
            if enclosing:
                definitions = [r for r in enclosing if r.kind == "definition"]
                candidates = [
                    min(definitions or enclosing, key=lambda r: r.end - r.start)
                ]
            else:
                candidates = contained
        # Prefer complete outer units, retaining separate adjacent definitions.
        ordered = sorted(candidates, key=lambda r: (r.start, -r.end))
        regions: list[Region] = []
        for region in ordered:
            if not regions or region.end > regions[-1].end:
                regions.append(region)
        citations = []
        for region in regions:
            try:
                citations.append(self._citation(path, source, region))
            except AnchorRejected:
                # Exact queries can only select units containing the whole token.
                continue
        if not citations:
            raise AnchorRejected(
                "No bounded verified syntax units; choose a line anchor."
            )
        return citations

    def parse(self, content: str) -> Resolution:
        result = Resolution()
        for index, match in enumerate(ANCHOR.finditer(content)):
            try:
                if index >= MAX_ANCHORS:
                    raise AnchorRejected(
                        f"At most {MAX_ANCHORS} anchor candidates can be verified."
                    )
                candidates = (
                    self._range(
                        match["path"], int(match["line"]), int(match["range"][1:])
                    )
                    if match["range"]
                    else [
                        self._resolve(
                            match["path"],
                            symbol=match["symbol"],
                            line=int(match["line"]) if match["line"] else None,
                        )
                    ]
                )
                combined = list(dict.fromkeys([*result.citations, *candidates]))
                coverage = {
                    (c.path, n)
                    for c in combined
                    for n in range(c.start_line, c.end_line + 1)
                }
                if (
                    len(combined) > MAX_CITATIONS
                    or len(coverage) > self.settings.max_total_citation_lines
                ):
                    example = candidates[0]
                    raise AnchorRejected(
                        f"Answer exceeds {MAX_CITATIONS} citations or "
                        f"{self.settings.max_total_citation_lines} total lines; "
                        "select fewer anchors. Example of a narrower selection: "
                        f"<final_answer>\n{example.path}:{example.start_line}\n</final_answer>"
                    )
                result.citations = combined
                result.anchors[match[0]] = candidates
            except AnchorRejected as exc:
                feedback = str(exc)
                if "Example" not in feedback:
                    feedback += (
                        " Example format: <final_answer>\nsrc/example.py:42\n"
                        "</final_answer>. "
                        "Use an actual path and line from the observations."
                    )
                result.feedback.append(feedback)
            if index >= MAX_ANCHORS:
                break
        paths = dict.fromkeys(m["path"] for m in ANCHOR.finditer(content))
        result.warnings = list(
            dict.fromkeys(
                warning
                for path in paths
                if path in self.sources
                for warning in self.sources[path].warnings
            )
        )
        return result

    def snippet(self, citation: Citation) -> RawLocation:
        """Return the same source snapshot that supplied the citation metadata."""
        source = self.sources[citation.path]
        text = "".join(source.lines[citation.start_line - 1 : citation.end_line])
        data = text.encode("utf-8")
        truncated = len(data) > self.settings.max_read_bytes
        text = data[: self.settings.max_read_bytes].decode("utf-8", errors="ignore")
        return RawLocation(
            citation.path,
            citation.start_line,
            citation.start_line + max(1, len(source_lines(text))) - 1,
            text,
            truncated,
        )

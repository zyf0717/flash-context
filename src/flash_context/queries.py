"""Classify lookup intent and share symbol/line anchor syntax."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from flash_context.types import Citation

PATH = r"(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+"
ANCHOR = re.compile(
    rf"(?<![\w./-])(?P<path>{PATH})(?:#(?P<symbol>[A-Za-z_$][\w$]*(?:[.:]+[\w$]+)*)|:(?P<line>[1-9][0-9]*)(?P<range>-[0-9]+)?)(?![\w-])"
)

CITATION_RE = re.compile(
    r"(?P<path>(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+)"
    r":(?P<start>[1-9][0-9]*)(?:-(?P<end>[1-9][0-9]*))?"
)


SOURCE_LINES_RE = re.compile(
    r"`?(?P<path>(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\.[A-Za-z0-9_.-]+)`?"
    r",?\s+lines?\s+"
    r"(?P<start>[1-9][0-9]*)"
    r"(?:\s*[-\u2013\u2014]\s*(?P<end>[1-9][0-9]*))?",
    re.IGNORECASE,
)


LINES_OF_SOURCE_RE = re.compile(
    r"lines?\s+"
    r"(?P<start>[1-9][0-9]*)"
    r"(?:\s*[-\u2013\u2014]\s*(?P<end>[1-9][0-9]*))?"
    r"\s+of\s+"
    r"`?(?P<path>(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\.[A-Za-z0-9_.-]+)`?",
    re.IGNORECASE,
)


MARKDOWN_FILE_LINES_RE = re.compile(
    r"File\**\s*:\s*`?"
    r"(?P<path>(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\.[A-Za-z0-9_.-]+)`?"
    r".{0,120}?"
    r"Lines\**\s*:\s*"
    r"(?P<start>[1-9][0-9]*)"
    r"(?:\s*[-\u2013\u2014]\s*(?P<end>[1-9][0-9]*))?",
    re.IGNORECASE | re.DOTALL,
)


EXPLICIT_PATH_RE = re.compile(
    r"`?(?P<path>(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+\.[A-Za-z0-9_.-]+)`?"
)


EXACT_TEXT_RE = re.compile(r"[`'\"](?P<target>[^`'\"]{1,120})[`'\"]")


TOKEN_RE = re.compile(r"\b(?P<token>[A-Za-z_][A-Za-z0-9_]*)\b")


LOOKUP_WORDS = frozenset(
    [
        "find",
        "return",
        "show",
        "use",
        "in",
        "the",
        "definition",
        "of",
        "function",
        "class",
        "symbol",
        "file",
        "line",
        "lines",
        "citations",
        "only",
        "where",
        "def",
    ]
)


@dataclass(frozen=True, slots=True)
class QueryIntent:
    exact: bool
    path: str | None
    target: str | None
    symbol: str | None
    prefer_source: bool
    ranges: tuple[Citation, ...]
    symbol_anchor: str | None = None

    @classmethod
    def parse(cls, query: str) -> QueryIntent:
        anchor = query.strip()
        if len(anchor) >= 2 and anchor[0] in "`'\"" and anchor[-1] == anchor[0]:
            anchor = anchor[1:-1]
        match = ANCHOR.fullmatch(anchor)
        if match is not None and match["symbol"]:
            return cls(
                exact=True,
                path=match["path"],
                target=None,
                symbol=None,
                prefer_source=False,
                ranges=(),
                symbol_anchor=anchor,
            )
        paths = list(EXPLICIT_PATH_RE.finditer(query))
        quotes = list(EXACT_TEXT_RE.finditer(query))
        ranges = extract_citations(query)
        remainder = query
        for regex in (CITATION_RE, EXPLICIT_PATH_RE, EXACT_TEXT_RE):
            remainder = regex.sub(" ", remainder)
        unknown = [
            m[0]
            for m in TOKEN_RE.finditer(remainder)
            if m[0].lower() not in LOOKUP_WORDS
        ]
        exact = (
            len(paths) <= 1
            and len(quotes) <= 1
            and (not unknown if paths or quotes or ranges else len(unknown) == 1)
        )
        path = paths[0]["path"].rstrip(".,;:)") if paths else None
        target = (
            quotes[0]["target"].strip()
            if quotes
            else (unknown[0] if len(unknown) == 1 else None)
        )
        if target == path or (path and target == Path(path).stem):
            target = None
        symbol = (
            target
            if exact
            and not ranges
            and target
            and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", target)
            else None
        )
        prefer_source = (
            not exact
            and not re.search(
                r"\b(?:docs?|documentation|markdown|readme)\b", query, re.IGNORECASE
            )
            and bool(
                re.search(
                    r"\b(?:implement\w*|handl\w*|code|functions?|methods?|classes|class)\b",
                    query,
                    re.IGNORECASE,
                )
            )
        )
        return cls(
            exact, path, target if exact else None, symbol, prefer_source, tuple(ranges)
        )


def extract_citations(answer: str) -> list[Citation]:
    return list(
        dict.fromkeys(
            _citation_from_match(match)
            for regex in (
                CITATION_RE,
                SOURCE_LINES_RE,
                LINES_OF_SOURCE_RE,
                MARKDOWN_FILE_LINES_RE,
            )
            for match in regex.finditer(answer)
        )
    )


def _citation_from_match(match: re.Match[str]) -> Citation:
    path = match.group("path")
    start = int(match.group("start"))
    end_text = match.group("end")
    end = int(end_text) if end_text is not None else start
    return Citation(path=path, start_line=start, end_line=end)

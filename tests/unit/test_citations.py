from __future__ import annotations

from flash_context.agent import _merge_adjacent_citations, extract_citations
from flash_context.types import Citation


def test_extract_colon_range_citation() -> None:
    citations = extract_citations("src/flash_context/types.py:129-158")

    assert citations[0].path == "src/flash_context/types.py"
    assert citations[0].start_line == 129
    assert citations[0].end_line == 158


def test_extract_source_lines_citation_with_en_dash() -> None:
    citations = extract_citations(
        "Source: `src/flash_context/types.py`, lines 140\u2013166."
    )

    assert citations[0].path == "src/flash_context/types.py"
    assert citations[0].start_line == 140
    assert citations[0].end_line == 166


def test_extract_lines_of_source_citation() -> None:
    citations = extract_citations(
        "It is located at lines 135-159 of `src/flash_context/types.py`."
    )

    assert citations[0].path == "src/flash_context/types.py"
    assert citations[0].start_line == 135
    assert citations[0].end_line == 159


def test_extract_markdown_file_lines_citation() -> None:
    citations = extract_citations(
        "- **File**: `src/flash_context/types.py`\n"
        "- **Lines**: 125\u2013140"
    )

    assert citations[0].path == "src/flash_context/types.py"
    assert citations[0].start_line == 125
    assert citations[0].end_line == 140


def test_merge_adjacent_citations_merges_overlapping_and_adjacent_ranges() -> None:
    citations = _merge_adjacent_citations(
        [
            Citation("a.py", 7, 10),
            Citation("a.py", 1, 3),
            Citation("a.py", 4, 8),
        ]
    )

    assert citations == [Citation("a.py", 1, 10)]


def test_merge_adjacent_citations_keeps_disjoint_and_cross_file_ranges() -> None:
    citations = _merge_adjacent_citations(
        [
            Citation("b.py", 20, 21),
            Citation("a.py", 5, 6),
            Citation("b.py", 1, 2),
            Citation("a.py", 8, 9),
        ]
    )

    assert citations == [
        Citation("b.py", 1, 2),
        Citation("b.py", 20, 21),
        Citation("a.py", 5, 6),
        Citation("a.py", 8, 9),
    ]

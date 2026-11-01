from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

from flash_context.config import Settings
from flash_context.llm import ChatClient
from flash_context.logging import TrajectoryRecorder
from flash_context.tools import read_file, repo_glob, repo_grep
from flash_context.types import (
    Citation,
    ExploreRequest,
    ExplorerError,
    ExploreResult,
    RawLocation,
    ToolCall,
    ToolObservation,
)

ToolName = Literal["read_file", "repo_glob", "repo_grep"]

ALLOWED_TOOLS: set[ToolName] = {"read_file", "repo_glob", "repo_grep"}
MAX_FINAL_CITATIONS = 5
NO_CITATIONS_FOUND = "NO_CITATIONS_FOUND"
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
BACKTICK_OR_QUOTE_RE = re.compile(
    r"[`'\"](?P<token>[A-Za-z_][A-Za-z0-9_]*)[`'\"]"
)
EXACT_TEXT_RE = re.compile(r"[`'\"](?P<target>[^`'\"]{1,120})[`'\"]")
TOKEN_RE = re.compile(r"\b(?P<token>[A-Za-z_][A-Za-z0-9_]*)\b")
SEMANTIC_QUERY_RE = re.compile(
    r"\b(why|how|compare|comparison|synthesize|interpret|explain|behavior|"
    r"behaviour|architecture|owner|ownership|relationship|tradeoff|flow)\b",
    re.IGNORECASE,
)


@dataclass(slots=True)
class EvidenceState:
    reads: list[ToolObservation] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    seen_tool_calls: set[str] = field(default_factory=set)
    repeated_tool_calls: int = 0


def explore(
    request: ExploreRequest,
    settings: Settings,
    *,
    client: ChatClient | None = None,
) -> ExploreResult:
    request.validate()
    repo_root = request.repo_root.resolve()
    fast_result = _try_exact_fast_path(
        request,
        repo_root=repo_root,
        settings=settings,
    )
    if fast_result is not None:
        return fast_result
    settings.require_endpoint()
    effective_max_turns = min(request.max_turns, settings.max_turns)
    recorder = TrajectoryRecorder(settings.traj_dir, request)
    owns_client = client is None
    chat_client = client or ChatClient(settings)
    file_sample = repo_glob(
        repo_root=repo_root,
        pattern="**/*",
        max_results=settings.max_grep_results,
        ignore=settings.ignore,
    )
    messages = _initial_messages(request, file_sample, settings)
    tools = tool_schemas()
    truncated = False
    warnings: list[str] = []
    last_content = ""
    evidence = EvidenceState()

    try:
        for turn in range(1, effective_max_turns + 1):
            response = chat_client.chat_completion(messages=messages, tools=tools)
            message = _extract_message(response)
            recorder.record_model_turn(turn, message)
            content_text = str(message.get("content") or "").strip()
            if content_text:
                last_content = content_text
                citations = _validated_citations_from_content(
                    content_text,
                    repo_root=repo_root,
                    settings=settings,
                    evidence=evidence,
                    warnings=warnings,
                )
                if citations:
                    evidence.citations = citations
                    if _message_has_tool_calls(message):
                        _append_warning_once(
                            warnings,
                            "ignored trailing tool calls after valid citations",
                        )
                    result = _finalize_result(
                        request=request,
                        repo_root=repo_root,
                        settings=settings,
                        answer=content_text,
                        citations=citations,
                        turns_used=turn,
                        truncated=truncated,
                        warnings=warnings,
                    )
                    recorder.finish(result=result)
                    return result

            tool_calls = _extract_tool_calls(message)
            if not tool_calls:
                citations = _best_current_citations(evidence)
                if request.citation and content_text != NO_CITATIONS_FOUND:
                    _append_warning_once(
                        warnings,
                        "final answer did not include valid citations",
                    )
                result = _finalize_result(
                    request=request,
                    repo_root=repo_root,
                    settings=settings,
                    answer=content_text,
                    citations=citations,
                    turns_used=turn,
                    truncated=truncated,
                    warnings=warnings,
                )
                recorder.finish(result=result)
                return result

            if _should_finalize_before_tool_calls(
                request,
                evidence,
                tool_calls,
                settings,
            ):
                _append_warning_once(
                    warnings,
                    "sufficient narrow evidence stopped broad read",
                )
                result = _finalize_result(
                    request=request,
                    repo_root=repo_root,
                    settings=settings,
                    answer=last_content,
                    citations=_best_current_citations(evidence),
                    turns_used=turn,
                    truncated=truncated,
                    warnings=warnings,
                )
                recorder.finish(result=result)
                return result

            repeated_call = _first_repeated_tool_call(evidence, tool_calls)
            if repeated_call is not None:
                evidence.repeated_tool_calls += 1
                _append_warning_once(
                    warnings,
                    "repeated tool call stopped exploration",
                )
                citations = _best_current_citations(evidence)
                result = _finalize_result(
                    request=request,
                    repo_root=repo_root,
                    settings=settings,
                    answer=last_content,
                    citations=citations,
                    turns_used=turn,
                    truncated=truncated,
                    warnings=warnings,
                )
                recorder.finish(result=result)
                return result
            for tool_call in tool_calls:
                evidence.seen_tool_calls.add(_tool_call_fingerprint(tool_call))

            messages.append(_assistant_tool_message(message))
            observations = _execute_tool_calls_parallel(
                tool_calls,
                repo_root=repo_root,
                settings=settings,
            )
            for tool_call, observation in zip(tool_calls, observations, strict=True):
                observation.tool_call_id = tool_call.id
                truncated = truncated or observation.truncated
                if (
                    tool_call.name == "read_file"
                    and observation.ok
                    and observation.path
                    and observation.line_range
                ):
                    evidence.reads.append(observation)
                recorder.record_observation(turn, tool_call.name, observation)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_call.name,
                        "content": json.dumps(
                            _model_observation_payload(
                                observation,
                                max_chars=settings.max_observation_chars,
                            ),
                            sort_keys=True,
                        ),
                    }
                )
        if last_content:
            citations = _validated_citations_from_content(
                last_content,
                repo_root=repo_root,
                settings=settings,
                evidence=evidence,
                warnings=warnings,
            ) or _citations_from_observations(
                last_content,
                evidence.reads,
            )
            _append_warning_once(warnings, "max turns exceeded after partial answer")
            if request.citation and not citations:
                _append_warning_once(
                    warnings,
                    "partial answer did not include valid citations",
                )
            result = _finalize_result(
                request=request,
                repo_root=repo_root,
                settings=settings,
                answer=last_content,
                citations=citations,
                turns_used=effective_max_turns,
                truncated=truncated,
                warnings=warnings,
            )
            recorder.finish(result=result)
            return result
        citations = _best_current_citations(evidence)
        _append_warning_once(warnings, "max turns exceeded without final answer")
        result = _finalize_result(
            request=request,
            repo_root=repo_root,
            settings=settings,
            answer="",
            citations=citations,
            turns_used=effective_max_turns,
            truncated=truncated,
            warnings=warnings,
        )
        recorder.finish(result=result)
        return result
    except ExplorerError as exc:
        recorder.finish(error=exc)
        raise
    finally:
        if owns_client:
            chat_client.close()


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


def format_text_result(result: ExploreResult, *, citation: bool) -> str:
    if citation:
        return _citation_text(result.citations)
    return result.answer


def _finalize_result(
    *,
    request: ExploreRequest,
    repo_root: Path,
    settings: Settings,
    answer: str,
    citations: list[Citation],
    turns_used: int,
    truncated: bool,
    warnings: list[str],
) -> ExploreResult:
    citations = _merge_adjacent_citations(citations)[:MAX_FINAL_CITATIONS]
    if request.citation or (not answer and citations):
        answer = _citation_text(citations)
    raw_locations = _extract_raw_locations(
        citations,
        repo_root=repo_root,
        settings=settings,
        warnings=warnings,
    )
    return ExploreResult(
        query=request.query,
        repo_root=str(repo_root),
        answer=answer,
        citations=citations,
        raw_locations=raw_locations,
        turns_used=turns_used,
        truncated=truncated,
        warnings=warnings,
    )


def _citation_text(citations: list[Citation]) -> str:
    if not citations:
        return NO_CITATIONS_FOUND
    return "\n".join(citation.label() for citation in citations)


def _merge_adjacent_citations(citations: list[Citation]) -> list[Citation]:
    grouped: dict[str, list[tuple[int, Citation]]] = {}
    path_order: list[str] = []
    non_mergeable: list[Citation] = []
    for index, citation in enumerate(citations):
        if citation.start_line is None or citation.end_line is None:
            non_mergeable.append(citation)
            continue
        if citation.path not in grouped:
            grouped[citation.path] = []
            path_order.append(citation.path)
        grouped[citation.path].append((index, citation))

    merged: list[Citation] = []
    for path in path_order:
        ranges = sorted(
            grouped[path],
            key=lambda item: (
                item[1].start_line or 0,
                item[1].end_line or 0,
            ),
        )
        current_start: int | None = None
        current_end: int | None = None
        current_reason: str | None = None
        current_reason_index: int | None = None

        for index, citation in ranges:
            start = citation.start_line
            end = citation.end_line
            if start is None or end is None:
                continue
            if current_start is None or current_end is None:
                current_start = start
                current_end = end
                current_reason = citation.reason
                current_reason_index = index if citation.reason else None
                continue

            if start <= current_end + 1:
                current_end = max(current_end, end)
                if citation.reason and (
                    current_reason_index is None or index < current_reason_index
                ):
                    current_reason = citation.reason
                    current_reason_index = index
                continue

            merged.append(
                Citation(path, current_start, current_end, current_reason)
            )
            current_start = start
            current_end = end
            current_reason = citation.reason
            current_reason_index = index if citation.reason else None

        if current_start is not None and current_end is not None:
            merged.append(Citation(path, current_start, current_end, current_reason))

    merged.extend(non_mergeable)
    return merged


def _extract_raw_locations(
    citations: list[Citation],
    *,
    repo_root: Path,
    settings: Settings,
    warnings: list[str],
) -> list[RawLocation]:
    raw_locations: list[RawLocation] = []
    for citation in citations:
        if citation.start_line is None or citation.end_line is None:
            _append_warning_once(warnings, "raw location missing line range")
            continue
        try:
            observation = read_file(
                repo_root=repo_root,
                path=citation.path,
                start_line=citation.start_line,
                end_line=citation.end_line,
                max_bytes=settings.max_read_bytes,
                ignore=settings.ignore,
            )
        except ExplorerError:
            _append_warning_once(warnings, "raw location could not be read")
            continue
        start, end = _parse_line_range(observation.line_range or "")
        if (
            observation.path is None
            or observation.content is None
            or start is None
            or end is None
        ):
            _append_warning_once(warnings, "raw location could not be read")
            continue
        if observation.truncated:
            _append_warning_once(warnings, "raw location truncated")
        raw_locations.append(
            RawLocation(
                path=observation.path,
                start_line=start,
                end_line=end,
                text=observation.content,
                truncated=observation.truncated,
            )
        )
    return raw_locations


def _try_exact_fast_path(
    request: ExploreRequest,
    *,
    repo_root: Path,
    settings: Settings,
) -> ExploreResult | None:
    if _is_semantic_query(request.query):
        return None
    evidence = EvidenceState()
    warnings: list[str] = []
    citations = _validated_citations_from_content(
        request.query,
        repo_root=repo_root,
        settings=settings,
        evidence=evidence,
        warnings=warnings,
    )
    if citations:
        return _finalize_result(
            request=request,
            repo_root=repo_root,
            settings=settings,
            answer="",
            citations=citations,
            turns_used=0,
            truncated=any(observation.truncated for observation in evidence.reads),
            warnings=[],
        )

    explicit_path = _extract_explicit_path(request.query)
    if explicit_path is not None:
        target = _extract_exact_target(request.query, explicit_path)
        if target is None:
            return None
        citations = _exact_matches_in_file(
            repo_root=repo_root,
            settings=settings,
            path=explicit_path,
            target=target,
            allow_assignment=True,
        )
        if citations:
            return _finalize_result(
                request=request,
                repo_root=repo_root,
                settings=settings,
                answer="",
                citations=citations,
                turns_used=0,
                truncated=False,
                warnings=[],
            )
        return None

    symbol = _extract_pathless_symbol(request.query)
    if symbol is None:
        return None
    citation = _unique_definition_citation(
        repo_root=repo_root,
        settings=settings,
        symbol=symbol,
    )
    if citation is None:
        return None
    return _finalize_result(
        request=request,
        repo_root=repo_root,
        settings=settings,
        answer="",
        citations=[citation],
        turns_used=0,
        truncated=False,
        warnings=[],
    )


def _is_semantic_query(query: str) -> bool:
    return bool(SEMANTIC_QUERY_RE.search(query))


def _extract_explicit_path(query: str) -> str | None:
    for match in EXPLICIT_PATH_RE.finditer(query):
        path = match.group("path").rstrip(".,;:)")
        if _is_repository_relative_path(path):
            return path
    return None


def _extract_exact_target(query: str, explicit_path: str) -> str | None:
    for match in EXACT_TEXT_RE.finditer(query):
        target = match.group("target").strip()
        if target and target != explicit_path and target != Path(explicit_path).stem:
            return target
    without_path = query.replace(explicit_path, " ")
    ignored = {
        "in",
        "find",
        "the",
        "where",
        "return",
        "citations",
        "only",
        "line",
        "lines",
        "file",
    }
    tokens = [
        match.group("token")
        for match in TOKEN_RE.finditer(without_path)
        if match.group("token").lower() not in ignored
    ]
    return tokens[-1] if len(tokens) == 1 else None


def _extract_pathless_symbol(query: str) -> str | None:
    for match in BACKTICK_OR_QUOTE_RE.finditer(query):
        return match.group("token")
    ignored = {
        "find",
        "the",
        "definition",
        "of",
        "return",
        "citations",
        "only",
        "class",
        "function",
        "def",
        "symbol",
    }
    candidates = [
        match.group("token")
        for match in TOKEN_RE.finditer(query)
        if match.group("token").lower() not in ignored
    ]
    return candidates[0] if len(candidates) == 1 else None


def _exact_matches_in_file(
    *,
    repo_root: Path,
    settings: Settings,
    path: str,
    target: str,
    allow_assignment: bool,
) -> list[Citation]:
    grep_result = _grep_exact_target(
        repo_root=repo_root,
        settings=settings,
        target=target,
        glob=path,
    )
    if grep_result.truncated:
        return []
    citations = _citations_for_target_hits(
        grep_result,
        target=target,
        allow_assignment=allow_assignment,
        definitions_only=False,
    )
    return citations if 0 < len(citations) <= MAX_FINAL_CITATIONS else []


def _unique_definition_citation(
    *,
    repo_root: Path,
    settings: Settings,
    symbol: str,
) -> Citation | None:
    grep_result = _grep_exact_target(
        repo_root=repo_root,
        settings=settings,
        target=symbol,
        glob="**/*.py",
    )
    pyi_result = _grep_exact_target(
        repo_root=repo_root,
        settings=settings,
        target=symbol,
        glob="**/*.pyi",
    )
    citations = _citations_for_target_hits(
        grep_result,
        target=symbol,
        allow_assignment=False,
        definitions_only=True,
    )
    citations.extend(
        _citations_for_target_hits(
            pyi_result,
            target=symbol,
            allow_assignment=False,
            definitions_only=True,
        )
    )
    if grep_result.truncated or pyi_result.truncated or len(citations) > 1:
        return None
    return citations[0] if len(citations) == 1 else None


def _grep_exact_target(
    *,
    repo_root: Path,
    settings: Settings,
    target: str,
    glob: str,
) -> ToolObservation:
    return repo_grep(
        repo_root=repo_root,
        pattern=re.escape(target),
        glob=glob,
        max_results=MAX_FINAL_CITATIONS + 1,
        ignore=settings.ignore,
    )


def _citations_for_target_hits(
    observation: ToolObservation,
    *,
    target: str,
    allow_assignment: bool,
    definitions_only: bool,
) -> list[Citation]:
    citations: list[Citation] = []
    for hit in observation.hits:
        if _line_matches_target(
            hit.text,
            target=target,
            allow_assignment=allow_assignment,
            definitions_only=definitions_only,
        ):
            citations.append(Citation(hit.path, hit.line, hit.line))
    return citations


def _line_matches_target(
    line: str,
    *,
    target: str,
    allow_assignment: bool,
    definitions_only: bool,
) -> bool:
    escaped = re.escape(target)
    definition_pattern = (
        rf"^\s*(?:async\s+def|def|class)\s+{escaped}\b"
    )
    if re.search(definition_pattern, line):
        return True
    if definitions_only:
        return False
    if allow_assignment and re.search(rf"^\s*{escaped}\s*(?::|=)", line):
        return True
    return bool(re.search(rf"\b{escaped}\b", line))


def _validated_citations_from_content(
    content: str,
    *,
    repo_root: Path,
    settings: Settings,
    evidence: EvidenceState,
    warnings: list[str],
) -> list[Citation]:
    parsed = extract_citations(content)
    if not parsed:
        return []
    validated = _validate_citations(
        parsed,
        repo_root=repo_root,
        settings=settings,
        evidence=evidence,
    )
    if not validated:
        _append_warning_once(warnings, "invalid citation rejected")
    return validated


def _validate_citations(
    citations: list[Citation],
    *,
    repo_root: Path,
    settings: Settings,
    evidence: EvidenceState,
) -> list[Citation]:
    validated: list[Citation] = []
    for citation in citations:
        normalized = _normalize_citation(citation)
        if normalized is None:
            continue
        if _citation_has_read_coverage(normalized, evidence.reads):
            validated.append(normalized)
            continue
        verified = _verify_citation_by_read(
            normalized,
            repo_root=repo_root,
            settings=settings,
            evidence=evidence,
        )
        if verified is not None:
            validated.append(verified)
    return _merge_adjacent_citations(_dedupe_citations(validated))[
        :MAX_FINAL_CITATIONS
    ]


def _normalize_citation(citation: Citation) -> Citation | None:
    if (
        not citation.path
        or citation.start_line is None
        or citation.end_line is None
        or citation.start_line <= 0
        or citation.end_line <= 0
        or citation.end_line < citation.start_line
        or not _is_repository_relative_path(citation.path)
    ):
        return None
    return Citation(
        path=citation.path,
        start_line=citation.start_line,
        end_line=citation.end_line,
        reason=citation.reason,
    )


def _is_repository_relative_path(path: str) -> bool:
    raw = Path(path)
    return not raw.is_absolute() and ".." not in raw.parts


def _citation_has_read_coverage(
    citation: Citation,
    observations: list[ToolObservation],
) -> bool:
    for observation in observations:
        if not _citation_overlaps_read(citation, observation):
            continue
        read_start, read_end = _parse_line_range(observation.line_range or "")
        if (
            read_start is not None
            and read_end is not None
            and citation.start_line is not None
            and citation.end_line is not None
            and read_start <= citation.start_line
            and read_end >= citation.end_line
        ):
            return True
    return False


def _citation_overlaps_read(
    citation: Citation,
    observation: ToolObservation,
) -> bool:
    if (
        observation.path != citation.path
        or observation.line_range is None
        or citation.start_line is None
        or citation.end_line is None
    ):
        return False
    read_start, read_end = _parse_line_range(observation.line_range)
    if read_start is None or read_end is None:
        return False
    return citation.start_line <= read_end and citation.end_line >= read_start


def _verify_citation_by_read(
    citation: Citation,
    *,
    repo_root: Path,
    settings: Settings,
    evidence: EvidenceState,
) -> Citation | None:
    if citation.start_line is None or citation.end_line is None:
        return None
    try:
        observation = read_file(
            repo_root=repo_root,
            path=citation.path,
            start_line=citation.start_line,
            end_line=citation.end_line,
            max_bytes=settings.max_read_bytes,
            ignore=settings.ignore,
        )
    except ExplorerError:
        return None
    verified = Citation(
        path=observation.path or citation.path,
        start_line=citation.start_line,
        end_line=citation.end_line,
        reason=citation.reason,
    )
    if verified.path != citation.path:
        return None
    if not _citation_has_read_coverage(verified, [observation]):
        return None
    evidence.reads.append(observation)
    return verified


def _dedupe_citations(citations: list[Citation]) -> list[Citation]:
    deduped: list[Citation] = []
    seen: set[tuple[str, int | None, int | None]] = set()
    for citation in citations:
        key = (citation.path, citation.start_line, citation.end_line)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(citation)
    return deduped


def _best_current_citations(evidence: EvidenceState) -> list[Citation]:
    if evidence.citations:
        return evidence.citations[:MAX_FINAL_CITATIONS]
    return _citations_from_reads(evidence.reads)


def _citations_from_reads(observations: list[ToolObservation]) -> list[Citation]:
    candidates: list[tuple[bool, int, int, Citation]] = []
    seen: set[tuple[str, int | None, int | None]] = set()
    for index, observation in enumerate(observations):
        if observation.path is None or observation.line_range is None:
            continue
        start, end = _parse_line_range(observation.line_range)
        if start is None or end is None:
            continue
        key = (observation.path, start, end)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(
            (
                observation.truncated,
                end - start,
                index,
                Citation(observation.path, start, end),
            )
        )
    return [
        citation
        for _, _, _, citation in sorted(candidates, key=lambda candidate: candidate[:3])
    ][:MAX_FINAL_CITATIONS]


def _should_finalize_before_tool_calls(
    request: ExploreRequest,
    evidence: EvidenceState,
    tool_calls: list[ToolCall],
    settings: Settings,
) -> bool:
    if not request.citation or _best_narrow_read_citation(evidence, settings) is None:
        return False
    return any(
        _is_broad_read_on_seen_path(tool_call, evidence, settings)
        for tool_call in tool_calls
    )


def _best_narrow_read_citation(
    evidence: EvidenceState,
    settings: Settings,
) -> Citation | None:
    for citation in _citations_from_reads(evidence.reads):
        for observation in evidence.reads:
            start, end = _parse_line_range(observation.line_range or "")
            if (
                observation.path == citation.path
                and not observation.truncated
                and citation.start_line is not None
                and citation.end_line is not None
                and start == citation.start_line
                and end == citation.end_line
                and citation.end_line - citation.start_line + 1
                <= settings.max_read_lines
            ):
                return citation
    return None


def _is_broad_read_on_seen_path(
    tool_call: ToolCall,
    evidence: EvidenceState,
    settings: Settings,
) -> bool:
    if tool_call.name != "read_file":
        return False
    path = tool_call.arguments.get("path")
    if not isinstance(path, str) or not path:
        return False
    read_paths = {
        observation.path for observation in evidence.reads if observation.path
    }
    if path not in read_paths:
        return False
    start_line = _int_argument(tool_call.arguments, "start_line")
    end_line = _int_argument(tool_call.arguments, "end_line")
    if start_line is None or end_line is None:
        return True
    return end_line - start_line + 1 > settings.max_read_lines


def _tool_call_fingerprint(tool_call: ToolCall) -> str:
    return json.dumps(
        {
            "name": tool_call.name,
            "arguments": tool_call.arguments,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _first_repeated_tool_call(
    evidence: EvidenceState,
    tool_calls: list[ToolCall],
) -> ToolCall | None:
    batch_fingerprints: set[str] = set()
    for tool_call in tool_calls:
        fingerprint = _tool_call_fingerprint(tool_call)
        if (
            fingerprint in evidence.seen_tool_calls
            or fingerprint in batch_fingerprints
        ):
            return tool_call
        batch_fingerprints.add(fingerprint)
    return None


def _message_has_tool_calls(message: dict[str, Any]) -> bool:
    return bool(message.get("tool_calls"))


def _append_warning_once(warnings: list[str], warning: str) -> None:
    if warning not in warnings:
        warnings.append(warning)


def extract_citations(answer: str) -> list[Citation]:
    citations: list[Citation] = []
    seen: set[tuple[str, int, int | None]] = set()
    for regex in (
        CITATION_RE,
        SOURCE_LINES_RE,
        LINES_OF_SOURCE_RE,
        MARKDOWN_FILE_LINES_RE,
    ):
        for match in regex.finditer(answer):
            citation = _citation_from_match(match)
            key = (citation.path, citation.start_line or 0, citation.end_line)
            if key in seen:
                continue
            seen.add(key)
            citations.append(citation)
    return citations


def _citation_from_match(match: re.Match[str]) -> Citation:
    path = match.group("path")
    start = int(match.group("start"))
    end_text = match.group("end")
    end = int(end_text) if end_text is not None else start
    return Citation(path=path, start_line=start, end_line=end)


def _citations_from_observations(
    answer: str,
    observations: list[ToolObservation],
) -> list[Citation]:
    citations: list[Citation] = []
    seen: set[tuple[str, int | None, int | None]] = set()
    for observation in observations:
        if observation.path is None or observation.line_range is None:
            continue
        if (
            observation.path not in answer
            and Path(observation.path).name not in answer
        ):
            continue
        start, end = _parse_line_range(observation.line_range)
        key = (observation.path, start, end)
        if key in seen:
            continue
        seen.add(key)
        citations.append(Citation(observation.path, start, end))
    return citations[:MAX_FINAL_CITATIONS]


def _parse_line_range(line_range: str) -> tuple[int | None, int | None]:
    start_text, _, end_text = line_range.partition("-")
    try:
        start = int(start_text)
    except ValueError:
        return None, None
    if not end_text:
        return start, start
    try:
        end = int(end_text)
    except ValueError:
        return start, start
    return start, end


def _initial_messages(
    request: ExploreRequest,
    file_sample: ToolObservation,
    settings: Settings,
) -> list[dict[str, Any]]:
    files = "\n".join(f"- {path}" for path in file_sample.matches)
    if not files:
        files = "- <no safe files listed>"
    truncated_note = (
        "\nThe file list is truncated; use repo_glob/repo_grep for more paths."
        if file_sample.truncated
        else ""
    )
    output_contract = (
        "Final answer format is strict: end with a <final_answer> block "
        "containing only 1-5 repository-relative path:start-end citation "
        "lines, then </final_answer>. Do not include prose, Markdown, code "
        "blocks, bullets, or explanations inside the block. If no citation "
        "is supported, return exactly NO_CITATIONS_FOUND."
        if request.citation
        else "Final answer may include concise prose with file-line citations."
    )
    return [
        {
            "role": "system",
            "content": (
                "You answer focused questions about a local repository. "
                "Use only the provided read-only tools. Return compact "
                "repository-relative citations as path:start-end. Use the "
                "listed repository paths as grounding and do not invent paths. "
                "Tool path arguments must be repository-relative with no "
                "leading slash and must not include the repository directory "
                "name as a prefix. Example: use src/app.py, not "
                "/repo/src/app.py or repo/src/app.py. "
                "If a read returns PATH_NOT_FOUND, INVALID_TOOL_ARGUMENTS, or "
                "PATH_OUTSIDE_ROOT, correct the path once using the known file "
                "list or broaden search; do not repeat the same failing call. "
                "When searches or reads are independent, issue them as multiple "
                "tool calls in the same turn. "
                "For exact symbol, function, or class names, use repo_grep "
                "before reading broad file ranges. "
                f"Use read_file line ranges of at most {settings.max_read_lines} "
                "lines unless no narrower range is known. "
                f"{output_contract}"
            ),
        },
        {
            "role": "user",
            "content": (
                f"{request.query}\n\n"
                f"Known safe repository files:\n{files}{truncated_note}"
            ),
        },
    ]


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
    content = payload.get("content")
    if not isinstance(content, str) or len(content) <= max_chars:
        return
    payload["content"] = content[:max_chars]
    payload["content_truncated_by_chars"] = True
    payload["truncated"] = True


def _with_line_numbers(content: str, line_range: str) -> str:
    start, _ = _parse_line_range(line_range)
    line_number = start or 1
    lines: list[str] = []
    for offset, line in enumerate(content.splitlines(), start=0):
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
            )
            if clamped:
                observation.truncated = True
            return observation
        if tool_call.name == "repo_glob":
            return repo_glob(
                repo_root=repo_root,
                pattern=_required_str(tool_call.arguments, "pattern"),
                max_results=settings.max_grep_results,
                ignore=settings.ignore,
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
            )
    except ExplorerError as exc:
        return ToolObservation.from_error(exc, tool_call_id=tool_call.id)
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


def _int_argument(arguments: dict[str, object], key: str) -> int | None:
    value = arguments.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _bounded_read_lines(
    arguments: dict[str, object],
    settings: Settings,
) -> tuple[int | None, int | None, bool]:
    start_line = _optional_int(arguments, "start_line")
    end_line = _optional_int(arguments, "end_line")
    if start_line is not None and end_line is not None:
        max_end_line = start_line + settings.max_read_lines - 1
        if end_line > max_end_line:
            return start_line, max_end_line, True
        return start_line, end_line, False
    if start_line is None:
        start_line = 1
    return start_line, start_line + settings.max_read_lines - 1, True

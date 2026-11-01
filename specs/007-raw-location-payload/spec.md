# Spec 007: Raw Location Evidence With Merged Ranges

## Summary

Final JSON-compatible results include controller-extracted raw source text for
validated citations. Before result rendering, citations are normalized by
merging overlapping or adjacent line ranges per path.

Citation-mode `answer` remains compact citation labels. Raw source text is
returned only in `raw_locations`.

## Requirements

- The canonical final `citations` list MUST merge overlapping or adjacent
  concrete line ranges for the same path.
- Adjacent means `next.start_line <= current.end_line + 1`.
- Merging MUST group by path and preserve path group order by first appearance
  in the validated citation list.
- Citations contain only `path`, `start_line`, and `end_line`; the unused
  `reason` field has been removed.
- `answer` in citation mode MUST be rendered from merged citations.
- `raw_locations` MUST be extracted by reading merged citation ranges with the
  existing root-scoped read-only file tool path.
- Raw extraction MUST obey denylist, ignore rules, symlink/path safety, and
  `max_read_bytes`.
- Unreadable raw locations MUST be omitted and reported with a warning.
- Truncated raw reads MUST be returned with `truncated: true` and reported with
  a warning.
- Trajectory logs MUST NOT persist raw location `text`.

## Payload Shape

```json
{
  "answer": "src/api/validation.py:42-88",
  "citations": [
    {
      "path": "src/api/validation.py",
      "start_line": 42,
      "end_line": 88
    }
  ],
  "raw_locations": [
    {
      "path": "src/api/validation.py",
      "start_line": 42,
      "end_line": 88,
      "text": "def validate_request(payload):\n    ...\n",
      "truncated": false
    }
  ]
}
```

## Acceptance Tests

- Overlapping and adjacent same-path citations merge before final output.
- Disjoint same-path citations and cross-file citations remain separate.
- JSON CLI and MCP outputs include `raw_locations`.
- Exact fast path returns `raw_locations` with `turns_used=0`.
- Truncated raw extraction marks the raw location as truncated.
- Trajectory logs include raw location metadata without raw text.

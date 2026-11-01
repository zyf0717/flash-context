# CLI

```bash
flash-context search --repo PATH --query TEXT [--max-turns N] \
  [--citation | --no-citation] [--format text|json]
```

`--repo` and a nonblank `--query` are required. Defaults are twelve turns,
citation-only answers, and text output. `--no-citation` retains model prose and
rewrites accepted anchors to verified file-line labels. `--format json` returns
the [shared result](contracts.md#result); formatting belongs to this adapter.
An answer without evidence is `NO_CITATIONS_FOUND` in either mode.

Warnings print to stderr as `WARNING: message` in both formats. Truncation without
a diagnostic prints `WARNING: Result truncated`. Stdout retains its result even
when an empty budget-limited search exits 6. Errors print `CODE: message` to
stderr, without source contents or secrets.

| Exit | Meaning |
| --- | --- |
| 0 | Success, partial cited results, or complete empty search |
| 2 | Usage error or blank query |
| 3 | Configuration error |
| 4 | Repository/path error |
| 5 | Endpoint error |
| 6 | Other search error, or empty result after a scan/parser limit or timeout |

Ordinary result caps alone do not change exit status. Endpoint-free lookups,
model corrections, termination, and evidence limits are defined once in the
[shared contract](contracts.md). Installation and examples are in the
[README](../README.md); settings are in [configuration](configuration.md).

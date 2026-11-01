# Citation quality trends

Configure an endpoint, then run:

```bash
uv run python scripts/citation_benchmark.py --repetitions 3 > /tmp/quality.jsonl
FLASH_CONTEXT_RUN_E2E=1 uv run pytest tests/e2e -s
```

Both entrypoints use `citations.json`: pinned source hashes and independently
reviewed expected line ranges. Do not regenerate truth through the production
resolver. The HTTPX 0.28.1 source and its BSD license are included in fixtures.

Each JSONL row records package/parser versions, effective noncredential settings,
fixture hash, turns, time, cited lines, UTF-8 snippet bytes, result bytes, and
incomplete-result metadata. Hit means every expected region was touched;
`region_recall` is the fraction touched. Tightness is expected/cited unique-line
intersection divided by cited lines (null for empty output). These are structural
proxies; evaluate recall and tightness together. They do not measure semantics.

For release comparisons, keep this script and fixture manifest fixed and run the
script with each release's installed Python environment, from a directory outside
the source checkout. For example, `/tmp/old-env/bin/python /path/to/flash-context/scripts/citation_benchmark.py`.
The runner imports only shared exploration/configuration interfaces and does not
use the v0.4.0 parser to calculate expected results. Keep model, settings, and
repetition count identical. Standard CI uses mocked endpoints; live trends are
opt-in and depend on the configured model.

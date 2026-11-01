# Architecture

```text
CLI / MCP → shared exploration core → OpenAI-compatible chat completions
                         ↓
              read_file / repo_glob / repo_grep
```

The adapters parse requests and render the shared result. The core owns query
routing, bounded model turns, and evidence selection. `queries.py` classifies
intent; `execution.py` validates messages and runs local batches. Citation
resolution owns syntax boundaries and a request-local source cache. Filesystem
safety is centralized in `tools/safety.py`; local tools are read-only. Endpoint
requests are serial; independent local calls in one turn may run concurrently.

Validation establishes safe paths, source coverage, syntax boundaries, and
whole-token presence for exact queries. Semantic relevance remains the model's
judgment. See the [shared contract](contracts.md) for evidence and safety rules,
[configuration](configuration.md) for budgets, and [spec history](../specs/README.md)
for completed work. The CLI, MCP adapter, and v0.4.0 citation boundaries are
implemented; no embedding store, repository writes, or model hosting is included.

FastContext's delegated exploration approach inspired the project. Historical
references are recorded in the archived specs; the supported endpoint contract
is OpenAI-compatible chat completions with tool calls.

# Architecture

```text
CLI / MCP → shared search core → OpenAI-compatible chat completions
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
judgment. The [shared contract](contracts.md) defines evidence and safety rules;
[configuration](configuration.md) defines settings and budgets. CLI and MCP
behavior live in their respective docs. Contributor guidance is in
[CONTRIBUTING.md](../CONTRIBUTING.md).

FastContext's delegated exploration approach inspired the project. The supported
endpoint contract is OpenAI-compatible chat completions with tool calls.

# Contributing

Use Python 3.13+ and `uv`. From the project root:

```bash
uv sync --locked --extra mcp
uv run --locked ruff check .
uv run --locked mypy
uv run --locked pytest -m "not e2e"
```

Standard tests mock external endpoints. CI tests Python 3.13 and 3.14 and checks
installed wheel/source packages. Optional live probes and timing instructions
are in [benchmarks](benchmarks/README.md).

## Changes

- Keep interfaces typed, adapters thin, and logic in the shared core. Prefer
  small, direct implementations and proportionate regression tests.
- Preserve read-only, root-scoped access, path/symlink checks, deny rules, resource
  limits, and metadata-only logging. Never expose source or secrets in diagnostics.
- Treat [docs](docs/architecture.md) as the source of truth. Update the relevant
  contract and affected examples when behavior changes; avoid repeating policy.
- Run `uv lock` when dependencies change. Record user-visible changes and migration
  notes in `CHANGELOG.md` under `[Unreleased]`; see [releasing](docs/releasing.md).

Use a `dev/` branch and Conventional Commits. Submit a pull request to `main`
with the problem, resulting behavior, and validation. Merge by squash or rebase
after CI passes; do not push directly to `main` or bypass required checks.

Report bugs with reproduction steps and Python/package versions. Redact secrets
from examples and logs. Contributions use the [Apache License 2.0](LICENSE).

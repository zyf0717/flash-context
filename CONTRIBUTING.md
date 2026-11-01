# Contributing

Bug reports, focused fixes, tests, and documentation improvements are welcome.
For substantial features or architecture changes, open an issue to discuss the
scope before implementing them.

## Development setup

Install Python 3.13+ and `uv`, then run these commands from your clone:

```bash
uv sync --locked --extra mcp
uv run --locked flash-context --help
```

The MCP extra enables development of the optional adapter. An external model
endpoint is not needed for the standard test suite.

See [Configuration](docs/configuration.md) for endpoint settings and the
[README](README.md) for CLI usage and MCP integration links. Source
checkouts load operator configuration from project-root `config.yaml` and
`.env`; keep credentials and local configuration out of commits.

## Checks

Run the same checks as CI before submitting a pull request:

```bash
uv run --locked ruff check .
uv run --locked mypy
uv run --locked pytest -m "not e2e"
```

`.github/workflows/ci.yml` runs on branch pushes and pull requests to `main`.
It checks Python 3.13 and 3.14 and verifies clean wheel and source installs.
The tag release workflow reuses these checks before publishing.
[Releasing](docs/releasing.md) covers package checks and publication.

## Endpoint-backed tests

These optional tests use this repository as the target and require a running
model endpoint. From the source checkout, configure its URL and model, then run:

```bash
export FLASH_CONTEXT_BASE_URL=http://localhost:1234/v1
export FLASH_CONTEXT_MODEL=your-model
FLASH_CONTEXT_RUN_E2E=1 uv run --locked pytest tests/e2e
```

To print per-prompt timing:

```bash
FLASH_CONTEXT_RUN_E2E=1 uv run --locked pytest tests/e2e/test_current_repo_multi_prompt_timing.py -s
```

## Implementation guidelines

- Keep changes focused and follow existing Python conventions. Prefer simple,
  typed interfaces and avoid unnecessary dependencies or abstractions.
- Keep CLI and MCP adapters thin; both use the shared exploration core.
- Preserve read-only repository access. Centralize path validation and retain
  traversal, symlink, denylist, and resource-limit protections.
- Add proportionate regression tests for changed behavior. Standard tests must
  mock external endpoints and must not depend on credentials or live services.
- Update the relevant specs, contracts, README, and user-facing documentation
  when changing public behavior.
- Refresh `uv.lock` with `uv lock` when changing dependencies.
- Add user-visible changes and migration instructions to `CHANGELOG.md` under
  `[Unreleased]`. Version preparation promotes those notes to a dated release
  entry; see [Releasing](docs/releasing.md).

Read [AGENTS.md](AGENTS.md) for repository-wide guidance,
[specs](specs/) for behavior and contracts, and
[implementation order](docs/implementation-order.md) for scope and sequencing.

## Issues and pull requests

Report bugs with reproduction steps, expected and actual behavior, and relevant
Python/package versions. Redact credentials and sensitive repository content
from logs and examples.

Create a branch in your fork or checkout (for example, `dev/short-description`)
and use Conventional Commits, such as
`fix: reject symlink escapes` or `docs: clarify endpoint configuration`.
In the pull request, explain the problem, resulting behavior, and validation
performed. Include any relevant issue or spec links.

`main` requires a pull request with passing `test (3.13)`, `test (3.14)`, and
`build` checks, an up-to-date branch, and resolved review conversations.
Merge with squash or rebase; merge commits, force pushes, and deletion of
`main` are blocked. Only `zyf0717` has bypass access. No review approval count
is required while the project has a sole maintainer.

## License

Contributions are submitted under the project's
[Apache License 2.0](LICENSE).

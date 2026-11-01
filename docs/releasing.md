# Releasing

The workflow is `.github/workflows/release.yaml`. Pull requests and pushes to
`main` run Ruff, mypy, and endpoint-free tests on Python 3.13 and 3.14 with the MCP
extra, then build and check clean wheel and source installs.

A `v*` tag push also runs this sequence automatically:

```text
tests → build/check/install → TestPyPI → TestPyPI install check
      → PyPI → PyPI install check
```

Each stage requires its predecessor to succeed. Both registries receive the
same wheel and source distribution. Index checks install the exact tagged
version, exercise endpoint-free CLI exploration and real MCP tool discovery,
and retry index installation up to six times with ten seconds between attempts.
TestPyPI supplies only `flash-context`; its dependencies come from PyPI.
Publishing jobs use short-lived OIDC credentials and generate attestations via
the [PyPA publishing action](https://github.com/pypa/gh-action-pypi-publish).

## One-time setup

The `zyf0717/flash-context` GitHub repository has environments named `testpypi`
and `pypi`, configured to allow only `v*` tags with no required reviewers or wait
timers. When setting up a fork, create equivalent environments so successful
tag releases proceed without manual approval.

Configure a GitHub Trusted Publisher separately on
[TestPyPI](https://test.pypi.org/manage/account/publishing/) and
[PyPI](https://pypi.org/manage/account/publishing/):

| Field | TestPyPI | PyPI |
| --- | --- | --- |
| Project name | `flash-context` | `flash-context` |
| Owner | `zyf0717` | `zyf0717` |
| Repository | `flash-context` | `flash-context` |
| Workflow filename | `release.yaml` | `release.yaml` |
| Environment | `testpypi` | `pypi` |

For a new project, add a pending publisher from the account publishing page;
the first successful upload creates the project. If it already exists under
your account, add the publisher in that project's publishing settings. Names
must be available or owned by you on both registries. No PyPI API tokens or
GitHub Actions secrets are needed. See the
[PyPI Trusted Publishing guide](https://docs.pypi.org/trusted-publishers/).

## Publish a version

Set the version in `pyproject.toml` and refresh `uv.lock`; `uv version` does
both. Runtime `flash_context.__version__` reads the installed metadata.

```bash
uv version 0.1.0
uv sync --locked --extra mcp
uv run --locked ruff check .
uv run --locked mypy
uv run --locked pytest -m "not e2e"
uv build
uvx twine check --strict dist/*
```

Commit the changes, push the commit, then push the matching version tag:

```bash
git tag v0.1.0
git push origin v0.1.0
```

The tag must exactly match `v` plus the project version (including prerelease
suffixes, for example `v0.2.0rc1`). Every accepted version tag publishes to both
registries. Existing versions/files are not overwritten or silently skipped;
use a new version after a partially published release. Re-running failed jobs
can resume from a failed stage when its upload has not already succeeded.

## Local installed-package checks

Use fresh environments outside the checkout; the smoke script must import the
installed distribution. Run from the repository root after `uv build`:

```bash
version=$(uv version --short)
uv venv /tmp/wheel-check --python 3.13
uv pip install --python /tmp/wheel-check/bin/python dist/*.whl
PATH="/tmp/wheel-check/bin:$PATH" /tmp/wheel-check/bin/python scripts/smoke_test.py "$version"
uv venv /tmp/sdist-check --python 3.13
uv pip install --python /tmp/sdist-check/bin/python "dist/flash_context-$version.tar.gz[mcp]"
PATH="/tmp/sdist-check/bin:$PATH" /tmp/sdist-check/bin/python scripts/smoke_test.py "$version" --mcp
```

Published installs load process environment variables and CLI overrides only;
project-root `config.yaml` and `.env` discovery is for source checkouts.

# Releasing

`.github/workflows/ci.yml` runs Ruff, mypy, and endpoint-free tests on Python
3.13 and 3.14 with the MCP extra for branch pushes and pull requests to `main`,
then builds and checks clean wheel and source installs.

A `v*` tag push triggers `.github/workflows/release.yml`, which calls the same
CI workflow before publishing:

```text
tests → build/check/install → TestPyPI → TestPyPI install check
      → PyPI → PyPI install check → GitHub release
```

Each stage requires its predecessor to succeed. Both registries receive the
same wheel and source distribution. Index checks install the exact tagged
version and exercise endpoint-free CLI exploration (citations, bare paths, and
reference-heavy unique symbols) plus real MCP discovery and its tool description.
Index installation is retried up to six times with ten seconds between attempts.
Each retry refreshes cached `flash-context` metadata so an initial index miss
does not persist for the entire retry loop.
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
| Workflow filename | `release.yml` | `release.yml` |
| Environment | `testpypi` | `pypi` |

For a new project, add a pending publisher from the account publishing page;
the first successful upload creates the project. If it already exists under
your account, add the publisher in that project's publishing settings. Names
must be available or owned by you on both registries. No PyPI API tokens or
GitHub Actions secrets are needed. See the
[PyPI Trusted Publishing guide](https://docs.pypi.org/trusted-publishers/).

## Publish a version

Keep user-visible changes in `CHANGELOG.md` under `[Unreleased]`, grouped into
`Added`, `Changed`, `Fixed`, or `Migration` as appropriate. Include instructions
for changed defaults or configuration. Omit empty headings and internal-only
work. This file is the source of GitHub release notes; do not maintain a separate
copy of the notes in the workflow.

When preparing a release, move those entries into a dated section matching the
new package version, for example `## [0.2.1] - YYYY-MM-DD` using the actual release
date. Leave `[Unreleased]` for future changes. Do not rewrite published entries
unless correcting an error. Set the version in `pyproject.toml` and refresh
`uv.lock`; `uv version` does both. Runtime `flash_context.__version__` reads the
installed metadata. The examples below show the already released version; choose
a new version for the next release.

```bash
uv version 0.2.0
uv sync --locked --extra mcp
uv run --locked ruff check .
uv run --locked mypy
uv run --locked pytest -m "not e2e"
uv run --locked python scripts/release_notes.py
uv build
uvx twine check --strict dist/*
```

Submit the version change through a pull request. Once it passes CI and is
merged into `main`, update your local checkout and push the matching tag:

```bash
git switch main
git pull --ff-only
git tag v0.2.0
git push origin v0.2.0
```

The tag must exactly match `v` plus the project version (including prerelease
suffixes, for example `v0.2.0rc1`). Every accepted version tag publishes to both
registries. Existing versions/files are not overwritten or silently skipped;
use a new version after a partially published release. Re-running failed jobs
can resume from a failed stage when its upload has not already succeeded.

## GitHub release publication and recovery

The final `github-release` job requires successful PyPI installation verification.
It downloads the existing `distributions` artifact instead of rebuilding, extracts
the matching changelog section, creates a draft, uploads the wheel and source
archive, then publishes the release. Prerelease tags such as `v0.3.0rc1` create
GitHub prereleases. Only this job receives `contents: write`; registry upload
permissions remain limited to their jobs.

CI validates the current package's changelog section on branches and pull
requests, and additionally checks the tag/version match on tag builds. Missing,
duplicate, undated, invalid-date, or empty entries fail before any publication.
The source distribution includes `CHANGELOG.md`.

If GitHub publication fails after PyPI succeeds, rerun only the failed jobs in
the same Actions run. Do not push another tag or rerun successful registry uploads.
A retry resumes an existing draft, uploads missing assets, verifies existing
assets against their SHA-256 digests, and preserves existing release notes.
A matching published release is left unchanged. An existing asset with a different
or missing digest stops the job for manual inspection; assets are never replaced
automatically. Resolve conflicting assets deliberately before retrying.

Changes to release automation take effect in tags containing the updated workflow;
rerunning an old tag uses its original workflow. The existing v0.2.0 GitHub release
was created manually and is retained unchanged.

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

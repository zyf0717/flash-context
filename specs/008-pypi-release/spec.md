# Spec 008: PyPI Release Pipeline

Status: Implemented; publishing requires one-time external Trusted Publisher setup.

## Contract

- `pyproject.toml` is the single version source, including runtime `__version__`.
- `.github/workflows/ci.yml` runs Ruff, mypy, and endpoint-free tests on Python
  3.13 and 3.14 with the MCP extra installed for branch pushes and pull requests
  to `main`. It also supports `workflow_call` for reuse by releases.
- CI builds a source distribution and a wheel from that source distribution,
  checks metadata with Twine, and smoke-tests clean installs of both.
- Source distributions explicitly include only package code, metadata, license,
  README, changelog, and configuration examples; local config and runtime data
  stay out.
- `.github/workflows/release.yml` runs only on `v*` tag pushes, calls `ci.yml`,
  and requires the tag to equal `v` plus the package version. Mismatches fail
  before publishing. Only tag builds upload distribution artifacts.
- Successful tag builds publish to TestPyPI, install and smoke-test that exact
  version, publish the same distribution artifacts to PyPI, and install and
  smoke-test that exact version again. Any failed stage blocks dependent stages.
- `CHANGELOG.md` is the source of curated release notes. CI validates one dated,
  non-empty section for the package version before publishing, and tag builds
  also enforce tag/version equality.
- After PyPI install verification succeeds, create a GitHub draft release, upload
  the same distribution artifacts, then publish. Only that job has
  `contents: write`.
  Prerelease version tags create GitHub prereleases.
- GitHub retries preserve notes, verify existing asset SHA-256 digests, and upload
  only missing assets. Mismatches stop publication without overwriting files.
- Publishing uses Trusted Publishing with separate `testpypi` and `pypi` GitHub
  environments. Only upload jobs receive `id-token: write`; they do not execute
  package code or build distributions.
- Index checks refresh cached package metadata on each retry for index propagation.
  TestPyPI supplies only the project distribution; dependencies resolve from
  production PyPI.
- Published installations use environment variables and CLI overrides. Source
  checkout configuration discovery remains as defined by spec 006.
- `main` requires a pull request, passing GitHub Actions checks `test (3.13)`,
  `test (3.14)`, and `build`, an up-to-date branch, and resolved review threads.
  Squash and rebase merges are allowed; merge commits, force pushes, and branch
  deletion are blocked. Only the `zyf0717` user may bypass these rules. No review
  approval count is required while there is a sole maintainer.

## Completed Tasks

- [x] Add package metadata, explicit artifact contents, and one version source.
- [x] Remove unused direct Pydantic dependencies.
- [x] Bound the MCP extra to SDK 1.x, whose FastMCP API the adapter uses.
- [x] Restrict implicit configuration discovery to source checkouts and test it.
- [x] Add CI and sequential tag-driven publishing with index install checks.
- [x] Add installed CLI/MCP smoke checks and document release setup.
- [x] Share CI between branch development, pull requests, and tagged releases.
- [x] Protect `main` with required PR checks, owner-only bypass, and linear merges.
- [x] Maintain curated changelog history and validate notes before publication.
- [x] Publish resumable GitHub releases only after PyPI installation verification.
- [x] Refresh package metadata during index installation retries.

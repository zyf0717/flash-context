# Spec 008: PyPI Release Pipeline

Status: Implemented; publishing requires one-time external Trusted Publisher setup.

## Contract

- `pyproject.toml` is the single version source, including runtime `__version__`.
- Pull requests and pushes to `main` run Ruff, mypy, and endpoint-free tests on
  Python 3.13 and 3.14 with the MCP extra installed.
- CI builds a source distribution and a wheel from that source distribution,
  checks metadata with Twine, and smoke-tests clean installs of both.
- Source distributions explicitly include only package code, metadata, license,
  README, and configuration examples; local config and runtime data stay out.
- `v*` tag pushes run the same checks and require the tag to equal `v` plus the
  package version. Mismatches fail before publishing.
- Successful tag builds publish to TestPyPI, install and smoke-test that exact
  version, publish the same distribution artifacts to PyPI, and install and
  smoke-test that exact version again. Any failed stage blocks dependent stages.
- Publishing uses Trusted Publishing with separate `testpypi` and `pypi` GitHub
  environments. Only upload jobs receive `id-token: write`; they do not execute
  package code or build distributions.
- Index checks retry briefly for index propagation. TestPyPI supplies only the
  project distribution; dependencies resolve from production PyPI.
- Published installations use environment variables and CLI overrides. Source
  checkout configuration discovery remains as defined by spec 006.

## Completed Tasks

- [x] Add package metadata, explicit artifact contents, and one version source.
- [x] Remove unused direct Pydantic dependencies.
- [x] Bound the MCP extra to SDK 1.x, whose FastMCP API the adapter uses.
- [x] Restrict implicit configuration discovery to source checkouts and test it.
- [x] Add CI and sequential tag-driven publishing with index install checks.
- [x] Add installed CLI/MCP smoke checks and document release setup.

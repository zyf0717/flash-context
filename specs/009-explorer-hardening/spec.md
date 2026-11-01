# Spec 009: Explorer hardening

Status: implemented

This spec refines specs 002–007 while retaining CLI-first shared-core exploration.

## Safety and execution

- Deny `.env*`, private-key names, runtime histories, and denylisted directories
  at both requested and resolved paths. Prune denied directories while walking.
- Keep optional trajectory logs outside the target, disabled by default, with
  structural metadata only. Reject in-root destinations before exploration;
  logging write failures are warnings. Empty/null trajectory settings disable it.
- Sanitize configuration errors without source excerpts or secret values.
- Each tool defaults to 16 MiB scanned, 10,000 directory entries and a five-second
  processing deadline; configuration keys and precedence are documented in
  `docs/configuration.md`. Count skipped bytes and apply limits to controller reads.
- Grep uses timed regex compatibility mode; patterns are at most 4096 characters.
  Skip lines exceeding 64 KiB and report incomplete coverage. Kernel I/O stalls
  are outside the cooperative deadline guarantee.
- Reject batches exceeding the configured default of 16 calls before scheduling.
  Verify at most 16 citation candidates per response, retaining the five final
  citation limit. Tool observations may carry warnings; propagate to results.

## Correctness

- Recognize only conservative exact lookup forms for preflight. Multiple
  targets/files, callers/usages, and unexplained intent use the model loop.
- Narrow-read early termination applies only to exact lookups when every
  pending call is a broad reread of seen evidence.
- Honor end-only read bounds; previews report truncation only when data was
  omitted. Byte-boundary metadata must not claim an unread line. Aggregate
  observation and raw-snippet truncation into the final result.
- Apply observation text caps to read content, grep rows and glob matches.
- Return token-exhausted evidence as explicitly truncated; without evidence,
  return ENDPOINT_BAD_RESPONSE. Reject empty final messages.
- Map file access failures to PATH_UNREADABLE. Searches can continue over other
  files with warnings and truncation. Unreachable read ranges due to scan limits
  use TOOL_LIMIT_EXCEEDED rather than claiming EOF.

## Validation

Endpoint-free regression tests cover denied aliases, environment files, log
privacy and read-only destinations, bounded long-line allocation, regex timeout,
scan limits, unreadable files, conservative routing, exact range metadata,
completion exhaustion, array observation caps and optional logging failures.
Existing release checks remain Ruff, mypy, pytest on Python 3.13/3.14, plus clean
wheel and source installs. Model evaluation and tuning are deferred.

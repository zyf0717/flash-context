# Explorer Tools Contract

The model may request only these local tools. All tools are read-only and scoped
to `repo_root`.

## Shared Rules

- Resolve paths with symlink awareness before access.
- Reject paths outside `repo_root`.
- Reject denylisted files and directories before reading content.
- Return repository-relative paths.
- Enforce configured caps and report truncation.
- Never mutate files, run shell commands, install dependencies, or access the
  network.
- The model may emit multiple tool calls in one assistant message. The
  controller may execute those local tools concurrently, but observations are
  returned to the model in the original tool-call order.

Default denylist:

```text
.git/**
.env*
.flash-context/**
*.pem
*.key
id_rsa
id_ed25519
id_ecdsa
id_dsa
**/secrets/**
**/.aws/**
**/.ssh/**
.venv/**
venv/**
node_modules/**
dist/**
build/**
```

## `read_file`

Arguments:

```json
{
  "path": "src/app.py",
  "start_line": 1,
  "end_line": 120
}
```

Returns:

```json
{
  "path": "src/app.py",
  "line_range": "1-120",
  "content": "file contents...",
  "truncated": false
}
```

Validation:

- `path` is required.
- `start_line` and `end_line` are optional positive integers.
- Returned content must not exceed `FLASH_CONTEXT_MAX_READ_BYTES`.

## `repo_glob`

Arguments:

```json
{
  "pattern": "src/**/*.py"
}
```

Returns:

```json
{
  "matches": ["src/app.py", "src/api/validation.py"],
  "truncated": false
}
```

Validation:

- Pattern is interpreted relative to `repo_root`.
- Denylisted matches are omitted.

## `repo_grep`

Arguments:

```json
{
  "pattern": "validate_request",
  "glob": "src/**/*.py",
  "max_results": 50
}
```

Returns:

```json
{
  "hits": [
    {
      "path": "src/api/validation.py",
      "line": 42,
      "text": "def validate_request(...):"
    }
  ],
  "truncated": false
}
```

Validation:

- `pattern` is required.
- `glob` is optional and repository-relative.
- `max_results` cannot exceed configured `FLASH_CONTEXT_MAX_GREP_RESULTS`.

## Bounded execution

See [hardening spec](../../009-explorer-hardening/spec.md) for scan, pattern,
line, batch, and verification limits. Observations may include `warnings` (a
list of fixed diagnostic strings). Skipped unreadable files, oversized lines,
and exhausted budgets produce `truncated: true`; incomplete search is not proof
of absence. Direct unreadable paths return `PATH_UNREADABLE`. Deny/ignore policy
applies to lexical and resolved paths. Enumeration prunes denied directories,
does not follow directory symlinks, and deduplicates resolved file paths.

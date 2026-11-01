# Configuration

Published installations use process environment variables and CLI overrides:

```bash
export FLASH_CONTEXT_BASE_URL=http://localhost:1234/v1
export FLASH_CONTEXT_MODEL=your-model
# Set FLASH_CONTEXT_API_KEY if your endpoint requires authentication.
```

The endpoint must support OpenAI-compatible chat completions and tool calls.
Exact path or uniquely defined symbol queries can complete locally without an
endpoint when the controller can validate the citation deterministically.
Bare paths, optionally quoted, return previews bounded by
`FLASH_CONTEXT_MAX_READ_BYTES` and `FLASH_CONTEXT_MAX_READ_LINES`. Symbol lookups
count definitions rather than references, and require complete, unambiguous
Python source/stub coverage within the scan limits.

Installed commands do not discover YAML or `.env` files in the installation
directory, working directory, or target repository.

## Source checkout configuration

When running from a source checkout, operator configuration lives in the
`flash-context` project root:

```bash
cp config.yaml.example config.yaml
cp .env.example .env
```

Edit `config.yaml` for model, explorer, and tool settings. Use `.env` or process
environment variables for secrets and local overrides. The inspected
repository's configuration files are not loaded implicitly.

Configuration precedence:

```text
defaults < project-root config.yaml < project-root .env < process environment < CLI overrides
```

Relative paths in YAML, including `explorer.traj_dir`, resolve from the
`flash-context` project root. Environment path overrides are used as supplied.
The YAML and `.env` stages apply only to source checkouts.

## Settings

The [example YAML](../config.yaml.example) and
[example environment file](../.env.example) list supported settings.

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `FLASH_CONTEXT_BASE_URL` | unset | OpenAI-compatible endpoint base URL |
| `FLASH_CONTEXT_MODEL` | unset | Endpoint model identifier |
| `FLASH_CONTEXT_API_KEY` | unset | Optional endpoint credential |
| `FLASH_CONTEXT_MAX_TURNS` | `6` | Maximum exploration turns |
| `FLASH_CONTEXT_MAX_READ_BYTES` | `12000` | File read byte cap |
| `FLASH_CONTEXT_MAX_GREP_RESULTS` | `50` | Grep result cap |
| `FLASH_CONTEXT_TRAJ_DIR` | unset | Optional trajectory log directory |
| `FLASH_CONTEXT_TIMEOUT_SECONDS` | `120` | Endpoint request timeout |
| `FLASH_CONTEXT_MAX_OBSERVATION_CHARS` | `6000` | Model observation character cap |
| `FLASH_CONTEXT_MAX_READ_LINES` | `120` | Model-requested read line cap |
| `FLASH_CONTEXT_MAX_COMPLETION_TOKENS` | `512` | Completion token cap |
| `FLASH_CONTEXT_TEMPERATURE` | `0` | Model sampling temperature |
| `FLASH_CONTEXT_MAX_PARALLEL_TOOLS` | `4` | Same-turn local tool worker cap |

Independent same-turn local tool calls run concurrently; endpoint requests
remain serial. Observation, read, and completion caps bound prompt growth and
reduce latency variance.

See [spec 006](../specs/006-project-root-yaml-dotenv-config/spec.md) for the
configuration contract and [CLI contract](../specs/001-flash-context-explorer/contracts/cli.md)
for options and error codes.

## Local execution budgets and diagnostics

Tool settings also accept these environment variables (and matching snake_case
keys under YAML `tools`, with the existing precedence):

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `FLASH_CONTEXT_MAX_SCAN_BYTES` | `16777216` | Bytes scanned per tool, including skipped lines |
| `FLASH_CONTEXT_MAX_SCAN_ENTRIES` | `10000` | Directory entries examined per tool |
| `FLASH_CONTEXT_TOOL_TIMEOUT_SECONDS` | `5` | Cooperative scan deadline and regex match timeout |
| `FLASH_CONTEXT_MAX_TOOL_CALLS_PER_TURN` | `16` | Maximum model tool batch size |

Limits apply to preflight, model tools, citation verification, and snippet
extraction. Budget exhaustion returns partial observations with truncation and
warnings; a read that cannot reach its starting line returns `TOOL_LIMIT_EXCEEDED`.
Grep uses regex compatibility mode, accepts patterns up to 4096 characters, and
skips lines over 64 KiB with a warning. Directory symlinks are not traversed;
file symlinks are checked at both requested and resolved paths and deduplicated.
Literal search paths are resolved directly, and scoped globs start at their
literal directory prefix, so unrelated trees do not consume their scan budgets.
Deadlines bound processing and matching, but cannot interrupt stalled kernel I/O.

The CLI prints result warnings to stderr for both text and JSON output, or a
generic warning for truncation without a more specific diagnostic. If no
citations are found after scan-byte/entry budget exhaustion or a tool processing
timeout, it exits 6 while preserving the result on stdout. Partial cited results
and complete empty searches exit 0. JSON and MCP retain `truncated` and `warnings`;
MCP returns the shared result without CLI exit semantics. A capped initial file
sample is normal; actual sample scan failures propagate into the result.

### Large repositories

Start with focused queries naming the source directory when known. For a larger
tree that exhausts the defaults, explicitly increase budgets, for example:

```bash
FLASH_CONTEXT_MAX_SCAN_ENTRIES=100000 \
FLASH_CONTEXT_MAX_SCAN_BYTES=100000000 \
FLASH_CONTEXT_TOOL_TIMEOUT_SECONDS=20 \
flash-context explore --repo /path/to/repo \
  --query "Find the recursive dependency resolution implementation"
```

These are opt-in values, not automatic scaling. They allow more local work per
tool and can increase latency; inspect the warnings before increasing them.

### Trajectory logs

Trajectory logging is disabled by default. A configured directory must resolve
outside the selected repository, otherwise exploration returns `CONFIG_INVALID`.
Existing configurations using `.flash-context` inside the target must move the
logs or disable them: `FLASH_CONTEXT_TRAJ_DIR=` overrides an inherited directory.
YAML null and an explicit `SettingsOverrides(traj_dir=None)` also disable logging.
Logs contain structural counts and error codes, never queries, model prose,
arguments, search text, source snippets, or raw exception details. Logging write
failures become result warnings. Existing log files are left untouched.
Tool entries use `content_length` for read content, `hit_count` for grep hits,
and `match_count` for glob paths. Irrelevant counters are omitted, so a grep
result is not described as empty read content.

## Exploration progress and evidence

For implementation-intent questions, documentation-only citations are provisional:
the controller requests source evidence within the remaining turn budget. If only
documentation remains at termination, citations and snippets are retained with
`truncated: true` and an implementation-unverified warning. Detection uses query
terms and common documentation filenames; it does not establish semantic relevance.
Explicit documentation requests and exact lookups retain their existing behavior.
Repeated calls reuse observations while fresh sibling calls execute; an entirely
repeated batch stops exploration. Resource limits and result schemas are unchanged.

Build outputs such as `dist/` remain excluded regardless of scan budgets.
Inspect an allowed source checkout when implementation exists only in a bundle.

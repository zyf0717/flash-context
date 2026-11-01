# Configuration

Published installations use process environment variables and CLI overrides:

```bash
export FLASH_CONTEXT_BASE_URL=http://localhost:1234/v1
export FLASH_CONTEXT_MODEL=your-model
# Set FLASH_CONTEXT_API_KEY if your endpoint requires authentication.
```

The endpoint must support OpenAI-compatible chat completions and tool calls.
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
| `FLASH_CONTEXT_MAX_TURNS` | `12` | Maximum exploration turns |
| `FLASH_CONTEXT_MAX_READ_BYTES` | `12000` | File read byte cap |
| `FLASH_CONTEXT_MAX_GREP_RESULTS` | `50` | Grep result cap |
| `FLASH_CONTEXT_TRAJ_DIR` | unset | Optional trajectory log directory |
| `FLASH_CONTEXT_TIMEOUT_SECONDS` | `120` | Endpoint request timeout |
| `FLASH_CONTEXT_MAX_OBSERVATION_CHARS` | `6000` | Model observation character cap |
| `FLASH_CONTEXT_MAX_READ_LINES` | `120` | Model-requested read line cap |
| `FLASH_CONTEXT_MAX_COMPLETION_TOKENS` | `512` | Completion token cap |
| `FLASH_CONTEXT_TEMPERATURE` | `0` | Model sampling temperature |
| `FLASH_CONTEXT_MAX_PARALLEL_TOOLS` | `4` | Same-turn local tool worker cap |
| `FLASH_CONTEXT_MAX_SCAN_BYTES` | `16777216` | Bytes scanned per tool; cumulative parser bytes |
| `FLASH_CONTEXT_MAX_SCAN_ENTRIES` | `10000` | Directory entries examined per tool |
| `FLASH_CONTEXT_TOOL_TIMEOUT_SECONDS` | `5` | Scan, regex, and parser deadline |
| `FLASH_CONTEXT_MAX_TOOL_CALLS_PER_TURN` | `16` | Maximum model tool batch size |
| `FLASH_CONTEXT_MAX_CITATION_LINES` | `120` | Lines per model citation |
| `FLASH_CONTEXT_MAX_TOTAL_CITATION_LINES` | `600` | Unique model-cited file-lines |
| `FLASH_CONTEXT_MAX_PARSE_BYTES` | `1048576` | Parser input bytes per file |

YAML uses the same names in snake_case: endpoint settings under `model`,
turn/citation limits and ignores under `explorer`, other limits under `tools`.
See the example YAML for the exact layout. Numeric limits must be positive and
finite; temperature may be zero. Endpoint settings are required only for model
exploration. [The shared contract](contracts.md) defines evidence and diagnostic
behavior; [CLI](cli.md) defines exit codes.

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

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

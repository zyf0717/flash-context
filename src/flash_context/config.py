from __future__ import annotations

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass, field, fields, replace
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

from flash_context.tools.safety import ScanLimits
from flash_context.types import ExplorerError


class _Unset(Enum):
    VALUE = "unset"


PROJECT_CONFIG_NAME = "config.yaml"
PROJECT_ENV_NAME = ".env"


@dataclass(frozen=True, slots=True)
class Settings:
    base_url: str = ""
    model: str = ""
    api_key: str | None = None
    max_turns: int = 6
    max_read_bytes: int = 12_000
    max_grep_results: int = 50
    traj_dir: Path | None = None
    ignore: list[str] = field(default_factory=list)
    timeout_seconds: float = 120.0
    max_observation_chars: int = 6_000
    max_read_lines: int = 120
    max_completion_tokens: int = 512
    temperature: float = 0.0
    max_parallel_tools: int = 4

    max_scan_bytes: int = 16 * 1024 * 1024
    max_scan_entries: int = 10_000
    tool_timeout_seconds: float = 5.0
    max_tool_calls_per_turn: int = 16

    @property
    def limits(self) -> ScanLimits:
        return ScanLimits(
            self.max_scan_bytes, self.max_scan_entries, self.tool_timeout_seconds
        )

    def require_endpoint(self) -> None:
        if not self.base_url:
            raise ExplorerError(
                "CONFIG_MISSING_ENDPOINT",
                "FLASH_CONTEXT_BASE_URL is required",
            )
        if not self.model:
            raise ExplorerError(
                "CONFIG_INVALID",
                "FLASH_CONTEXT_MODEL is required",
            )


@dataclass(frozen=True, slots=True)
class SettingsOverrides:
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    max_turns: int | None = None
    max_read_bytes: int | None = None
    max_grep_results: int | None = None
    traj_dir: Path | None | _Unset = _Unset.VALUE
    ignore: list[str] | None = None
    timeout_seconds: float | None = None
    max_observation_chars: int | None = None
    max_read_lines: int | None = None
    max_completion_tokens: int | None = None
    temperature: float | None = None
    max_parallel_tools: int | None = None
    max_scan_bytes: int | None = None
    max_scan_entries: int | None = None
    tool_timeout_seconds: float | None = None
    max_tool_calls_per_turn: int | None = None


def load_settings(
    *,
    repo_root: Path | None = None,
    overrides: SettingsOverrides | None = None,
) -> Settings:
    _ = repo_root
    settings = Settings()
    project_root = _project_root()
    if project_root is not None:
        yaml_path = project_root / PROJECT_CONFIG_NAME
        if yaml_path.exists():
            settings = _apply_yaml(settings, yaml_path, project_root=project_root)
        settings = _apply_env(settings, _load_dotenv(project_root / PROJECT_ENV_NAME))
    settings = _apply_env(settings, os.environ)
    if overrides is not None:
        settings = _apply_overrides(settings, overrides)
    _validate_settings(settings)
    return settings


def _project_root() -> Path | None:
    source_dir = Path(__file__).resolve().parent.parent
    if source_dir.name == "src" and (source_dir.parent / "pyproject.toml").is_file():
        return source_dir.parent
    return None


def _load_dotenv(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    if not path.is_file():
        raise ExplorerError(
            "CONFIG_INVALID",
            f"Env path is not a file: {path}",
        )
    env: dict[str, str] = {}
    lines = _read_config(path).splitlines()
    for line_number, raw_line in enumerate(lines, 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").lstrip()
        if "=" not in line:
            raise ExplorerError(
                "CONFIG_INVALID",
                f"Invalid .env line: {line_number}",
            )
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            raise ExplorerError(
                "CONFIG_INVALID",
                f"Invalid .env line: {line_number}",
            )
        env[key] = _parse_env_value(value.strip())
    return env


def _parse_env_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    if " #" in value:
        return value.split(" #", 1)[0].rstrip()
    return value


def _apply_yaml(settings: Settings, path: Path, *, project_root: Path) -> Settings:
    try:
        loaded = yaml.safe_load(_read_config(path))
    except yaml.YAMLError as exc:
        raise ExplorerError(
            "CONFIG_INVALID",
            f"Invalid YAML config: {path}",
            details={"line": exc.problem_mark.line + 1}
            if isinstance(exc, yaml.MarkedYAMLError) and exc.problem_mark
            else {},
        ) from exc
    if loaded is None:
        data: dict[str, Any] = {}
    elif isinstance(loaded, dict):
        data = {str(key): value for key, value in loaded.items()}
    else:
        raise ExplorerError("CONFIG_INVALID", "YAML config must be a mapping")

    model = _section(data, "model")
    explorer = _section(data, "explorer")
    tools = _section(data, "tools")
    traj_dir = explorer.get("traj_dir", data.get("traj_dir", settings.traj_dir))

    return replace(
        settings,
        base_url=str(model.get("base_url", settings.base_url) or ""),
        model=str(model.get("model", settings.model) or ""),
        api_key=_optional_str(model.get("api_key", settings.api_key)),
        max_turns=_int_value(
            explorer.get("max_turns", settings.max_turns), "max_turns"
        ),
        max_read_bytes=_int_value(
            tools.get("max_read_bytes", settings.max_read_bytes), "max_read_bytes"
        ),
        max_grep_results=_int_value(
            tools.get("max_grep_results", settings.max_grep_results),
            "max_grep_results",
        ),
        timeout_seconds=_float_value(
            model.get("timeout_seconds", settings.timeout_seconds),
            "timeout_seconds",
        ),
        max_observation_chars=_int_value(
            tools.get("max_observation_chars", settings.max_observation_chars),
            "max_observation_chars",
        ),
        max_read_lines=_int_value(
            tools.get("max_read_lines", settings.max_read_lines),
            "max_read_lines",
        ),
        max_parallel_tools=_int_value(
            tools.get("max_parallel_tools", settings.max_parallel_tools),
            "max_parallel_tools",
        ),
        max_completion_tokens=_int_value(
            model.get("max_completion_tokens", settings.max_completion_tokens),
            "max_completion_tokens",
        ),
        temperature=_float_value(
            model.get("temperature", settings.temperature),
            "temperature",
        ),
        traj_dir=_optional_project_path(traj_dir, project_root=project_root),
        max_scan_bytes=_int_value(
            tools.get("max_scan_bytes", settings.max_scan_bytes), "max_scan_bytes"
        ),
        max_scan_entries=_int_value(
            tools.get("max_scan_entries", settings.max_scan_entries), "max_scan_entries"
        ),
        tool_timeout_seconds=_float_value(
            tools.get("tool_timeout_seconds", settings.tool_timeout_seconds),
            "tool_timeout_seconds",
        ),
        max_tool_calls_per_turn=_int_value(
            tools.get("max_tool_calls_per_turn", settings.max_tool_calls_per_turn),
            "max_tool_calls_per_turn",
        ),
        ignore=_str_list(explorer.get("ignore", settings.ignore), "ignore"),
    )


def _apply_env(settings: Settings, env: Mapping[str, str | None]) -> Settings:
    return replace(
        settings,
        max_tool_calls_per_turn=_env_int(
            env,
            "FLASH_CONTEXT_MAX_TOOL_CALLS_PER_TURN",
            settings.max_tool_calls_per_turn,
        ),
        tool_timeout_seconds=_env_float(
            env, "FLASH_CONTEXT_TOOL_TIMEOUT_SECONDS", settings.tool_timeout_seconds
        ),
        max_scan_entries=_env_int(
            env, "FLASH_CONTEXT_MAX_SCAN_ENTRIES", settings.max_scan_entries
        ),
        max_scan_bytes=_env_int(
            env, "FLASH_CONTEXT_MAX_SCAN_BYTES", settings.max_scan_bytes
        ),
        base_url=env.get("FLASH_CONTEXT_BASE_URL") or settings.base_url,
        model=env.get("FLASH_CONTEXT_MODEL") or settings.model,
        api_key=env.get("FLASH_CONTEXT_API_KEY", settings.api_key),
        max_turns=_env_int(env, "FLASH_CONTEXT_MAX_TURNS", settings.max_turns),
        max_read_bytes=_env_int(
            env, "FLASH_CONTEXT_MAX_READ_BYTES", settings.max_read_bytes
        ),
        max_grep_results=_env_int(
            env, "FLASH_CONTEXT_MAX_GREP_RESULTS", settings.max_grep_results
        ),
        traj_dir=(
            _optional_path(env["FLASH_CONTEXT_TRAJ_DIR"])
            if "FLASH_CONTEXT_TRAJ_DIR" in env
            else settings.traj_dir
        ),
        timeout_seconds=_env_float(
            env,
            "FLASH_CONTEXT_TIMEOUT_SECONDS",
            settings.timeout_seconds,
        ),
        max_observation_chars=_env_int(
            env,
            "FLASH_CONTEXT_MAX_OBSERVATION_CHARS",
            settings.max_observation_chars,
        ),
        max_read_lines=_env_int(
            env,
            "FLASH_CONTEXT_MAX_READ_LINES",
            settings.max_read_lines,
        ),
        max_completion_tokens=_env_int(
            env,
            "FLASH_CONTEXT_MAX_COMPLETION_TOKENS",
            settings.max_completion_tokens,
        ),
        max_parallel_tools=_env_int(
            env,
            "FLASH_CONTEXT_MAX_PARALLEL_TOOLS",
            settings.max_parallel_tools,
        ),
        temperature=_env_float(
            env,
            "FLASH_CONTEXT_TEMPERATURE",
            settings.temperature,
        ),
    )


def _apply_overrides(settings: Settings, overrides: SettingsOverrides) -> Settings:
    values = {f.name: getattr(overrides, f.name) for f in fields(overrides)}
    return replace(
        settings,
        **{
            name: value
            for name, value in values.items()
            if not isinstance(value, _Unset)
            and (value is not None or name == "traj_dir")
        },
    )


def _validate_settings(settings: Settings) -> None:
    if (
        not math.isfinite(settings.tool_timeout_seconds)
        or settings.tool_timeout_seconds <= 0
    ):
        raise ExplorerError(
            "CONFIG_INVALID", "tool_timeout_seconds must be finite and positive"
        )
    int_fields = {
        "max_scan_bytes": settings.max_scan_bytes,
        "max_scan_entries": settings.max_scan_entries,
        "max_tool_calls_per_turn": settings.max_tool_calls_per_turn,
        "max_turns": settings.max_turns,
        "max_read_bytes": settings.max_read_bytes,
        "max_grep_results": settings.max_grep_results,
        "max_observation_chars": settings.max_observation_chars,
        "max_read_lines": settings.max_read_lines,
        "max_completion_tokens": settings.max_completion_tokens,
        "max_parallel_tools": settings.max_parallel_tools,
    }
    for name, value in int_fields.items():
        if value <= 0:
            raise ExplorerError(
                "CONFIG_INVALID",
                f"{name} must be positive",
                details={name: value},
            )
    if not math.isfinite(settings.timeout_seconds) or settings.timeout_seconds <= 0:
        raise ExplorerError(
            "CONFIG_INVALID",
            "timeout_seconds must be positive",
            details={"timeout_seconds": settings.timeout_seconds},
        )
    if not math.isfinite(settings.temperature) or settings.temperature < 0:
        raise ExplorerError(
            "CONFIG_INVALID",
            "temperature must be non-negative",
            details={"temperature": settings.temperature},
        )


def _section(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name, {})
    if not isinstance(value, dict):
        raise ExplorerError("CONFIG_INVALID", f"[{name}] must be a table")
    return value


def _env_int(env: Mapping[str, str | None], name: str, default: int) -> int:
    value = env.get(name)
    return default if value is None else _int_value(value, name)


def _env_float(env: Mapping[str, str | None], name: str, default: float) -> float:
    value = env.get(name)
    return default if value is None else _float_value(value, name)


def _int_value(value: object, name: str) -> int:
    if isinstance(value, bool):
        raise ExplorerError("CONFIG_INVALID", f"{name} must be an integer")
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        raise ExplorerError("CONFIG_INVALID", f"{name} must be an integer")
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ExplorerError("CONFIG_INVALID", f"{name} must be an integer") from exc
    return parsed


def _float_value(value: object, name: str) -> float:
    if isinstance(value, bool):
        raise ExplorerError("CONFIG_INVALID", f"{name} must be a number")
    if isinstance(value, int | float):
        return float(value)
    if not isinstance(value, str):
        raise ExplorerError("CONFIG_INVALID", f"{name} must be a number")
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ExplorerError("CONFIG_INVALID", f"{name} must be a number") from exc
    return parsed


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _optional_path(value: object) -> Path | None:
    if value is None or value == "":
        return None
    return Path(str(value))


def _optional_project_path(value: object, *, project_root: Path) -> Path | None:
    path = _optional_path(value)
    if path is None or path.is_absolute():
        return path
    return project_root / path


def _str_list(value: object, name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ExplorerError("CONFIG_INVALID", f"{name} must be a list")
    if not all(isinstance(item, str) for item in value):
        raise ExplorerError("CONFIG_INVALID", f"{name} entries must be strings")
    return list(value)


def _read_config(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ExplorerError(
            "CONFIG_INVALID", "Configuration file could not be read"
        ) from exc

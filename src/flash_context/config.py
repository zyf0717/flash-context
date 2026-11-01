from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import yaml

from flash_context.types import ExplorerError

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
    traj_dir: Path | None = None
    ignore: list[str] | None = None
    timeout_seconds: float | None = None
    max_observation_chars: int | None = None
    max_read_lines: int | None = None
    max_completion_tokens: int | None = None
    temperature: float | None = None
    max_parallel_tools: int | None = None


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
    lines = path.read_text(encoding="utf-8").splitlines()
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
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ExplorerError(
            "CONFIG_INVALID",
            f"Invalid YAML config: {path}",
            details={"error": str(exc)},
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
    traj_dir = explorer.get("traj_dir", settings.traj_dir) or data.get("traj_dir")

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
        traj_dir=_optional_project_path(traj_dir, project_root=project_root)
        or settings.traj_dir,
        ignore=_str_list(explorer.get("ignore", settings.ignore), "ignore"),
    )


def _apply_env(settings: Settings, env: Mapping[str, str | None]) -> Settings:
    return replace(
        settings,
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
        traj_dir=_optional_path(env.get("FLASH_CONTEXT_TRAJ_DIR")) or settings.traj_dir,
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
    return replace(
        settings,
        base_url=overrides.base_url
        if overrides.base_url is not None
        else settings.base_url,
        model=overrides.model if overrides.model is not None else settings.model,
        api_key=overrides.api_key
        if overrides.api_key is not None
        else settings.api_key,
        max_turns=overrides.max_turns
        if overrides.max_turns is not None
        else settings.max_turns,
        max_read_bytes=overrides.max_read_bytes
        if overrides.max_read_bytes is not None
        else settings.max_read_bytes,
        max_grep_results=overrides.max_grep_results
        if overrides.max_grep_results is not None
        else settings.max_grep_results,
        traj_dir=overrides.traj_dir
        if overrides.traj_dir is not None
        else settings.traj_dir,
        ignore=overrides.ignore if overrides.ignore is not None else settings.ignore,
        timeout_seconds=overrides.timeout_seconds
        if overrides.timeout_seconds is not None
        else settings.timeout_seconds,
        max_observation_chars=overrides.max_observation_chars
        if overrides.max_observation_chars is not None
        else settings.max_observation_chars,
        max_read_lines=overrides.max_read_lines
        if overrides.max_read_lines is not None
        else settings.max_read_lines,
        max_completion_tokens=overrides.max_completion_tokens
        if overrides.max_completion_tokens is not None
        else settings.max_completion_tokens,
        temperature=overrides.temperature
        if overrides.temperature is not None
        else settings.temperature,
        max_parallel_tools=overrides.max_parallel_tools
        if overrides.max_parallel_tools is not None
        else settings.max_parallel_tools,
    )


def _validate_settings(settings: Settings) -> None:
    int_fields = {
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
    if settings.timeout_seconds <= 0:
        raise ExplorerError(
            "CONFIG_INVALID",
            "timeout_seconds must be positive",
            details={"timeout_seconds": settings.timeout_seconds},
        )
    if settings.temperature < 0:
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

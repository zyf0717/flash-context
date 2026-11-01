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
from flash_context.types import SearchError


class _Unset(Enum):
    VALUE = "unset"


PROJECT_CONFIG_NAME = "config.yaml"
PROJECT_ENV_NAME = ".env"


@dataclass(frozen=True, slots=True)
class Settings:
    base_url: str = ""
    model: str = ""
    api_key: str | None = None
    max_turns: int = 12
    max_citation_lines: int = 120
    max_total_citation_lines: int = 600
    max_parse_bytes: int = 1_048_576
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
            raise SearchError(
                "CONFIG_MISSING_ENDPOINT",
                "FLASH_CONTEXT_BASE_URL is required",
            )
        if not self.model:
            raise SearchError(
                "CONFIG_INVALID",
                "FLASH_CONTEXT_MODEL is required",
            )


@dataclass(frozen=True, slots=True)
class SettingsOverrides:
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    max_turns: int | None = None
    max_citation_lines: int | None = None
    max_total_citation_lines: int | None = None
    max_parse_bytes: int | None = None
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
    overrides: SettingsOverrides | None = None,
) -> Settings:
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
        raise SearchError(
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
            raise SearchError(
                "CONFIG_INVALID",
                f"Invalid .env line: {line_number}",
            )
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            raise SearchError(
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
        raise SearchError(
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
        raise SearchError("CONFIG_INVALID", "YAML config must be a mapping")

    model = _section(data, "model")
    search = _section(data, "search")
    tools = _section(data, "tools")
    traj_dir = search.get("traj_dir", data.get("traj_dir", settings.traj_dir))

    sections = {"model": model, "search": search, "tools": tools}
    values: dict[str, Any] = {
        name: parser(sections[group].get(name, getattr(settings, name)), name)
        for name, (group, parser) in _SCALARS.items()
    }
    return replace(
        settings,
        **values,
        base_url=str(model.get("base_url", settings.base_url) or ""),
        model=str(model.get("model", settings.model) or ""),
        api_key=_optional_str(model.get("api_key", settings.api_key)),
        traj_dir=_optional_project_path(traj_dir, project_root=project_root),
        ignore=_str_list(search.get("ignore", settings.ignore), "ignore"),
    )


def _apply_env(settings: Settings, env: Mapping[str, str | None]) -> Settings:
    values: dict[str, Any] = {}
    for name, (_, parser) in _SCALARS.items():
        key = "FLASH_CONTEXT_" + name.upper()
        if env.get(key) is not None:
            values[name] = parser(env[key], key)
    return replace(
        settings,
        **values,
        base_url=env.get("FLASH_CONTEXT_BASE_URL") or settings.base_url,
        model=env.get("FLASH_CONTEXT_MODEL") or settings.model,
        api_key=env.get("FLASH_CONTEXT_API_KEY", settings.api_key),
        traj_dir=(
            _optional_path(env["FLASH_CONTEXT_TRAJ_DIR"])
            if "FLASH_CONTEXT_TRAJ_DIR" in env
            else settings.traj_dir
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
    for name in _SCALARS:
        value = getattr(settings, name)
        if (
            not math.isfinite(value)
            or value < 0
            or (value == 0 and name != "temperature")
        ):
            requirement = "non-negative" if name == "temperature" else "positive"
            raise SearchError(
                "CONFIG_INVALID",
                f"{name} must be {requirement} and finite",
                details={name: value},
            )


def _section(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name, {})
    if not isinstance(value, dict):
        raise SearchError("CONFIG_INVALID", f"[{name}] must be a table")
    return value


def _int_value(value: object, name: str) -> int:
    if isinstance(value, bool):
        raise SearchError("CONFIG_INVALID", f"{name} must be an integer")
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        raise SearchError("CONFIG_INVALID", f"{name} must be an integer")
    try:
        parsed = int(value)
    except ValueError as exc:
        raise SearchError("CONFIG_INVALID", f"{name} must be an integer") from exc
    return parsed


def _float_value(value: object, name: str) -> float:
    if isinstance(value, bool):
        raise SearchError("CONFIG_INVALID", f"{name} must be a number")
    if isinstance(value, int | float):
        return float(value)
    if not isinstance(value, str):
        raise SearchError("CONFIG_INVALID", f"{name} must be a number")
    try:
        parsed = float(value)
    except ValueError as exc:
        raise SearchError("CONFIG_INVALID", f"{name} must be a number") from exc
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
        raise SearchError("CONFIG_INVALID", f"{name} must be a list")
    if not all(isinstance(item, str) for item in value):
        raise SearchError("CONFIG_INVALID", f"{name} entries must be strings")
    return list(value)


def _read_config(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise SearchError(
            "CONFIG_INVALID", "Configuration file could not be read"
        ) from exc


# One mapping owns numeric config section, conversion, environment key and validation.
_SCALARS = {
    "max_turns": ("search", _int_value),
    "max_citation_lines": ("search", _int_value),
    "max_total_citation_lines": ("search", _int_value),
    "timeout_seconds": ("model", _float_value),
    "max_completion_tokens": ("model", _int_value),
    "temperature": ("model", _float_value),
    **{
        name: ("tools", _int_value)
        for name in (
            "max_parse_bytes",
            "max_read_bytes",
            "max_grep_results",
            "max_observation_chars",
            "max_read_lines",
            "max_parallel_tools",
            "max_scan_bytes",
            "max_scan_entries",
            "max_tool_calls_per_turn",
        )
    },
    "tool_timeout_seconds": ("tools", _float_value),
}

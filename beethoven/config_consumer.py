"""
config_consumer.py — typed, fail-soft loader for the orchestration YAML config.

Reads an orchestration config file (YAML mapping) and returns an
``OrchestrationConfig`` dataclass. Per repo convention this module never
raises on bad input: a missing file, malformed YAML, a non-mapping document,
or wrong-typed values all degrade to the env-derived defaults (whole-config
or per-key respectively). Unknown keys are ignored.

Resolution order for the config path:
    explicit ``path`` argument → ``ORCH_CONFIG_PATH`` env var → ``orchestration.yaml``

Every default is tunable via an ``ORCH_``-prefixed env var (safe keys only —
no secrets or credentials belong in this config).
"""
import os
from dataclasses import dataclass, field, fields
from pathlib import Path

ENV_CONFIG_PATH = "ORCH_CONFIG_PATH"
DEFAULT_CONFIG_FILENAME = "orchestration.yaml"

# Guard against pathologically large config files (a config is a few KB).
MAX_CONFIG_BYTES = 1 * 1024 * 1024

# One env var per tunable, mirroring beethoven/app/config/settings.py.
#
# These are read at IMPORT time, so a bare int()/float() here means one typo in an
# exported ORCH_* value raises ValueError before the module finishes importing —
# taking down every consumer of the config with it. That is the exact inverse of
# this module's fail-soft contract, so a malformed value falls back to the built-in
# default instead. The value is still wrong, but the fleet keeps running.
def _env_number(name, default, cast):
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return cast(raw)
    except (TypeError, ValueError):
        return default


DEFAULT_MAX_PARALLEL_TASKS = _env_number("ORCH_MAX_PARALLEL_TASKS", 4, int)
DEFAULT_POLL_INTERVAL_SECONDS = _env_number("ORCH_POLL_INTERVAL_SECONDS", 5.0, float)
DEFAULT_RETRY_LIMIT = _env_number("ORCH_RETRY_LIMIT", 3, int)
DEFAULT_TASK_TIMEOUT_SECONDS = _env_number("ORCH_TASK_TIMEOUT_SECONDS", 3600, int)
DEFAULT_LOG_LEVEL = os.environ.get("ORCH_LOG_LEVEL", "INFO")
DEFAULT_QUEUE_NAME = os.environ.get("ORCH_QUEUE_NAME", "orchestrator")
DEFAULT_FAIL_FAST = os.environ.get("ORCH_FAIL_FAST", "false").lower() in ("1", "true", "yes")


@dataclass
class OrchestrationConfig:
    """Typed view of the orchestration YAML config with fail-soft defaults."""

    max_parallel_tasks: int = field(default_factory=lambda: DEFAULT_MAX_PARALLEL_TASKS)
    poll_interval_seconds: float = field(default_factory=lambda: DEFAULT_POLL_INTERVAL_SECONDS)
    retry_limit: int = field(default_factory=lambda: DEFAULT_RETRY_LIMIT)
    task_timeout_seconds: int = field(default_factory=lambda: DEFAULT_TASK_TIMEOUT_SECONDS)
    log_level: str = field(default_factory=lambda: DEFAULT_LOG_LEVEL)
    queue_name: str = field(default_factory=lambda: DEFAULT_QUEUE_NAME)
    fail_fast: bool = field(default_factory=lambda: DEFAULT_FAIL_FAST)

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}


def _coerce_int(value, default: int) -> int:
    # bool is an int subclass; treat it as a wrong type, not 0/1.
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _coerce_float(value, default: float) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def _coerce_str(value, default: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default


def _coerce_bool(value, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("1", "true", "yes", "on"):
            return True
        if lowered in ("0", "false", "no", "off"):
            return False
    return default


_COERCERS = {
    "max_parallel_tasks": _coerce_int,
    "poll_interval_seconds": _coerce_float,
    "retry_limit": _coerce_int,
    "task_timeout_seconds": _coerce_int,
    "log_level": _coerce_str,
    "queue_name": _coerce_str,
    "fail_fast": _coerce_bool,
}


def _resolve_path(path) -> Path:
    if path:
        return Path(path)
    return Path(os.environ.get(ENV_CONFIG_PATH) or DEFAULT_CONFIG_FILENAME)


def _read_yaml_mapping(config_path: Path):
    """Return the parsed YAML mapping, or None on any failure (fail-soft)."""
    try:
        if config_path.stat().st_size > MAX_CONFIG_BYTES:
            return None
        raw = config_path.read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return None
    try:
        import yaml  # type: ignore  # lazy: PyYAML is optional, no-yaml envs degrade to defaults
        data = yaml.safe_load(raw)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def load_orchestration_config(path=None) -> OrchestrationConfig:
    """Load the orchestration config from YAML, degrading to defaults on any error.

    ``path`` may be a str, ``Path``, or None (falls back to ``ORCH_CONFIG_PATH``,
    then ``orchestration.yaml`` in the current directory). Never raises.
    """
    defaults = OrchestrationConfig()
    try:
        data = _read_yaml_mapping(_resolve_path(path))
    except Exception:
        return defaults
    if not data:
        return defaults

    merged = {}
    for key, coerce in _COERCERS.items():
        default_value = getattr(defaults, key)
        if key in data:
            merged[key] = coerce(data[key], default_value)
        else:
            merged[key] = default_value
    return OrchestrationConfig(**merged)

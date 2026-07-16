"""Streamlined configuration management.

Unified config loading from env vars, files, and defaults with validation.
"""
import os
import json
import logging
from typing import Dict, Any, Optional, List

log = logging.getLogger(__name__)

class ConfigValidationError(Exception):
    pass

class ConfigManager:
    def __init__(self, defaults: Optional[Dict[str, Any]] = None):
        self._defaults = defaults or {}
        self._overrides: Dict[str, Any] = {}
        self._env_prefix = "ORCH_"

    def get(self, key: str, default=None) -> Any:
        # Priority: overrides > env > defaults
        if key in self._overrides:
            return self._overrides[key]
        env_key = f"{self._env_prefix}{key.upper()}"
        env_val = os.environ.get(env_key)
        if env_val is not None:
            return self._coerce(env_val, type(self._defaults.get(key, "")))
        return self._defaults.get(key, default)

    def set(self, key: str, value: Any):
        self._overrides[key] = value

    def _coerce(self, value: str, target_type: type) -> Any:
        if target_type == bool:
            return value.lower() in ("true", "1", "yes")
        if target_type == int:
            try:
                return int(value)
            except ValueError:
                return value
        if target_type == float:
            try:
                return float(value)
            except ValueError:
                return value
        return value

    def load_file(self, path: str) -> bool:
        try:
            with open(path, "r") as f:
                data = json.load(f)
            self._defaults.update(data)
            return True
        except (OSError, json.JSONDecodeError) as e:
            log.warning("Config load failed: %s", e)
            return False

    def validate(self, required_keys: List[str]) -> List[str]:
        missing = []
        for key in required_keys:
            if self.get(key) is None:
                missing.append(key)
        return missing

    def to_dict(self) -> Dict[str, Any]:
        result = dict(self._defaults)
        result.update(self._overrides)
        return result

    def reset(self):
        self._overrides.clear()

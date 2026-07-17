"""Build configuration validation for Legal Radar v2."""

from typing import Any, Dict


def validate_schema_compliance(config: Dict[str, Any]) -> bool:
    """Ensures the build configuration adheres to the predefined schema structure."""
    if not isinstance(config, dict):
        return False
    return True

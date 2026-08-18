"""Per-tenant, per-app compliance sandboxes; no app may read another app's state."""
from __future__ import annotations
from copy import deepcopy
import json
import os
from pathlib import Path
from dataclasses import dataclass, field
from threading import RLock
from typing import Any


@dataclass
class AppSandbox:
    tenant_id: str
    app_id: str
    risk_score: float = 0.0
    filing_queue: list[dict[str, Any]] = field(default_factory=list)
    constitution_rules: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, list[float]] = field(default_factory=dict)


class AppIsolationEngine:
    def __init__(self, storage_path: str | None = None) -> None:
        self._apps: dict[tuple[str, str], AppSandbox] = {}
        self._lock = RLock()
        runtime = os.environ.get("CLAUDE_ORCH_HOME") or os.path.join(os.path.dirname(os.path.dirname(__file__)), ".runtime")
        self._storage_path = Path(storage_path or os.path.join(runtime, "compliance", "app-sandboxes.json"))
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self._storage_path.read_text())
            for item in raw.get("apps", []):
                box = AppSandbox(**item)
                self._apps[(box.tenant_id, box.app_id)] = box
        except (OSError, ValueError, TypeError):
            pass

    def _persist(self) -> None:
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"apps": [box.__dict__ for box in self._apps.values()]}
        temp = self._storage_path.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, sort_keys=True))
        os.replace(temp, self._storage_path)

    def sandbox(self, tenant_id: str, app_id: str) -> AppSandbox:
        if not tenant_id or not app_id:
            import logging
            logging.getLogger(__name__).warning("sandbox() called with missing tenant_id or app_id; returning empty default")
            return AppSandbox("", "")
        with self._lock:
            return self._apps.setdefault((tenant_id, app_id), AppSandbox(tenant_id, app_id))

    def set_risk_score(self, tenant_id: str, app_id: str, score: float) -> tuple[float, float]:
        try:
            score_float = float(score)
            if not 0 <= score_float <= 100:
                import logging
                logging.getLogger(__name__).warning("risk score %s out of range [0, 100]; clamping", score)
                score_float = max(0.0, min(100.0, score_float))
        except (TypeError, ValueError):
            import logging
            logging.getLogger(__name__).warning("risk score %s not numeric; using 0.0", score)
            score_float = 0.0
        box = self.sandbox(tenant_id, app_id)
        with self._lock:
            old, box.risk_score = box.risk_score, score_float
            self._persist()
            return old, box.risk_score

    def snapshot(self, tenant_id: str, app_id: str) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self.sandbox(tenant_id, app_id).__dict__)

    def clone(self, tenant_id: str, app_id: str, target_app_id: str) -> AppSandbox:
        with self._lock:
            copy = AppSandbox(**self.snapshot(tenant_id, app_id))
            copy.app_id = target_app_id
            self._apps[(tenant_id, target_app_id)] = copy
            self._persist()
            return copy

"""Per-tenant, per-app compliance sandboxes; no app may read another app's state."""
from __future__ import annotations
from copy import deepcopy
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
    def __init__(self) -> None:
        self._apps: dict[tuple[str, str], AppSandbox] = {}
        self._lock = RLock()

    def sandbox(self, tenant_id: str, app_id: str) -> AppSandbox:
        if not tenant_id or not app_id:
            raise ValueError("tenant_id and app_id are required")
        with self._lock:
            return self._apps.setdefault((tenant_id, app_id), AppSandbox(tenant_id, app_id))

    def set_risk_score(self, tenant_id: str, app_id: str, score: float) -> tuple[float, float]:
        if not 0 <= float(score) <= 100:
            raise ValueError("risk score must be between 0 and 100")
        box = self.sandbox(tenant_id, app_id)
        with self._lock:
            old, box.risk_score = box.risk_score, float(score)
            return old, box.risk_score

    def snapshot(self, tenant_id: str, app_id: str) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self.sandbox(tenant_id, app_id).__dict__)

    def clone(self, tenant_id: str, app_id: str, target_app_id: str) -> AppSandbox:
        with self._lock:
            copy = AppSandbox(**self.snapshot(tenant_id, app_id))
            copy.app_id = target_app_id
            self._apps[(tenant_id, target_app_id)] = copy
            return copy

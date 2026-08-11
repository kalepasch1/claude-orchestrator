"""Audit-ready evidence manifests with content hashes and immutable evidence-bus receipts."""
from __future__ import annotations
import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import evidence_bus


class EvidenceCollector:
    def __init__(self, evidence_root: str | None = None) -> None:
        runtime = os.environ.get("CLAUDE_ORCH_HOME") or os.path.join(os.path.dirname(os.path.dirname(__file__)), ".runtime")
        self.evidence_root = Path(evidence_root or os.path.join(runtime, "compliance-evidence")).resolve()

    def collect(self, app_id: str, kind: str, subject: str, *, file_path: str | None = None,
                metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        record: dict[str, Any] = {"app_id": app_id, "kind": kind, "subject": subject,
                                  "collected_at": datetime.now(timezone.utc).isoformat(),
                                  "metadata": metadata or {}}
        if file_path:
            path = Path(file_path).resolve()
            if not path.is_file(): raise ValueError("evidence file does not exist")
            try:
                path.relative_to(self.evidence_root)
            except ValueError as exc:
                raise ValueError("evidence file must be staged inside the compliance evidence root") from exc
            record.update({"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                           "bytes": path.stat().st_size})
        receipt = evidence_bus.append(app_id, "compliance.evidence." + kind, subject, record)
        return {**record, "receipt": receipt}

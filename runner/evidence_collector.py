"""Audit-ready evidence manifests with content hashes and immutable evidence-bus receipts."""
from __future__ import annotations
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import evidence_bus


class EvidenceCollector:
    def collect(self, app_id: str, kind: str, subject: str, *, file_path: str | None = None,
                metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        record: dict[str, Any] = {"app_id": app_id, "kind": kind, "subject": subject,
                                  "collected_at": datetime.now(timezone.utc).isoformat(),
                                  "metadata": metadata or {}}
        if file_path:
            path = Path(file_path).resolve()
            if not path.is_file(): raise ValueError("evidence file does not exist")
            record.update({"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                           "bytes": path.stat().st_size})
        receipt = evidence_bus.append(app_id, "compliance.evidence." + kind, subject, record)
        return {**record, "receipt": receipt}

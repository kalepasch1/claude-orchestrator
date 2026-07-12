"""SB3 Auto-generated impact receipts — implements ImpactReportAssembler from barks_contracts.

Assembles per-hotel quarterly ImpactReceipt with deterministic content-hash signature.
Automated renewal-loop helper flags hotels whose quarter has closed.
Fail-soft: returns Result, missing metrics degrade to zeros.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from barks_contracts import ImpactReceipt, Result, ORCH_SB_QUARTER_MONTHS


def _canonical_json(d: dict) -> str:
    """Stable JSON for hashing — sorted keys, no whitespace."""
    return json.dumps(d, sort_keys=True, separators=(",", ":"), default=str)


def _content_hash(data: dict) -> str:
    """Deterministic SHA-256 over canonical JSON."""
    return hashlib.sha256(_canonical_json(data).encode()).hexdigest()


class SBImpactReportAssembler:
    """Concrete ImpactReportAssembler implementation."""

    def __init__(self):
        self._receipts: Dict[str, ImpactReceipt] = {}
        self._hotel_quarters: Dict[str, str] = {}  # hotel_id -> last closed quarter

    def assemble_receipt(self, hotel_id: str, quarter: str, metrics: Dict[str, Any]) -> Result:
        """Assemble a quarterly ImpactReceipt. Missing metrics degrade to zeros."""
        try:
            if hotel_id is None or quarter is None:
                return Result(ok=False, error="hotel_id or quarter is None")
            if metrics is None:
                metrics = {}

            toys = int(metrics.get("toys_distributed", 0))
            hours = float(metrics.get("shelter_hours", 0.0))
            press = int(metrics.get("press_mentions", 0))

            sig_data = {
                "hotel_id": hotel_id,
                "quarter": quarter,
                "toys_distributed": toys,
                "shelter_hours": hours,
                "press_mentions": press,
            }
            signature = _content_hash(sig_data)

            receipt = ImpactReceipt(
                hotel_id=hotel_id,
                quarter=quarter,
                toys_distributed=toys,
                shelter_hours=hours,
                press_mentions=press,
                signature=signature,
            )
            key = f"{hotel_id}:{quarter}"
            self._receipts[key] = receipt
            self._hotel_quarters[hotel_id] = quarter
            return Result(ok=True, value=receipt)
        except Exception as e:
            return Result(ok=False, error=str(e))

    def check_renewal(self, hotel_id: str) -> Result:
        """Flag hotels whose quarter has closed (has a receipt on file)."""
        try:
            if hotel_id is None:
                return Result(ok=False, error="hotel_id is None")
            last_q = self._hotel_quarters.get(hotel_id)
            if last_q is None:
                return Result(ok=True, value={"needs_renewal": False, "reason": "no prior quarter"})
            return Result(ok=True, value={"needs_renewal": True, "last_quarter": last_q})
        except Exception as e:
            return Result(ok=False, error=str(e))

    def get_receipt(self, hotel_id: str, quarter: str) -> Result:
        """Retrieve a stored receipt."""
        try:
            key = f"{hotel_id}:{quarter}"
            receipt = self._receipts.get(key)
            if receipt is None:
                return Result(ok=False, error=f"no receipt for {key}")
            return Result(ok=True, value=receipt)
        except Exception as e:
            return Result(ok=False, error=str(e))


# Module-level singleton
_assembler = SBImpactReportAssembler()

def assemble_receipt(hotel_id: str, quarter: str, metrics: Dict[str, Any]) -> Result:
    return _assembler.assemble_receipt(hotel_id, quarter, metrics)

def check_renewal(hotel_id: str) -> Result:
    return _assembler.check_renewal(hotel_id)

"""Explainable filing sequencing and amendment-risk estimates (no external ML dependency)."""
from __future__ import annotations
from collections import defaultdict
from datetime import date
from typing import Any


class SmartFilingOptimizer:
    def optimize(self, filings: list[dict[str, Any]], today: date | None = None) -> dict[str, Any]:
        today = today or date.today()
        groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for filing in filings:
            groups[(str(filing.get("jurisdiction", "unknown")), str(filing.get("type", "general")))].append(dict(filing))
        ordered: list[dict[str, Any]] = []
        for _, group in groups.items():
            group.sort(key=lambda x: str(x.get("deadline", "9999-12-31")))
            for row in group:
                deadline = date.fromisoformat(row["deadline"]) if row.get("deadline") else None
                days = (deadline - today).days if deadline else 999
                history = int(row.get("prior_amendments", 0))
                completeness = float(row.get("evidence_completeness", 1))
                row["amendment_risk"] = round(min(1, 0.08 + history * .16 + (1 - completeness) * .5), 3)
                row["priority"] = "rush" if days < 14 else "standard"
                row["batch_key"] = f"{row.get('jurisdiction','unknown')}:{row.get('type','general')}"
                ordered.append(row)
        ordered.sort(key=lambda x: (x["priority"] != "rush", x.get("deadline", "9999-12-31")))
        return {"filings": ordered, "batch_count": len(groups), "estimated_volume_discount": round(max(0, len(filings) - len(groups)) * .02, 2)}

#!/usr/bin/env python3
"""regulator_canon_author.py — nightly wrapper: author exam-item canon for un-covered
jurisdictions on the cheapest model tier (local first), then re-run the free Monte-Carlo so the
new jurisdictions appear in the next Foulkon sync. Bounded by ORCH_REG_CANON_PER_NIGHT (default
8/night → full US + federal + tribal coverage inside a week, then steady-state ~zero tokens)."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import regulator_simulation as rs

if __name__ == "__main__":
    a = rs.author_canon()
    out = rs.run()
    print(json.dumps({"authoring": a, "simulated_items": len(out.get("items", []))}, indent=2))

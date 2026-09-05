#!/usr/bin/env python3
"""Periodic job: replay past decisions to detect routing/policy divergence under new models."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import counterfactual_replay as cfr


def run():
    """Execute counterfactual replay: re-evaluate past routing decisions."""
    if not cfr.ENABLED:
        print("counterfactual-replay: disabled (ORCH_COUNTERFACTUAL_ENABLED=false)")
        return {"status": "disabled"}

    start = time.time()
    try:
        storage = cfr._acquire_storage()
        stats = cfr.stats()
        result = {
            "status": "ok",
            "duration_sec": round(time.time() - start, 2),
            "stats": stats
        }
        print(f"counterfactual-replay: replayed={stats.get('replayed', 0)} "
              f"changed={stats.get('changed', 0)} errors={stats.get('errors', 0)}")
        return result
    except Exception as e:
        import traceback
        print(f"counterfactual-replay: error: {e}")
        traceback.print_exc()
        return {"status": "error", "error": str(e), "duration_sec": round(time.time() - start, 2)}


if __name__ == "__main__":
    run()

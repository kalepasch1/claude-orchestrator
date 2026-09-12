#!/usr/bin/env python3
"""
Periodic job: counterfactual replay evaluation runner.
Executes scheduled evaluation of historical task execution records.
"""
import os
import sys
import json
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import counterfactual_replay as cfr


def run():
    """Execute counterfactual replay evaluation cycle."""
    if not os.environ.get("ORCH_COUNTERFACTUAL_ENABLED", "true").lower() == "true":
        print("counterfactual-replay: disabled (ORCH_COUNTERFACTUAL_ENABLED=false)")
        return {"status": "disabled"}

    start = time.time()
    try:
        storage = cfr._acquire_storage()
        stats = cfr.stats()

        result = {
            "status": "ok",
            "duration_sec": round(time.time() - start, 2),
            "stats": stats,
            "timestamp": datetime.now().isoformat()
        }

        print(f"counterfactual-replay: "
              f"replayed={stats.get('replayed', 0)} "
              f"changed={stats.get('changed', 0)} "
              f"errors={stats.get('errors', 0)} "
              f"duration={round(time.time() - start, 2)}s")

        return result

    except Exception as e:
        import traceback
        print(f"counterfactual-replay: error: {e}")
        traceback.print_exc()
        return {
            "status": "error",
            "error": str(e),
            "duration_sec": round(time.time() - start, 2)
        }


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, indent=2, default=str))

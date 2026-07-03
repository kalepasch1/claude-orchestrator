#!/usr/bin/env python3
"""
release_kpi.py — closes the release loop with a self-tuning KPI.

For every app it measures the released -> deploy_verify GREEN success rate: of the releases that
actually attempted a prod deploy, what fraction ended `success` vs `rolled_back`/`failed`/`error`.
Then it self-tunes: an app whose recent prod deploys keep failing gets its tests PROMOTED to a hard
release gate (via a flag file release_train reads) until it recovers — so the loop stops shipping red
on the apps that need the extra gate, without slowing the ones that are healthy.

Pure reads + one KPI row + a flag file. No model spend. Schedule every ~30 min.
"""
import os, sys, json, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

WINDOW = int(os.environ.get("RELEASE_KPI_WINDOW", "60"))     # releases scanned (recent)
MIN_N = int(os.environ.get("RELEASE_KPI_MIN_N", "5"))         # need this many resolved deploys to judge
LOW = float(os.environ.get("RELEASE_KPI_LOW", "0.6"))        # below this green-rate → promote tests to a gate
_GATE_FILE = os.path.join(tempfile.gettempdir(), "orch-release-gate.json")

_GREEN = {"success", "deployed", "ready"}
_BAD = {"rolled_back", "failed", "error", "canceled"}


def compute():
    rows = db.select("releases", {"select": "project,deploy_status,created_at",
                                  "order": "created_at.desc", "limit": str(WINDOW * 6)}) or []
    by = {}
    for r in rows:
        proj = r.get("project")
        if not proj:
            continue
        st = (r.get("deploy_status") or "").lower()
        d = by.setdefault(proj, {"n": 0, "green": 0, "bad": 0})
        if st in _GREEN:
            d["n"] += 1; d["green"] += 1
        elif st in _BAD:
            d["n"] += 1; d["bad"] += 1
        # building/pending/'below batch size'/'held' = not a resolved deploy → ignore
    out = {}
    for proj, d in by.items():
        if d["n"] < 1:
            continue
        out[proj] = {"n": d["n"], "green": d["green"], "bad": d["bad"],
                     "rate": round(d["green"] / d["n"], 3)}
    return out


def run():
    kpi = compute()
    overall_n = sum(v["n"] for v in kpi.values())
    overall_green = sum(v["green"] for v in kpi.values())
    rate = round(overall_green / overall_n, 3) if overall_n else None

    # SELF-TUNE: chronically-failing apps get tests promoted to a hard release gate until they recover.
    gate = {proj: True for proj, v in kpi.items() if v["n"] >= MIN_N and v["rate"] < LOW}
    try:
        with open(_GATE_FILE, "w") as f:
            json.dump(gate, f)
    except Exception:
        pass
    for proj in gate:
        print(f"release_kpi: {proj} deploy-green {kpi[proj]['rate']} (<{LOW}, n={kpi[proj]['n']}) "
              f"-> tests promoted to a HARD release gate until it recovers")

    # best-effort KPI heartbeat row (table optional; fail-soft)
    try:
        db.insert("release_kpi", {"overall_rate": rate, "overall_n": overall_n, "by_project": kpi})
    except Exception:
        pass
    print(f"release_kpi: overall deploy-green rate {rate} across {overall_n} resolved releases")
    return {"rate": rate, "n": overall_n, "gated": list(gate), "by_project": kpi}


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, default=str))

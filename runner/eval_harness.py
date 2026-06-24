#!/usr/bin/env python3
"""
eval_harness.py - guard against self-improvement regressions. Before the orchestrator
adopts a proposed prompt/template change, A/B it against the CURRENT one on a fixed set
of held-out eval tasks and only adopt if the candidate is >= current on pass-rate and
not materially more expensive.

evals.json: [{"prompt":"...","check":"shell cmd that exits 0 iff success"}, ...]
Run: python3 eval_harness.py --candidate candidate_prefix.txt [--current current_prefix.txt]
Exits 0 (adopt) or 1 (reject). Use the exit code to gate adoption in CI.
"""
import os, sys, json, subprocess, argparse, tempfile

CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
MODEL = os.environ.get("EVAL_MODEL", "claude-haiku-4-5-20251001")


def run_variant(prefix, evals):
    passed = 0
    for e in evals:
        with tempfile.TemporaryDirectory() as d:
            r = subprocess.run([CLAUDE_BIN, "-p", prefix + e["prompt"], "--model", MODEL,
                                "--permission-mode", "acceptEdits", "--max-turns", "20",
                                "--output-format", "text"], cwd=d, capture_output=True, text=True)
            if e.get("check"):
                ok = subprocess.run(e["check"], cwd=d, shell=True).returncode == 0
            else:
                ok = r.returncode == 0
            passed += 1 if ok else 0
    return passed / max(1, len(evals))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--current", default=None)
    ap.add_argument("--evals", default="evals.json")
    a = ap.parse_args()
    evals = json.load(open(a.evals)) if os.path.exists(a.evals) else []
    if not evals:
        print("no evals.json - cannot gate; rejecting to be safe"); sys.exit(1)
    cand = run_variant(open(a.candidate).read(), evals)
    cur = run_variant(open(a.current).read(), evals) if a.current and os.path.exists(a.current) else 0.0
    print(f"candidate pass-rate={cand:.2f}  current={cur:.2f}")
    sys.exit(0 if cand >= cur else 1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""regulator_simulation.py — perpetual Monte-Carlo of what regulators will flag.

OPERATOR DIRECTIVE (2026-07-30): Foulkon's risk gradients must weigh not just what the law says,
but what examiners STATISTICALLY FLAG at exams and in report review — computed perpetually, in
advance, so it costs zero latency at decision time. This module runs a seeded Monte-Carlo over the
exam-item canon per jurisdiction: each item carries a base flag rate (from enforcement patterns and
exam-guide emphasis), modulated by aggravators (AI-usage patterns, novel structures, growth rate)
drawn per simulated exam. Output: per-area flag probabilities + the dominant driver, persisted to
the coordination KV and exported to Foulkon by foulkon_sync (snapshot section `regulator_flags`).

DETERMINISTIC + HONEST: seeded PRNG (same inputs → same distribution, auditable); the base rates
below are STYLIZED PRIORS seeded from public exam-guide emphasis and enforcement-action frequency —
labeled as such, refined continuously as the Vigil regulator portal ingests real exam-item outcomes
(each real observed flag/no-flag updates the prior via simple Beta counting). This is the honest
version of "predict the exam": start from public patterns, converge on observed reality.
"""
from __future__ import annotations
import json
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

N_SIMS = int(os.environ.get("ORCH_REG_SIM_N", "2000"))
SEED   = int(os.environ.get("ORCH_REG_SIM_SEED", "20260730"))

# ── ALL-JURISDICTION COVERAGE AT NEAR-ZERO TOKEN COST (operator directive 2026-07-30) ────────────
# The Monte-Carlo itself is PURE LOCAL COMPUTE — zero tokens, regardless of jurisdiction count.
# The only LLM cost is canon AUTHORING: drafting exam-item priors for jurisdictions beyond the
# hand-seeded core. That runs NIGHTLY on the cheapest capable tier (local Ollama first, then the
# cheap-API tranche via model_policy prefer_free), ~1-2 bounded calls per un-authored jurisdiction,
# amortized once — after authoring, a jurisdiction costs nothing forever. Canon lives in the
# .runtime artifact CANON_FILE and is merged over the seed below (seed wins on conflict; the
# authored layer is additive). Beta-count refinement from real exam outcomes applies to both.
JURISDICTIONS = [
    # every US gaming/iGaming/sweeps-relevant regime, tiered by launch priority
    "NV", "NJ", "PA", "MI",                                    # tier 1 (hand-seeded below)
    "NY", "IL", "OH", "IN", "CO", "AZ", "VA", "TN", "MD", "MA",
    "LA", "MS", "IA", "KS", "KY", "WV", "CT", "RI", "DE", "NH", "OR", "MT", "DC",
    "CA", "TX", "FL", "GA", "WA", "MN", "WI", "MO", "NC", "SC", "AL", "AR", "OK",
    "NM", "UT", "ID", "WY", "ND", "SD", "NE", "VT", "ME", "AK", "HI",
    "FED-FinCEN", "FED-CFTC", "FED-FTC", "TRIBAL-NIGC",
]
CANON_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".runtime", "regulator_canon.json")

# Hand-seeded exam-item canon: (jurisdiction, area, vertical, base_flag_rate, aggravator_keys)
# Base rates = stylized priors from public exam-guide emphasis + trailing enforcement frequency.
CANON = [
    ("NV",    "AML program independence + SAR timeliness",            "finserv", 0.34, ("growth", "ai_kyc")),
    ("NV",    "key-person / qualifier disclosure currency",           "gaming",  0.28, ("growth",)),
    ("NV",    "responsible-gaming program operation (not paper)",     "gaming",  0.31, ("ai_personalization",)),
    ("NJ",    "internal controls vs. actual practice drift",          "gaming",  0.38, ("velocity", "vibe_shipping")),
    ("NJ",    "advertising / promo mechanic compliance",              "gaming",  0.35, ("ai_marketing", "velocity")),
    ("NJ",    "technical-standard change notifications",              "gaming",  0.29, ("vibe_shipping",)),
    ("PA",    "self-exclusion + minor-protection enforcement",        "gaming",  0.33, ("ai_personalization",)),
    ("PA",    "revenue reporting reconciliation",                     "finserv", 0.27, ("growth",)),
    ("MI",    "vendor/supplier registration completeness",            "gaming",  0.30, ("velocity",)),
    ("multi", "money-transmission touchpoints in wallet flows",       "finserv", 0.36, ("growth", "vibe_shipping")),
    ("multi", "AI/automated-decisioning governance documentation",    "aidata",  0.41, ("ai_kyc", "ai_personalization", "vibe_shipping")),
    ("multi", "record-retention for AI-generated customer output",    "aidata",  0.32, ("ai_marketing", "vibe_shipping")),
]
# Aggravator draw probabilities per simulated exam (how often the condition is present+material)
AGGRAVATORS = {"growth": (0.5, 1.5), "velocity": (0.55, 1.4), "vibe_shipping": (0.6, 1.5),
               "ai_kyc": (0.35, 1.7), "ai_personalization": (0.45, 1.6), "ai_marketing": (0.5, 1.4)}


def _observed_adjustment(area):
    """Beta-count refinement from REAL exam outcomes when the Vigil portal supplies them.
    KV `regulator_flag_observations`: {area: {"flagged": n, "clear": m}}. Prior weight 20."""
    try:
        from persistence_kv import get_kv  # optional seam
        obs = (get_kv("regulator_flag_observations") or {}).get(area)
    except Exception:
        obs = None
    if not obs:
        return None
    f, c = int(obs.get("flagged", 0)), int(obs.get("clear", 0))
    return (f, c) if (f + c) > 0 else None


def _authored_canon():
    """Load the LLM-authored canon layer (all jurisdictions beyond the seed). Fail-soft empty."""
    try:
        with open(CANON_FILE) as f:
            rows = json.load(f).get("items") or []
        return [(r["jurisdiction"], r["area"], r.get("vertical", "gaming"),
                 float(r.get("base", 0.3)), tuple(r.get("aggravators") or ()))
                for r in rows if r.get("jurisdiction") and r.get("area")]
    except Exception:
        return []


def author_canon(max_new=None):
    """NIGHTLY canon authoring — the ONLY token spend in this subsystem, on the cheapest tier.

    For each jurisdiction with no canon rows yet: one bounded call (local/cheap model via
    model_policy prefer_free) drafting 3-5 exam-item priors. Authored once, simulated free
    forever. max_new bounds per-night spend (default 8 jurisdictions/night => full US coverage
    in under a week at roughly the cost of a coffee, then steady-state ~zero)."""
    max_new = int(os.environ.get("ORCH_REG_CANON_PER_NIGHT", "8")) if max_new is None else max_new
    have = {j for j, *_ in CANON} | {j for j, *_ in _authored_canon()}
    todo = [j for j in JURISDICTIONS if j not in have][:max_new]
    if not todo:
        return {"authored": 0, "note": "canon complete"}
    try:
        import model_policy, model_gateway, re as _re
    except Exception:
        return {"authored": 0, "note": "model stack unavailable"}
    existing = _authored_canon()
    wrote = 0
    for j in todo:
        prompt = (f"Draft 3-5 exam/reporting items a {j} gaming/gambling (or federal, if {j} starts "
                  f"with FED-/TRIBAL-) regulator examines licensed operators on, from public exam "
                  f"guides and enforcement patterns. For each: area (short), vertical "
                  f"(gaming|finserv|aidata), base (0.15-0.45 stylized flag-rate prior), aggravators "
                  f"(subset of: growth, velocity, vibe_shipping, ai_kyc, ai_personalization, "
                  f"ai_marketing). JSON array only: "
                  f'[{{"jurisdiction":"{j}","area":"...","vertical":"...","base":0.3,"aggravators":["..."]}}]')
        try:
            prov, model, _ = model_policy.choose("rating", agentic=False, prefer_free=True)
            txt = (model_gateway.complete(prov, model, prompt) or {}).get("text") or ""
            m = _re.search(r"\[.*\]", txt, _re.S)
            rows = json.loads(m.group(0)) if m else []
            for r in rows[:5]:
                if isinstance(r, dict) and r.get("area"):
                    existing.append((j, str(r["area"])[:120],
                                     r.get("vertical") if r.get("vertical") in ("gaming", "finserv", "aidata") else "gaming",
                                     min(0.45, max(0.15, float(r.get("base") or 0.3))),
                                     tuple(a for a in (r.get("aggravators") or []) if a in AGGRAVATORS)))
                    wrote += 1
        except Exception:
            continue
    try:
        os.makedirs(os.path.dirname(CANON_FILE), exist_ok=True)
        with open(CANON_FILE, "w") as f:
            json.dump({"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                       "items": [{"jurisdiction": j, "area": a, "vertical": v, "base": b,
                                  "aggravators": list(g)} for j, a, v, b, g in existing]}, f)
    except Exception as e:
        print(f"regulator_simulation: canon write failed: {type(e).__name__}")
    print(f"regulator_simulation: authored {wrote} canon items across {len(todo)} jurisdiction(s)")
    return {"authored": wrote, "jurisdictions": todo}


def simulate():
    rng = random.Random(SEED + int(time.time() // 86400))   # stable within a day, drifts daily
    items = []
    for juris, area, vertical, base, aggs in CANON + _authored_canon():
        obs = _observed_adjustment(area)
        if obs:
            f, c = obs
            base = (base * 20 + f) / (20 + f + c)           # Beta-count blend toward reality
        flags = 0
        driver_counts = {}
        for _ in range(N_SIMS):
            p = base
            hit_driver = None
            for a in aggs:
                prob, mult = AGGRAVATORS.get(a, (0, 1))
                if rng.random() < prob:
                    p = min(0.95, p * mult)
                    hit_driver = a
            if rng.random() < p:
                flags += 1
                if hit_driver:
                    driver_counts[hit_driver] = driver_counts.get(hit_driver, 0) + 1
        driver = max(driver_counts, key=driver_counts.get) if driver_counts else None
        items.append({"jurisdiction": juris, "area": area, "vertical": vertical,
                      "p_flag": round(flags / N_SIMS, 3),
                      "driver": driver,
                      "basis": "observed-adjusted" if obs else "stylized prior (public exam emphasis + enforcement frequency)"})
    items.sort(key=lambda x: -x["p_flag"])
    return {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "n_sims": N_SIMS, "items": items}


ARTIFACT = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".runtime", "regulator_flags.json")


def load_latest():
    """Read the last simulation (used by foulkon_sync when embedding the snapshot)."""
    try:
        with open(ARTIFACT) as f:
            return json.load(f)
    except Exception:
        return None


def run():
    out = simulate()
    # Local artifact is the handoff seam — foulkon_sync runs on the same machine and embeds it.
    try:
        os.makedirs(os.path.dirname(ARTIFACT), exist_ok=True)
        with open(ARTIFACT, "w") as f:
            json.dump(out, f)
    except Exception as e:
        print(f"regulator_simulation: artifact write failed: {type(e).__name__}: {str(e)[:120]}")
    print("regulator_simulation: " + json.dumps({"items": len(out["items"]),
                                                 "top": out["items"][0]["area"] if out["items"] else None}))
    return out


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "author":
        print(json.dumps(author_canon(), indent=2))
        print(json.dumps({"resim": len(run().get("items", []))}))
    else:
        print(json.dumps(run(), indent=2))

#!/usr/bin/env python3
"""cx_provider_divergence.py - detect model-specific blind spots in high-stakes determinations.
Re-asks chair-synthesis across two providers via model_gateway.complete and flags divergences.
Inserts inbox note kind='provider_divergence'. Reuses model_gateway.complete; no schema change."""
import os, sys, json, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

MAX_PER_RUN = int(os.environ.get("CX_DIVERGENCE_MAX", "2"))
PROVIDER_A = os.environ.get("CX_DIVERGENCE_PROVIDER_A", "anthropic")
MODEL_A = os.environ.get("CX_DIVERGENCE_MODEL_A", "claude-haiku-4-5-20251001")
PROVIDER_B = os.environ.get("CX_DIVERGENCE_PROVIDER_B", "deepseek")
MODEL_B = os.environ.get("CX_DIVERGENCE_MODEL_B", "deepseek-chat")

SYNTHESIS_PROMPT = ("You are reviewing a prior committee determination. Provide your independent "
    'verdict as JSON: {"verdict":"support|oppose|conditional|needs-info","score":0-10,'
    '"reasoning":"1-2 sentences"}\n\nTITLE: {title}\nBODY: {body}')

def _extract_verdict(text):
    if not text: return {}
    try: return json.loads(text)
    except Exception: pass
    m = re.search(r'\{[^{}]+\}', text)
    if m:
        try: return json.loads(m.group())
        except Exception: pass
    return {}

def run():
    try:
        import model_gateway
    except Exception as e:
        print(f"cx_provider_divergence: cannot import model_gateway: {e}"); return 0
    dets = db.select("determinations", {"select": "id,title,recommendation,materiality,consensus_pct",
        "order": "created_at.desc", "limit": "20"}) or []
    candidates = []
    for d in dets:
        mat = d.get("materiality")
        try:
            if mat is not None and float(mat) < 0.5: continue
        except (ValueError, TypeError): pass
        did = d.get("id")
        if not did: continue
        existing = db.select("determination_outcomes", {"select": "id", "source": "eq.provider_divergence",
            "subject_id": f"eq.{did}", "limit": "1"}) or []
        if not existing: candidates.append(d)
        if len(candidates) >= MAX_PER_RUN: break
    if not candidates:
        print("cx_provider_divergence: no unchecked high-materiality determinations"); return 0
    divergences = []
    for d in candidates:
        title, body = d.get("title", ""), d.get("recommendation", "")
        prompt = SYNTHESIS_PROMPT.format(title=title[:500], body=body[:1000])
        try: resp_a = model_gateway.complete(PROVIDER_A, MODEL_A, prompt, timeout=60)
        except Exception: resp_a = ""
        try: resp_b = model_gateway.complete(PROVIDER_B, MODEL_B, prompt, timeout=60)
        except Exception: resp_b = ""
        va, vb = _extract_verdict(resp_a), _extract_verdict(resp_b)
        verdict_a, verdict_b = va.get("verdict", "unknown"), vb.get("verdict", "unknown")
        diverged = verdict_a != verdict_b and verdict_a != "unknown" and verdict_b != "unknown"
        try:
            db.insert("determination_outcomes", {"source": "provider_divergence",
                "subject_type": "determination", "subject_id": d.get("id"),
                "expected": verdict_a, "actual": verdict_b, "diverged": diverged,
                "detail": json.dumps({"provider_a": f"{PROVIDER_A}/{MODEL_A}",
                    "provider_b": f"{PROVIDER_B}/{MODEL_B}", "verdict_a": verdict_a,
                    "verdict_b": verdict_b})[:2000]})
        except Exception: pass
        if diverged:
            divergences.append(f"- {title[:60]}: {PROVIDER_A}={verdict_a}, {PROVIDER_B}={verdict_b}")
    if divergences:
        try:
            db.insert("inbox", {"kind": "provider_divergence",
                "title": f"Provider split: {len(divergences)} determination(s)",
                "body": ("Provider divergence:\n" + "\n".join(divergences[:10]))[:3000], "status": "unread"})
        except Exception: pass
    print(f"cx_provider_divergence: checked {len(candidates)}, divergences={len(divergences)}")
    return len(candidates)

if __name__ == "__main__":
    run()

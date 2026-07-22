#!/usr/bin/env python3
"""
capability_radar.py - cross-app arbitrage. Continuously matches mature capabilities that
exist in one app against gaps/opportunities in OTHER portfolio apps, RICE-ranks by revenue
potential, and files proposal cards ("App X's capability Y -> App Z could ship product W").
Respects preference suppression so only likely-valuable ideas surface. Schedule weekly.
"""
import os, sys, json, subprocess, re, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db, preference, claude_cli
import resolution_intelligence

try:
    import knowledge_embed as _ke
    _EMBED_OK = bool(os.environ.get("EMBED_PROVIDER"))
except ImportError:
    _ke = None
    _EMBED_OK = False


def _cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb + 1e-9)

MODEL = os.environ.get("RADAR_MODEL", "claude-sonnet-4-6")


def _mature_caps():
    caps = db.select("capabilities", {"select": "name,slug,domain,summary,status",
                                      "status": "in.(trusted,productizable)"}) or []
    if not any(c.get("slug") == resolution_intelligence.CAPABILITY["slug"] for c in caps):
        caps.append(dict(resolution_intelligence.CAPABILITY))
    return caps


def _projects():
    return db.select("projects", {"select": "name,repo_path"}) or []


PROMPT = """Given these reusable CAPABILITIES and these PORTFOLIO APPS, propose the best
cross-app matches: an app that could ship a new product/feature by instantiating a capability
it doesn't already have. Output one JSON object per line:
{"capability":"slug","target_app":"name","product":"what to ship","why":"demand",
 "reach":1-10,"impact":1-10,"confidence":0.0-1.0,"effort_days":number}
CAPABILITIES: {caps}
APPS: {apps}"""


def rice(o):
    try:
        return round(o["reach"] * o["impact"] * o["confidence"] / max(0.5, o["effort_days"]), 1)
    except Exception:
        return 0.0


def _embed_match(caps, apps):
    """Embedding-based: for each app gap, find best-matching capability by cosine similarity."""
    if not _EMBED_OK or not _ke:
        return []
    ideas = []
    for app in apps:
        app_vec = _ke.embed(f"app: {app['name']}\ngaps: new product opportunities")
        if not app_vec:
            continue
        best, best_score = None, 0.0
        for cap in caps:
            cv = _ke.embed(f"{cap['slug']}\n{cap.get('summary','')}\n{cap.get('domain','')}")
            if not cv:
                continue
            score = _cosine(app_vec, cv)
            if score > best_score:
                best, best_score = cap, score
        if best and best_score > 0.3:
            ideas.append({
                "capability": best["slug"],
                "target_app": app["name"],
                "product": f"{best['name']} for {app['name']}",
                "why": f"semantic match (cosine={best_score:.2f}) between app profile and capability domain",
                "reach": 5, "impact": 7, "confidence": round(best_score, 2),
                "effort_days": 10,
            })
    return ideas


def run():
    caps, apps = _mature_caps(), _projects()
    if not caps:
        print("radar: no trusted/productizable capabilities yet"); return 0

    # primary path: embedding-based semantic matching (no LLM call needed)
    ideas = _embed_match(caps, apps)

    # fallback: LLM-based matching when embeddings unavailable
    if not ideas:
        prompt = PROMPT.replace("{caps}", json.dumps(caps)).replace("{apps}", json.dumps([a["name"] for a in apps]))
        try:
            r = claude_cli.run(prompt, MODEL, timeout=200)
            out = r["text"]
        except Exception as e:
            print("radar failed:", e); return 0
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    ideas.append(json.loads(line))
                except Exception:
                    pass

    made = 0
    for o in sorted(ideas, key=rice, reverse=True)[:5]:
        title = f"[RICE {rice(o)}] {o.get('target_app')}: ship '{o.get('product')}' via {o.get('capability')}"
        if preference.should_suppress(title, o.get("why", ""), "proposal"):
            continue
        db.insert("approvals", {"project": o.get("target_app"), "kind": "proposal", "title": title,
                                "why": o.get("why"), "value": f"reuse capability {o.get('capability')}",
                                "risk": "validate fit + instantiate via capability.instantiate()",
                                "detail": json.dumps(o)})
        made += 1
    print(f"capability radar: filed {made} cross-app product proposals (embed={'yes' if _EMBED_OK else 'no/LLM fallback'})")
    return made


if __name__ == "__main__":
    run()

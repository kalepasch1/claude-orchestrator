#!/usr/bin/env python3
"""
cx_adversarial_sufficiency.py - Adversarial sufficiency testing for determinations.

For recent high-materiality determinations, runs a short red-team that tries to move
the verdict. Records how many attempts the determination survived (inbox kind='adv_sufficiency'
+ a determination_outcomes row source='adversarial'). Surfaces determinations that look
confident but are fragile, so robustness — not just consensus — informs autonomy.

Reuses committees._premortem-style prompting + model_gateway; no schema change;
does not edit committees.py.
"""
import os, sys, re, json, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

# Max determinations to test per run (cost-safe)
MAX_PER_RUN = int(os.environ.get("ORCH_ADV_SUFFICIENCY_LIMIT", "5") or 5)
# Number of red-team attack attempts per determination
ATTACK_ROUNDS = int(os.environ.get("ORCH_ADV_ATTACK_ROUNDS", "3") or 3)
# Minimum materiality to qualify for adversarial testing
MIN_MATERIALITY = float(os.environ.get("ORCH_ADV_MIN_MATERIALITY", "0.6") or 0.6)
# How far back to look (days)
LOOKBACK_DAYS = int(os.environ.get("ORCH_ADV_LOOKBACK_DAYS", "14") or 14)


def _complete(prompt, need=5):
    """Complete a prompt via model_gateway (same pattern as committees._complete)."""
    try:
        import model_policy, model_gateway
        prov, model, _ = model_policy.choose("review", agentic=False, need=need)
        r = model_gateway.complete(prov, model, prompt)
        return r.get("text") or ""
    except Exception:
        return ""


def _json_parse(text):
    """Extract a JSON object from text."""
    m = re.search(r"\{.*\}", text, re.S)
    try:
        return json.loads(m.group(0)) if m else {}
    except Exception:
        return {}


def _recent_high_materiality():
    """Fetch recent high-materiality determinations not yet adversarially tested."""
    cutoff = (datetime.datetime.now(datetime.timezone.utc)
              - datetime.timedelta(days=LOOKBACK_DAYS)).isoformat()
    try:
        dets = db.select("determinations", {
            "select": "id,title,position,consensus_pct,materiality,confidence,factions,dissent",
            "created_at": f"gte.{cutoff}",
            "materiality": f"gte.{MIN_MATERIALITY}",
            "order": "materiality.desc",
            "limit": str(MAX_PER_RUN * 3),  # fetch extra to filter already-tested
        }) or []
    except Exception:
        return []

    # Filter out already-tested determinations
    tested = set()
    try:
        outcomes = db.select("determination_outcomes", {
            "select": "determination_id",
            "source": "eq.adversarial",
            "limit": "500",
        }) or []
        tested = {o["determination_id"] for o in outcomes if o.get("determination_id")}
    except Exception:
        pass

    return [d for d in dets if d.get("id") not in tested][:MAX_PER_RUN]


def _attack(det, round_num):
    """Run one adversarial attack round against a determination.
    Returns dict with survived (bool), attack description, and strength."""
    title = (det.get("title") or "")[:200]
    position = (det.get("position") or "")[:200]
    factions = det.get("factions") or []
    dissent = det.get("dissent") or []

    faction_str = ""
    if isinstance(factions, str):
        try:
            factions = json.loads(factions)
        except Exception:
            factions = []
    if isinstance(factions, list):
        faction_str = "; ".join(
            f"{f.get('stance','?')}: {f.get('share',0)*100:.0f}% — {f.get('argument','')[:80]}"
            for f in factions[:5]
        )

    dissent_str = ""
    if isinstance(dissent, str):
        try:
            dissent = json.loads(dissent)
        except Exception:
            dissent_str = dissent[:200]
    if isinstance(dissent, list):
        dissent_str = "; ".join(str(d)[:100] for d in dissent[:3])

    prompt = (
        f"You are an adversarial red team (round {round_num}/{ATTACK_ROUNDS}). "
        f"A committee determined: '{position}' on '{title}'. "
        f"Factions: [{faction_str}]. Dissent: [{dissent_str}]. "
        f"Construct the STRONGEST counter-argument that would flip this verdict. "
        f"Then assess: would the original panel ACTUALLY change its mind? "
        f"Return ONE JSON: "
        f"{{\"attack\":\"2-sentence counter-argument\","
        f"\"strength\":0.0-1.0,"
        f"\"would_flip\":true/false,"
        f"\"reason\":\"why it would or wouldn't flip\"}}"
    )

    result = _json_parse(_complete(prompt, need=7))
    if not result:
        return {"survived": True, "attack": "red-team failed to generate", "strength": 0.0}

    return {
        "survived": not result.get("would_flip", False),
        "attack": (result.get("attack") or "")[:200],
        "strength": float(result.get("strength", 0) or 0),
        "reason": (result.get("reason") or "")[:200],
    }


def _test_determination(det):
    """Run ATTACK_ROUNDS adversarial attacks and return results."""
    rounds = []
    survived_count = 0

    for i in range(1, ATTACK_ROUNDS + 1):
        result = _attack(det, i)
        rounds.append(result)
        if result.get("survived", True):
            survived_count += 1

    return {
        "determination_id": det.get("id"),
        "title": (det.get("title") or "")[:200],
        "survived": survived_count,
        "total": ATTACK_ROUNDS,
        "fragile": survived_count < ATTACK_ROUNDS,
        "max_attack_strength": max((r.get("strength", 0) for r in rounds), default=0),
        "rounds": rounds,
    }


def run():
    """Main entry point: test recent high-materiality determinations for adversarial robustness."""
    dets = _recent_high_materiality()
    if not dets:
        return {"status": "ok", "tested": 0, "note": "no untested high-materiality determinations"}

    results = []
    for det in dets:
        result = _test_determination(det)
        results.append(result)

        # Record outcome
        try:
            db.insert("determination_outcomes", {
                "determination_id": det.get("id"),
                "source": "adversarial",
                "metric": "adv_sufficiency",
                "outcome": float(result["survived"]) / result["total"] if result["total"] else 1.0,
                "meta": json.dumps({
                    "survived": result["survived"],
                    "total": result["total"],
                    "max_strength": result["max_attack_strength"],
                    "fragile": result["fragile"],
                }),
            })
        except Exception:
            pass

        # Alert on fragile determinations
        if result["fragile"]:
            strongest = max(result["rounds"], key=lambda r: r.get("strength", 0))
            body = (
                f"Determination '{result['title']}' survived only {result['survived']}/{result['total']} "
                f"adversarial attacks. Strongest attack (strength {result['max_attack_strength']:.2f}): "
                f"{strongest.get('attack', '')} — {strongest.get('reason', '')}"
            )
            try:
                db.insert("inbox", {
                    "kind": "adv_sufficiency",
                    "title": f"Fragile determination: '{result['title'][:80]}' ({result['survived']}/{result['total']} survived)",
                    "body": body[:3000],
                    "meta": json.dumps({
                        "determination_id": det.get("id"),
                        "survived": result["survived"],
                        "total": result["total"],
                    }),
                })
            except Exception:
                pass

    fragile_count = sum(1 for r in results if r.get("fragile"))
    return {
        "status": "ok",
        "tested": len(results),
        "fragile": fragile_count,
        "robust": len(results) - fragile_count,
        "details": [{"title": r["title"], "survived": r["survived"], "total": r["total"],
                      "fragile": r["fragile"]} for r in results],
    }


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, default=str))

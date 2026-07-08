#!/usr/bin/env python3
"""Runner-facing mesh optimizer.

Centralizes the 20X-500X primitives that must happen around each expensive
agentic edit/run loop:
- prompt bankruptcy
- reusable intent graph / patch transplant hints
- pre-settlement simulation
- multi-role debate compression
- model/domain settlement and slashing
- Common Brain deployment outcome writeback
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _truthy(name, default=True):
    raw = os.environ.get(name)
    if raw is None:
        return bool(default)
    return str(raw).lower() in ("1", "true", "yes", "on")


def _note(*parts):
    return " | ".join(str(p) for p in parts if p)


def prepare_prompt(task, prompt, *, project="", repo="", base="", coder="", visible_model="",
                   diff_plan=None, assignment=None):
    """Return a prompt prepared for the expensive coder call."""
    notes = []
    out = prompt
    domain = "backend"

    try:
        import model_portfolios
        domain = model_portfolios.classify(task, task.get("_touched_files") or [])
    except Exception:
        domain = "backend"

    try:
        import merged_diff_library
        adapter = merged_diff_library.adapter_directive(task)
        if adapter and adapter not in out:
            out = adapter + "\n\n" + out
            notes.append("intent-graph-adapter")
    except Exception:
        pass

    try:
        import prompt_bankruptcy
        if prompt_bankruptcy.is_bankrupt(task):
            out = prompt_bankruptcy.restructure(task, out, project=project)
            notes.append("prompt-bankruptcy-restructure")
    except Exception:
        pass

    sim = None
    if _truthy("ORCH_PRESETTLEMENT_SIM", True):
        try:
            import presettlement_sim
            agent_id = visible_model or coder or ""
            sim = presettlement_sim.simulate(task, agent_id=agent_id, domain=domain, diff_plan=diff_plan)
            if sim.get("predicted_failure"):
                reasons = "; ".join(sim.get("reasons") or [])[:600]
                out = (
                    "PRE-SETTLEMENT SIMULATOR WARNING\n"
                    f"Predicted failure probability: {sim.get('failure_probability')} "
                    f"(confidence={sim.get('confidence')}).\n"
                    f"Recommended action: {sim.get('recommended_action')}.\n"
                    f"Reasons: {reasons}.\n\n"
                    "Respond by shrinking the task to the smallest mergeable slice, using prior templates first, "
                    "and stopping before irreversible/material changes.\n\n"
                    + out
                )
                notes.append(f"pre-settlement:{sim.get('recommended_action')}")
        except Exception:
            sim = None

    debate = None
    should_debate = (
        _truthy("ORCH_DEBATE_COMPRESS", True)
        and not task.get("_debate_compressed")
        and (task.get("material") or len(str(task.get("prompt") or "")) >= int(os.environ.get("ORCH_DEBATE_MIN_PROMPT_CHARS", "900"))
             or str(task.get("kind") or "").lower() in ("security", "legal", "hard", "build"))
    )
    if should_debate:
        try:
            import debate_compress
            debate = debate_compress.compressed_debate(task, assignment=assignment, project=project)
            if debate:
                out = debate_compress.inject_debate(out, debate)
                task["_debate_compressed"] = True
                notes.append("compressed-debate")
        except Exception:
            debate = None

    return {
        "prompt": out,
        "domain": domain,
        "notes": notes,
        "note": _note(*notes),
        "simulation": sim,
        "debate": debate,
    }


def settle(task, *, project="", slug="", kind="", model="", coder="", tests_passed=False,
           integrated=False, output="", cost=None, wall_s=0.0, deployed=False, rollback=False):
    """Write all post-outcome learning signals."""
    cost = cost or {}
    domain = task.get("_mesh_domain") or "backend"
    review_failures = int(task.get("_review_failures") or (0 if tests_passed else 1))
    cost_usd = float(cost.get("usd") or 0.0) if isinstance(cost, dict) else 0.0
    agent_id = f"{coder}:{model}" if coder and coder not in str(model) else str(model or coder or "")

    try:
        import prompt_bankruptcy
        prompt_bankruptcy.record_attempt(task, bool(tests_passed and integrated))
    except Exception:
        pass

    try:
        import model_portfolios
        model_portfolios.update(agent_id or "unknown", domain, bool(integrated), cost_usd=cost_usd, wall_s=wall_s)
    except Exception:
        pass

    try:
        import model_slashing
        model_slashing.record(agent_id or "unknown", "", merged=bool(integrated),
                              tests_passed=bool(tests_passed), review_failures=review_failures,
                              rollback=bool(rollback), cost_usd=cost_usd, domain=domain)
    except Exception:
        pass

    try:
        import common_brain
        common_brain.record_outcome(task, project=project, slug=slug, status=("merged" if integrated else "failed"),
                                    outcome=("integrated" if integrated else "not_integrated"),
                                    tokens_avoided=int(task.get("_tokens_avoided") or 0),
                                    minutes_avoided=float(task.get("_minutes_avoided") or 0.0),
                                    review_failures=review_failures,
                                    rollback=bool(rollback),
                                    metadata={
                                        "kind": kind,
                                        "model": model,
                                        "coder": coder,
                                        "domain": domain,
                                        "tests_passed": bool(tests_passed),
                                        "cost_usd": cost_usd,
                                        "deployed": bool(deployed),
                                    })
    except Exception:
        pass

    return {"domain": domain, "agent_id": agent_id, "review_failures": review_failures}

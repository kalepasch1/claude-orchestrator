#!/usr/bin/env python3
"""golden_path.py — the last two Part 4 clauses (Wave C, slice 4).

IMPROVEMENTS_MASTER_UNQUEUED_2026-07-31.md, Part 4, in full:

    "Transplant-proven-organs discipline (disposition ledger + merged-diff library at the
     raised 0.55 similarity; never grow tumors); contract-first generation (emit failing test
     + type signatures first, then fill — the verify gate IS the spec); PER-VERTICAL
     GOLDEN-PATH TEMPLATES DISTILLED FROM TOP-DECILE MERGED SHARDS; STRATEGY-AWARE GENERATION
     (approved strategy from the tribunal is context for every shard — code born
     compliant-by-design for the chosen structure, e.g. sweepstakes entry generates AMOE flows
     + state gates natively)."

Slice 2 shipped the first two clauses (`transplant_discipline.py`). These are the last two,
and they are the compounding half:

**Golden paths.** The merged-diff library answers "has something like this been done?".
It cannot answer "what does GOOD look like here?", because it ranks by similarity and
similarity is blind to outcome — a shard that merged after four repair attempts scores the same
as one that merged first-pass. `distil()` ranks by outcome instead and keeps only the top
decile, so the template a generator starts from is the best result the fleet has produced in
that vertical, not merely the nearest.

**Strategy-aware generation.** Once a tribunal has approved a structure, that approval is the
most load-bearing context a shard can have — and today it is not passed down at all. So a
sweepstakes shard writes an entry flow, review discovers there is no AMOE path and no state
gating, and the work is redone. `strategy_context()` makes the approved structure's
requirements part of the prompt, so the code is born with them: cheaper than adding them, and
far cheaper than discovering they are missing at the compliance gate.

Pure logic, dependency-free, fail-soft per CLAUDE.md.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

#: Keep only this fraction of shards as golden — the spec's "top decile".
TOP_DECILE = float(os.environ.get("ORCH_GOLDEN_PATH_QUANTILE", "0.10"))
#: Below this many observations a vertical has no golden path, only anecdotes.
MIN_SHARDS_PER_VERTICAL = int(os.environ.get("ORCH_GOLDEN_PATH_MIN_SHARDS", "5"))


def _num(value, default=0.0):
    try:
        if value is None:
            return default
        result = float(value)
        return default if result != result else result   # NaN -> default
    except (TypeError, ValueError):
        return default


# ── outcome scoring ─────────────────────────────────────────────────────────────────────────

def outcome_score(shard):
    """How good a merged shard actually turned out, 0..1. Never raises.

    Deliberately NOT similarity. The merged-diff library already ranks by similarity, and that
    is why it will happily hand a coder a diff that merged only after four repair attempts —
    the shape matched, the outcome was bad, and nothing in the ranking could tell the difference.

    Inputs (all optional): merged, attempts, review_cycles, reverted, test_pass,
    days_to_merge, post_merge_incidents.
    """
    try:
        shard = shard if isinstance(shard, dict) else {}
        if shard.get("merged") is not True:
            return 0.0
        # A revert is disqualifying, not a deduction: whatever it teaches, it is not the path.
        if shard.get("reverted") is True:
            return 0.0

        score = 1.0
        attempts = max(1, int(_num(shard.get("attempts"), 1)))
        score *= 1.0 / attempts                      # first-pass merges dominate
        score *= 0.85 ** max(0, int(_num(shard.get("review_cycles"), 0)))
        if shard.get("test_pass") is False:
            score *= 0.5
        incidents = max(0, int(_num(shard.get("post_merge_incidents"), 0)))
        score *= 0.6 ** incidents
        days = _num(shard.get("days_to_merge"), 0.0)
        if days > 0:
            score *= min(1.0, 3.0 / max(1.0, days))  # slow merges are worth less to copy
        return round(max(0.0, min(1.0, score)), 4)
    except Exception:
        return 0.0


def distil(shards, vertical=None, quantile=None, min_shards=None):
    """Golden-path templates for a vertical: the top-decile shards by OUTCOME.

    Returns {"vertical", "eligible", "golden": [...], "cutoff", "reason"}. `golden` is empty
    with a stated reason when the evidence is too thin — a "golden path" drawn from two shards
    is one team's habit, and enshrining it as a template is how a habit becomes a standard.

    Never raises.
    """
    quantile = TOP_DECILE if quantile is None else _num(quantile, TOP_DECILE)
    min_shards = MIN_SHARDS_PER_VERTICAL if min_shards is None else min_shards
    result = {"vertical": vertical, "eligible": 0, "golden": [], "cutoff": None, "reason": ""}
    try:
        pool = []
        for shard in shards or ():
            if not isinstance(shard, dict):
                continue
            if vertical is not None and shard.get("vertical") != vertical:
                continue
            score = outcome_score(shard)
            if score <= 0:
                continue                       # unmerged or reverted: never a template
            pool.append({**shard, "outcome_score": score})

        result["eligible"] = len(pool)
        if len(pool) < min_shards:
            result["reason"] = (
                f"{len(pool)} eligible shard(s) for {vertical or 'all'} — below the {min_shards} "
                f"needed before a template is evidence rather than one team's habit")
            return result

        pool.sort(key=lambda s: (-s["outcome_score"], str(s.get("slug", ""))))
        keep = max(1, int(round(len(pool) * quantile)))
        result["golden"] = pool[:keep]
        result["cutoff"] = pool[keep - 1]["outcome_score"]
        return result
    except Exception:
        result["reason"] = "distillation failed"
        return result


def golden_paths(shards, quantile=None, min_shards=None):
    """Distil every vertical present in `shards`. Returns {vertical: result}. Never raises."""
    try:
        verticals = sorted({s.get("vertical") for s in (shards or ())
                            if isinstance(s, dict) and s.get("vertical")})
        return {v: distil(shards, vertical=v, quantile=quantile, min_shards=min_shards)
                for v in verticals}
    except Exception:
        return {}


def template_for(shards, vertical, **kwargs):
    """The single best template for a vertical, or None. Never raises."""
    try:
        golden = distil(shards, vertical=vertical, **kwargs).get("golden") or []
        return golden[0] if golden else None
    except Exception:
        return None


# ── strategy-aware generation ───────────────────────────────────────────────────────────────

#: Approved structure -> requirements code must be BORN with, not have added later.
#: The sweepstakes entry is the spec's own worked example.
STRUCTURE_REQUIREMENTS = {
    "sweepstakes": [
        "an alternate method of entry (AMOE) with equal dignity of entry — not a footnote link",
        "per-state eligibility gating, including the states that prohibit the structure outright",
        "no purchase or consideration on any entry path",
        "official rules surfaced before entry, with sponsor, dates, odds and prize ARV",
    ],
    "contest": [
        "judging criteria stated before entry and applied by named judges",
        "skill as the determinant of the outcome — chance may not decide it",
        "per-state eligibility gating",
    ],
    "loyalty-program": [
        "points liability recorded as a liability, not as revenue",
        "expiry and forfeiture terms disclosed at enrolment",
        "a stated conversion rate that cannot be changed retroactively",
    ],
    "money-transmission": [
        "no custody of customer funds on any path",
        "agent-of-payee structure documented at the point it is relied on",
        "per-state licensing gate before the flow is reachable",
    ],
    "lending": [
        "APR disclosure computed and shown before commitment",
        "state rate caps enforced as a gate, not as a warning",
        "adverse-action notice on every decline path",
    ],
}


def structure_requirements(structure):
    """Requirements a given approved structure imposes on the code. [] when unknown."""
    try:
        return list(STRUCTURE_REQUIREMENTS.get(str(structure or "").strip().lower(), []))
    except Exception:
        return []


def strategy_context(strategy, template=None):
    """Turn an approved tribunal strategy into generation context. Never raises.

    Returns {"ok", "structure", "requirements", "template_slug", "prompt", "reason"}.

    `ok` is False when there is no approved structure — and that is the point of the gate.
    Generating without it produces code that has to be retrofitted with AMOE flows and state
    gates after review, which costs more than the generation did.
    """
    result = {"ok": False, "structure": None, "requirements": [], "template_slug": None,
              "prompt": "", "reason": ""}
    try:
        strategy = strategy if isinstance(strategy, dict) else {}
        structure = str(strategy.get("structure") or "").strip().lower()
        approved = strategy.get("approved") is True

        if not structure:
            result["reason"] = ("no approved structure on the strategy — generating now means "
                                "retrofitting the structural requirements after review")
            return result
        if not approved:
            result["reason"] = (f"structure '{structure}' is proposed but NOT approved by the "
                                f"tribunal — generating against an unapproved structure risks "
                                f"building the wrong thing correctly")
            return result

        result["structure"] = structure
        result["requirements"] = structure_requirements(structure)
        if template and isinstance(template, dict):
            result["template_slug"] = template.get("slug")

        lines = [f"APPROVED STRUCTURE: {structure}"]
        if strategy.get("jurisdictions"):
            lines.append("JURISDICTIONS: " + ", ".join(str(j) for j in strategy["jurisdictions"]))
        if result["requirements"]:
            lines.append("")
            lines.append("The code must be BORN with these — they are not review findings to "
                         "fix afterwards:")
            lines += [f"  - {r}" for r in result["requirements"]]
        else:
            lines.append("")
            lines.append(f"No structural requirements are recorded for '{structure}'. Treat "
                         f"that as a gap in this module, not as permission to skip them.")
        if result["template_slug"]:
            lines.append("")
            lines.append(f"GOLDEN PATH: start from {result['template_slug']} — the best-outcome "
                         f"merged shard in this vertical, not merely the most similar one.")
        result["prompt"] = "\n".join(lines)
        result["ok"] = True
        return result
    except Exception:
        result["reason"] = "strategy context could not be built"
        return result


def missing_requirements(structure, implemented):
    """Requirements a shard has not covered. The compliance gate, computable up front."""
    try:
        required = structure_requirements(structure)
        covered = {str(item).strip().lower() for item in (implemented or ())}
        out = []
        for requirement in required:
            head = requirement.split("—")[0].strip().lower()
            if not any(head[:24] in c or c in head for c in covered if c):
                out.append(requirement)
        return out
    except Exception:
        return []


def render(distilled=None, context=None):
    """Operator summary. Never raises."""
    try:
        lines = []
        if distilled is not None:
            lines.append(f"GOLDEN PATH — {distilled.get('vertical') or 'all'}")
            lines.append(f"  {distilled.get('eligible', 0)} eligible · "
                         f"{len(distilled.get('golden') or [])} golden")
            if distilled.get("reason"):
                lines.append(f"  {distilled['reason']}")
            for shard in (distilled.get("golden") or [])[:5]:
                lines.append(f"    {shard.get('outcome_score'):.2f}  {shard.get('slug')}")
        if context is not None:
            lines.append("")
            lines.append("STRATEGY CONTEXT: " + ("ready" if context.get("ok") else "BLOCKED"))
            if context.get("reason"):
                lines.append(f"  {context['reason']}")
            for requirement in context.get("requirements", []):
                lines.append(f"  - {requirement}")
        return "\n".join(lines) or "nothing to report"
    except Exception:
        return "golden path report unavailable"

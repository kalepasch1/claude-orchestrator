#!/usr/bin/env python3
"""transplant_discipline.py — the Part 4 codegen disciplines, as checks (Wave C, slice 2).

IMPROVEMENTS_MASTER_UNQUEUED_2026-07-31.md, Part 4:

    "Transplant-proven-organs discipline (disposition ledger + merged-diff library at the
     raised 0.55 similarity; never grow tumors); contract-first generation (emit failing test
     + type signatures first, then fill — the verify gate IS the spec)"

Three ideas, each of which was prose. Prose does not fail a build, so each is a function here:

1. **The raised similarity floor.** `patch_transplant.hint()` gates on
   `ORCH_PATCH_TRANSPLANT_MIN_SIM`, default **0.18**, and `find_transplant_source()` on a
   separate hardcoded **0.25** — two thresholds, neither of them the 0.55 the spec calls for,
   drifting independently. At 0.18 the "proven patch" handed to a coder is barely related to
   the task: this is where prompts like "adapt the proven patch beethoven/deployfix-… 
   similarity=0.309" come from, and a coder that dutifully adapts an unrelated diff produces
   exactly the unmergeable output the transplant was supposed to prevent. One constant, here.

2. **Never grow tumors.** A transplant is an ORGAN when it replaces or extends behaviour, and a
   TUMOR when it appends a near-copy of code the file already contains. Additive-only diffs
   that re-declare an existing symbol are the signature: nothing is deleted, tests still pass,
   and the file now has two implementations of the same idea. `tumor_check` names that shape.

3. **The verify gate IS the spec.** Generation must not start until a contract exists: a
   failing test plus type signatures. `contract_first_gate` refuses a spec that has neither —
   "write the code and we'll test it after" is how a shard gets judged against whatever it
   happened to do.

Pure, dependency-free, fail-soft per CLAUDE.md. `patch_transplant` imports the floor from here
so there is one definition rather than three.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# The Part 4 floor. Env-overridable for an experiment; the DEFAULT is the spec's value, and
# every transplant path reads it from here.
MIN_TRANSPLANT_SIMILARITY = float(os.environ.get("ORCH_TRANSPLANT_MIN_SIM", "0.55"))

# Below this a "hint" is noise dressed as evidence; naming it separately makes the distinction
# between "not similar enough to transplant" and "not similar enough to even mention" explicit.
MENTION_SIMILARITY = float(os.environ.get("ORCH_TRANSPLANT_MENTION_SIM", "0.55"))


def _num(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def transplant_admissible(similarity, floor=None):
    """True when a prior diff is similar enough to be worth adapting. Never raises."""
    floor = MIN_TRANSPLANT_SIMILARITY if floor is None else _num(floor, MIN_TRANSPLANT_SIMILARITY)
    return _num(similarity, -1.0) >= floor


def rejection_reason(similarity, floor=None):
    """Why a transplant candidate was rejected, or "" when it is admissible."""
    floor = MIN_TRANSPLANT_SIMILARITY if floor is None else _num(floor, MIN_TRANSPLANT_SIMILARITY)
    value = _num(similarity, -1.0)
    if value >= floor:
        return ""
    return (f"similarity {value:.3f} is below the transplant floor of {floor:.2f} — adapting a "
            f"weakly-related diff produces unmergeable output and costs a lane doing it")


# ── tumor detection ─────────────────────────────────────────────────────────────────────────

_DEF_LINE = re.compile(r"^[+\-]\s*(?:async\s+)?(?:def|class|function|export function|const)\s+"
                       r"(?P<symbol>[A-Za-z_][A-Za-z0-9_]*)")
_ADDED = re.compile(r"^\+(?!\+\+)")
_REMOVED = re.compile(r"^-(?!--)")


def _symbols(diff, sign):
    """Symbols declared on added (+) or removed (-) lines of a unified diff."""
    out = []
    for line in (diff or "").splitlines():
        if not line.startswith(sign):
            continue
        match = _DEF_LINE.match(line)
        if match:
            out.append(match.group("symbol"))
    return out


def tumor_check(diff, existing_symbols=()):
    """Decide whether a diff grows an organ or a tumor.

    Returns {"tumor": bool, "reason": str, "duplicated": [symbol, ...], "added", "removed"}.

    A TUMOR is an additive-only diff that declares a symbol the target already defines. Nothing
    is replaced, so both implementations survive; the build stays green and the file now holds
    two answers to the same question. That is the failure mode "never grow tumors" names, and it
    is invisible to every test that only checks the new path.

    Fail-soft: an unparseable diff is NOT called a tumor. A false positive here blocks real
    work, which is worse than missing one.
    """
    result = {"tumor": False, "reason": "", "duplicated": [], "added": 0, "removed": 0}
    try:
        text = diff or ""
        lines = text.splitlines()
        result["added"] = sum(1 for l in lines if _ADDED.match(l))
        result["removed"] = sum(1 for l in lines if _REMOVED.match(l))

        added_symbols = _symbols(text, "+")
        removed_symbols = set(_symbols(text, "-"))
        existing = {str(s) for s in (existing_symbols or ())}

        # A symbol that is added while an identical symbol is removed is a REPLACEMENT — the
        # healthy case, and the one a naive "is it already defined?" check gets wrong.
        duplicated = [s for s in added_symbols
                      if s in existing and s not in removed_symbols]

        # Duplicated within the diff itself: two new definitions of the same name.
        seen = set()
        for symbol in added_symbols:
            if symbol in seen and symbol not in duplicated:
                duplicated.append(symbol)
            seen.add(symbol)

        if duplicated and result["removed"] == 0:
            result["tumor"] = True
            result["duplicated"] = sorted(set(duplicated))
            result["reason"] = (
                "additive-only diff re-declares " + ", ".join(sorted(set(duplicated)))
                + " — the original stays, so the file now holds two implementations of the "
                  "same idea and every test still passes")
        elif duplicated:
            result["duplicated"] = sorted(set(duplicated))
            result["reason"] = ("re-declares " + ", ".join(sorted(set(duplicated)))
                                + " but also removes code — review whether this replaces or "
                                  "duplicates")
        return result
    except Exception:
        return result


# ── contract-first gate ─────────────────────────────────────────────────────────────────────

def contract_first_gate(spec):
    """Refuse generation until a contract exists. Returns {"ok", "missing", "reason"}.

    A spec is admissible when it carries BOTH:
      * `failing_test`   — the executable statement of what "done" means, which must fail now;
      * `signatures`     — the type signatures the implementation must satisfy.

    "The verify gate IS the spec" only works if the gate exists before the code does. Without
    it a shard is judged against whatever it happened to do, which is how a task passes review
    and still does not do the thing.

    Never raises: a malformed spec is reported as not-ok, since proceeding is the worse error.
    """
    result = {"ok": False, "missing": [], "reason": ""}
    try:
        spec = spec if isinstance(spec, dict) else {}
        failing_test = str(spec.get("failing_test") or "").strip()
        signatures = spec.get("signatures")
        signatures = list(signatures) if isinstance(signatures, (list, tuple)) else []

        if not failing_test:
            result["missing"].append("failing_test")
        if not signatures:
            result["missing"].append("signatures")

        # A test that is asserted to already pass is not a contract, it is a description.
        if failing_test and spec.get("test_currently_passes") is True:
            result["missing"].append("failing_test")
            result["reason"] = ("the contract test already passes, so it constrains nothing — "
                                "a contract must fail before the implementation exists")
            result["missing"] = sorted(set(result["missing"]))
            return result

        if result["missing"]:
            result["reason"] = ("contract-first requires " + " and ".join(result["missing"])
                                + " before generation starts; the verify gate IS the spec")
            return result

        result["ok"] = True
        return result
    except Exception:
        result["missing"] = ["failing_test", "signatures"]
        result["reason"] = "contract could not be evaluated"
        return result


def render(diff_result=None, gate_result=None):
    """Operator-readable summary. Never raises."""
    try:
        lines = []
        if gate_result is not None:
            lines.append("contract-first gate: " + ("PASS" if gate_result.get("ok") else "BLOCKED"))
            if gate_result.get("reason"):
                lines.append("  " + gate_result["reason"])
        if diff_result is not None:
            lines.append("transplant shape: " + ("TUMOR" if diff_result.get("tumor") else "organ"))
            if diff_result.get("reason"):
                lines.append("  " + diff_result["reason"])
            lines.append(f"  +{diff_result.get('added', 0)} / -{diff_result.get('removed', 0)}")
        return "\n".join(lines) or "nothing to report"
    except Exception:
        return "transplant discipline report unavailable"

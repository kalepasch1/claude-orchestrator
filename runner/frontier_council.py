#!/usr/bin/env python3
"""frontier_council.py — frontier planning council for broad/material objectives.

For a small, mechanical task the existing `plan_stage` single-planner step is
the right amount of ceremony. For a broad, high-value, or materially risky
objective it is not: one model, one pass, no adversary, and no record of why
the approach was chosen. This module is the heavier path.

Shape of a council run (`convene`):

  0. GATE          `should_convene()` — broad/high-value/material only. Small or
                   mechanical work returns a deterministic fallback contract so
                   the caller never has to branch on "did the council run".
  1. DOSSIER       `build_dossier()` pins ONE codebase dossier at an exact base
                   SHA: symbol graph, relevant files, history, invariants,
                   recorded failures, release evidence. Every seat reads the
                   same pinned evidence, so disagreement is about judgment and
                   not about who happened to look at a newer tree.
  2. SEATING       `probe_capabilities()` asks each provider whether it is
                   ACTUALLY reachable. Catalog strings are a claim, not a fact —
                   a model listed in model_catalog but unreachable would
                   otherwise produce a silently empty seat. Seats are then
                   selected one-per-vendor-family for genuine independence.
  3. PROPOSALS     each seat drafts independently against the pinned dossier.
  4. CRITIQUES     proposals are ANONYMIZED before cross-review, so a seat
                   critiques the argument rather than the brand.
  5. ADVERSARY     a dedicated risk seat argues against every proposal.
  6. JUDGE         a separate synthesizing seat — never one of the proposers —
                   selects and merges into one contract.
  7. CONTRACT      `sign_contract()` emits one signed implementation contract:
                   non-goals, file ownership, DAG, migrations/rollback, tests,
                   journey probes, budgets, escalation rules. The signature is
                   over the canonical JSON, so a contract that is edited after
                   signing fails verification instead of quietly executing.
  8. PERSIST       full evidence (every proposal, critique, adversary note and
                   the judge's rationale) is written alongside the contract.

Design constraints:
  - `ask` is injected. All model access goes through one caller-supplied
    callable, so this module is deterministic and offline-testable, and the
    production wiring (model_gateway) stays in one place.
  - Fail-soft everywhere. Any seat that errors is recorded as a failed seat and
    the council proceeds; a council that cannot seat a quorum degrades to the
    deterministic fallback rather than raising into the runner.
  - Pure-ish: no import-time side effects, no network, no DB writes unless the
    caller passes a persister.
"""
import hashlib
import hmac
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── Tunables (ORCH_-prefixed so they are fleet-pushable via fleet_control) ──
MIN_PROMPT_LEN = int(os.environ.get("ORCH_COUNCIL_MIN_LEN", "400"))
MIN_SEATS = int(os.environ.get("ORCH_COUNCIL_MIN_SEATS", "2"))
MAX_SEATS = int(os.environ.get("ORCH_COUNCIL_MAX_SEATS", "4"))
PROBE_TIMEOUT = int(os.environ.get("ORCH_COUNCIL_PROBE_TIMEOUT", "20"))
SEAT_TIMEOUT = int(os.environ.get("ORCH_COUNCIL_SEAT_TIMEOUT", "120"))
GIT_TIMEOUT = int(os.environ.get("ORCH_GIT_TIMEOUT", "60"))
DEFAULT_BUDGET_USD = float(os.environ.get("ORCH_COUNCIL_BUDGET_USD", "2.50"))
_SECRET = (os.environ.get("ORCH_COUNCIL_SECRET", "")
           or os.environ.get("BROKER_TOKEN_SECRET", "")
           or "orchestrator-local").encode()

# Objectives that justify the council's cost. Matched case-insensitively
# against the prompt; any hit plus sufficient length convenes.
MATERIAL_MARKERS = (
    "migration", "rollback", "schema", "architecture", "refactor",
    "security", "credential", "auth", "billing", "payment", "revenue",
    "production", "release", "fleet-wide", "breaking change", "data loss",
    "contract", "invariant", "consensus", "council",
)
# Work that is mechanical by construction — never worth council overhead.
MECHANICAL_MARKERS = (
    "typo", "docstring", "rename", "whitespace", "formatting", "lint fix",
    "bump version", "add comment", "canary",
)


def _git(args, repo, timeout=None):
    """Run git, fail-soft. Returns (stdout, ok)."""
    try:
        r = subprocess.run(["git"] + list(args), cwd=repo, capture_output=True,
                           text=True, timeout=timeout or GIT_TIMEOUT)
        return r.stdout.strip(), r.returncode == 0
    except Exception:
        return "", False


def _canonical(obj):
    """Stable JSON for hashing/signing: sorted keys, no incidental whitespace."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def digest(obj):
    """Content hash of any JSON-able object."""
    return hashlib.sha256(_canonical(obj).encode()).hexdigest()


# ────────────────────────────────────────────────────────────── 0. gate

def should_convene(task, prompt):
    """True when this objective is broad/high-value/material enough for a council.

    Deliberately conservative: council overhead is real, so a task must be BOTH
    long enough to have structure AND carry a material marker (or be flagged
    high-value by the caller). Anything explicitly mechanical is refused even
    if it is long.
    """
    task = task or {}
    text = (prompt or "").lower()

    if str(os.environ.get("ORCH_FRONTIER_COUNCIL", "true")).lower() != "true":
        return False
    kind = str(task.get("kind") or "").lower()
    if kind in ("canary", "speculative", "docs"):
        return False
    if any(m in text for m in MECHANICAL_MARKERS):
        return False
    if len(text) < MIN_PROMPT_LEN:
        return False
    if task.get("high_value") or str(task.get("class") or "").lower() in (
            "security", "legal", "architecture"):
        return True
    return any(m in text for m in MATERIAL_MARKERS)


# ────────────────────────────────────────────────────── 1. pinned dossier

def resolve_base_sha(repo_path, ref="HEAD"):
    """Resolve *ref* to a full SHA. Returns "" when it cannot be resolved.

    The council pins to an exact SHA rather than a branch name: a branch moves
    under a long council run, and evidence that describes a tree nobody can
    reproduce is not evidence.
    """
    sha, ok = _git(["rev-parse", ref], repo_path)
    return sha if ok and sha else ""


def build_dossier(repo_path, base_sha=None, paths=None, history_depth=20,
                  invariants=None, failures=None, release_evidence=None):
    """Build ONE pinned dossier every seat reads from.

    Returns a dict with a `dossier_id` content hash. Missing pieces degrade to
    empty collections — a repo without release evidence still yields a usable
    dossier rather than an exception.
    """
    base_sha = base_sha or resolve_base_sha(repo_path)
    files = []
    for p in (paths or []):
        blob, ok = _git(["show", f"{base_sha}:{p}"], repo_path)
        files.append({"path": p, "present": bool(ok),
                      "sha256": hashlib.sha256(blob.encode()).hexdigest() if ok else "",
                      "lines": len(blob.splitlines()) if ok else 0})

    log, ok = _git(["log", f"--max-count={history_depth}", "--pretty=%H%x1f%s",
                    base_sha], repo_path)
    history = []
    if ok and log:
        for line in log.splitlines():
            parts = line.split("\x1f")
            if len(parts) == 2:
                history.append({"sha": parts[0], "subject": parts[1]})

    dossier = {
        "repo_path": repo_path,
        "base_sha": base_sha,
        "pinned_at": int(time.time()),
        "symbol_graph": symbol_graph(repo_path, base_sha, paths or []),
        "files": files,
        "history": history,
        "invariants": list(invariants or []),
        "failures": list(failures or []),
        "release_evidence": list(release_evidence or []),
    }
    dossier["dossier_id"] = digest({k: v for k, v in dossier.items()
                                    if k != "pinned_at"})
    return dossier


def symbol_graph(repo_path, base_sha, paths):
    """Top-level defs/classes per file, and which listed files import each other.

    Intentionally shallow and dependency-free: the point is to give every seat
    the same map of what exists and what depends on what, not to be a compiler.
    """
    nodes, edges = {}, []
    stems = {os.path.splitext(os.path.basename(p))[0]: p for p in paths}
    for p in paths:
        blob, ok = _git(["show", f"{base_sha}:{p}"], repo_path)
        if not ok:
            continue
        syms = []
        for line in blob.splitlines():
            if line.startswith("def ") or line.startswith("class "):
                syms.append(line.split("(")[0].replace("def ", "")
                            .replace("class ", "").strip(": "))
            stripped = line.strip()
            if stripped.startswith("import ") or stripped.startswith("from "):
                token = stripped.split()[1].split(".")[0]
                if token in stems and stems[token] != p:
                    edges.append({"from": p, "to": stems[token]})
        nodes[p] = syms
    return {"nodes": nodes, "edges": edges}


# ──────────────────────────────────────────── 2. capability probe + seating

def probe_capabilities(candidates, ask, timeout=None):
    """Return only the candidates that ACTUALLY answer a trivial probe.

    A catalog entry is a claim about a model, not evidence that this host can
    reach it — expired keys, regional gating, and renamed model ids all present
    as a catalog hit and a dead call. Seating an unreachable model produces an
    empty seat that looks like a considered abstention, which is worse than not
    seating it at all.

    `candidates` is a sequence of (provider, model). Fail-soft: a probe that
    raises simply drops that candidate.
    """
    live = []
    for provider, model in candidates or []:
        try:
            res = ask(provider, model, "Reply with the single word: ready",
                      operation="capability_probe",
                      timeout=timeout or PROBE_TIMEOUT) or {}
            if str(res.get("text", "")).strip():
                live.append((provider, model))
        except Exception:
            continue
    return live


def vendor_family(provider, model=""):
    """Best-effort vendor family, delegating to model_catalog when available."""
    try:
        import model_catalog
        return model_catalog.vendor_family(provider, model)
    except Exception:
        return str(provider or "").split(":")[0].lower()


def select_seats(live_candidates, max_seats=None):
    """One seat per vendor family, declared order preserved.

    Two models from the same family are highly correlated: they share training
    lineage and tend to share blind spots, so seating both buys cost without
    buying independence.
    """
    max_seats = max_seats or MAX_SEATS
    seats, seen = [], set()
    for provider, model in live_candidates or []:
        fam = vendor_family(provider, model)
        if fam in seen:
            continue
        seen.add(fam)
        seats.append({"provider": provider, "model": model, "family": fam,
                      "seat_id": f"seat-{len(seats) + 1}"})
        if len(seats) >= max_seats:
            break
    return seats


# ───────────────────────────────────────────────────────── 3-6. the rounds

def _seat_call(ask, seat, prompt, operation):
    """One seat, one call. Returns (text, error)."""
    try:
        res = ask(seat["provider"], seat["model"], prompt,
                  operation=operation, timeout=SEAT_TIMEOUT) or {}
        return str(res.get("text", "")).strip(), ""
    except Exception as exc:  # noqa: BLE001 — fail-soft, error recorded not raised
        return "", f"{type(exc).__name__}: {exc}"


def _dossier_brief(dossier):
    """The pinned evidence, rendered once, identical for every seat."""
    return (
        f"PINNED DOSSIER {dossier.get('dossier_id', '')[:12]} "
        f"@ base_sha {dossier.get('base_sha', '')[:12]}\n"
        f"files: {_canonical(dossier.get('files', []))}\n"
        f"symbols: {_canonical(dossier.get('symbol_graph', {}))}\n"
        f"recent history: {_canonical(dossier.get('history', [])[:10])}\n"
        f"invariants: {_canonical(dossier.get('invariants', []))}\n"
        f"known failures: {_canonical(dossier.get('failures', []))}\n"
        f"release evidence: {_canonical(dossier.get('release_evidence', []))}\n"
    )


def gather_proposals(seats, objective, dossier, ask):
    """Round 1: each seat drafts INDEPENDENTLY against the pinned dossier."""
    brief = _dossier_brief(dossier)
    out = []
    for seat in seats:
        text, err = _seat_call(
            ask, seat,
            "You are an independent planning seat. Using ONLY the pinned "
            "evidence below, propose ONE implementation approach: files to "
            "touch, sequence, migrations and rollback, tests, and the risks "
            "you accept.\n\n" + brief + "\nOBJECTIVE:\n" + (objective or ""),
            "council_proposal")
        out.append({"seat_id": seat["seat_id"], "provider": seat["provider"],
                    "model": seat["model"], "family": seat["family"],
                    "text": text, "error": err, "ok": bool(text)})
    return out


def anonymize(proposals):
    """Strip provider/model/family before cross-review.

    A seat that knows which vendor wrote a proposal critiques the vendor's
    reputation as much as the argument. The label is restored afterwards from
    `seat_id`, so evidence stays attributable even though review was blind.
    """
    return [{"label": f"Proposal {chr(65 + i)}", "seat_id": p["seat_id"],
             "text": p.get("text", "")}
            for i, p in enumerate(p_ for p_ in proposals if p_.get("ok"))]


def cross_critique(seats, anonymized, ask):
    """Round 2: every seat critiques every OTHER seat's proposal, blind."""
    out = []
    for seat in seats:
        others = [a for a in anonymized if a["seat_id"] != seat["seat_id"]]
        if not others:
            continue
        body = "\n\n".join(f"{a['label']}:\n{a['text']}" for a in others)
        text, err = _seat_call(
            ask, seat,
            "Critique each anonymous proposal below. For each: the strongest "
            "point, the fatal flaw if any, and what evidence would change your "
            "mind. Do not guess who wrote them.\n\n" + body,
            "council_critique")
        out.append({"seat_id": seat["seat_id"], "reviewed":
                    [a["label"] for a in others], "text": text,
                    "error": err, "ok": bool(text)})
    return out


def adversary_review(adversary_seat, objective, anonymized, ask):
    """A dedicated risk seat whose only job is to argue the plans down."""
    if not adversary_seat:
        return {"seat_id": "", "text": "", "error": "no adversary seat available",
                "ok": False}
    body = "\n\n".join(f"{a['label']}:\n{a['text']}" for a in anonymized)
    text, err = _seat_call(
        ask, adversary_seat,
        "You are the RISK ADVERSARY. Assume each plan below fails in "
        "production. Name the failure mode, the blast radius, the missing "
        "rollback, and the cheapest probe that would catch it early.\n\n"
        "OBJECTIVE:\n" + (objective or "") + "\n\n" + body,
        "council_adversary")
    return {"seat_id": adversary_seat["seat_id"], "text": text,
            "error": err, "ok": bool(text)}


def synthesize(judge_seat, objective, proposals, critiques, adversary, ask):
    """A SEPARATE judge merges the record into one recommendation.

    The judge is never one of the proposers: a model asked to grade its own
    proposal reliably grades it well, and the whole point of the council is an
    independent read of the record.
    """
    if not judge_seat:
        return {"seat_id": "", "text": "", "error": "no judge seat available",
                "ok": False}
    record = _canonical({
        "proposals": [{"seat_id": p["seat_id"], "text": p["text"]}
                      for p in proposals if p.get("ok")],
        "critiques": [{"seat_id": c["seat_id"], "text": c["text"]}
                      for c in critiques if c.get("ok")],
        "adversary": adversary.get("text", ""),
    })
    text, err = _seat_call(
        ask, judge_seat,
        "You are the SYNTHESIZING JUDGE and wrote none of these proposals. "
        "Merge the record into ONE implementation plan. State explicitly what "
        "is OUT of scope, which files each step owns, the step DAG, "
        "migrations and rollback, the tests and journey probes that prove it, "
        "and when to escalate to the owner.\n\nOBJECTIVE:\n"
        + (objective or "") + "\n\nRECORD:\n" + record,
        "council_judge")
    return {"seat_id": judge_seat["seat_id"], "provider": judge_seat["provider"],
            "text": text, "error": err, "ok": bool(text)}


# ────────────────────────────────────────────── 7. the signed contract

CONTRACT_FIELDS = ("objective", "non_goals", "file_ownership", "dag",
                   "migrations", "rollback", "tests", "journey_probes",
                   "budgets", "escalation")


def make_contract(objective, dossier, plan_text, seats, budget_usd=None,
                  non_goals=None, file_ownership=None, dag=None,
                  migrations=None, rollback=None, tests=None,
                  journey_probes=None, escalation=None):
    """Assemble the implementation contract body (unsigned).

    Every field is present even when empty. A contract with a missing key is
    ambiguous — did nobody consider rollback, or is there genuinely none? — so
    the shape is fixed and emptiness is explicit.
    """
    return {
        "objective": objective or "",
        "base_sha": dossier.get("base_sha", ""),
        "dossier_id": dossier.get("dossier_id", ""),
        "seats": [{"seat_id": s["seat_id"], "family": s["family"]} for s in seats],
        "plan": plan_text or "",
        "non_goals": list(non_goals or []),
        "file_ownership": dict(file_ownership or {}),
        "dag": list(dag or []),
        "migrations": list(migrations or []),
        "rollback": list(rollback or []),
        "tests": list(tests or []),
        "journey_probes": list(journey_probes or []),
        "budgets": {"usd": float(budget_usd if budget_usd is not None
                                 else DEFAULT_BUDGET_USD)},
        "escalation": list(escalation or [
            "owner-only if the change forces licensing, custody, or a new secret",
            "escalate on any rollback path that cannot be exercised in a test",
        ]),
    }


def sign_contract(contract):
    """Return {contract, contract_hash, signature}. HMAC over canonical JSON."""
    body_hash = digest(contract)
    sig = hmac.new(_SECRET, body_hash.encode(), hashlib.sha256).hexdigest()[:32]
    return {"contract": contract, "contract_hash": body_hash, "signature": sig}


def verify_contract(signed):
    """True only if the body still hashes to the signed hash.

    Catches both tampering and honest drift — a contract edited in place after
    signing must not execute under the old signature.
    """
    try:
        body_hash = digest(signed["contract"])
        if not hmac.compare_digest(body_hash, signed.get("contract_hash", "")):
            return False
        good = hmac.new(_SECRET, body_hash.encode(),
                        hashlib.sha256).hexdigest()[:32]
        return hmac.compare_digest(signed.get("signature", ""), good)
    except Exception:
        return False


# ──────────────────────────────────────────────── deterministic fallback

def fallback_contract(objective, dossier=None, reason="council skipped"):
    """The no-council path: same shape, deterministic, always signed.

    Callers consume one contract type whether or not the council ran, so the
    council can be disabled fleet-wide without touching any consumer.
    """
    dossier = dossier or {"base_sha": "", "dossier_id": ""}
    contract = make_contract(
        objective, dossier,
        plan_text="Single-planner path: implement the smallest correct change, "
                  "run the repo's existing checks, and commit.",
        seats=[],
        non_goals=["no architectural change", "no schema migration"],
        tests=["existing repo test suite must stay green"],
        escalation=["escalate to a full council if the change grows to touch "
                    "migrations, credentials, or release paths"])
    signed = sign_contract(contract)
    signed.update({"convened": False, "reason": reason, "evidence": {
        "proposals": [], "critiques": [], "adversary": {}, "judge": {}}})
    return signed


def persist(record, persister=None, artifact_dir=None):
    """Write the council record. Fail-soft — a failed write never blocks work.

    Returns the artifact path, or "" if nothing was written.
    """
    if persister is not None:
        try:
            persister(record)
        except Exception:
            pass
    target = artifact_dir or os.environ.get("ORCH_COUNCIL_ARTIFACT_DIR", "")
    if not target:
        return ""
    try:
        os.makedirs(target, exist_ok=True)
        name = f"council-{record.get('contract_hash', 'unknown')[:16]}.json"
        path = os.path.join(target, name)
        with open(path, "w") as fh:
            json.dump(record, fh, indent=2, sort_keys=True, default=str)
        return path
    except Exception:
        return ""


# ─────────────────────────────────────────────────────── the orchestrator

def convene(task, objective, repo_path, ask, candidates,
            paths=None, invariants=None, failures=None,
            release_evidence=None, base_sha=None, budget_usd=None,
            persister=None, artifact_dir=None):
    """Run the full council and return ONE signed contract plus its evidence.

    Returns the same dict shape in every path — `convened` says whether the
    council actually ran, `reason` says why not. Never raises: the caller is a
    task runner, and a planning stage that raises wedges the queue.
    """
    if not should_convene(task, objective):
        return fallback_contract(objective, reason="objective is small or mechanical")

    try:
        dossier = build_dossier(repo_path, base_sha=base_sha, paths=paths,
                                invariants=invariants, failures=failures,
                                release_evidence=release_evidence)
    except Exception as exc:  # noqa: BLE001 — fail-soft, reason recorded
        return fallback_contract(objective, reason=f"dossier failed: {exc}")

    live = probe_capabilities(candidates, ask)
    seats = select_seats(live)
    # A judge must be independent of the proposers, so the last live seat is
    # reserved for judging and never drafts. Below quorum, no council.
    if len(seats) < MIN_SEATS + 1:
        return fallback_contract(
            objective, dossier,
            reason=f"insufficient live frontier seats ({len(seats)} reachable, "
                   f"need {MIN_SEATS + 1})")

    judge_seat = seats[-1]
    proposer_seats = seats[:-1]
    adversary_seat = proposer_seats[-1] if len(proposer_seats) > 1 else judge_seat

    proposals = gather_proposals(proposer_seats, objective, dossier, ask)
    if not any(p.get("ok") for p in proposals):
        return fallback_contract(objective, dossier,
                                 reason="no seat produced a proposal")

    anonymized = anonymize(proposals)
    critiques = cross_critique(proposer_seats, anonymized, ask)
    adversary = adversary_review(adversary_seat, objective, anonymized, ask)
    judgment = synthesize(judge_seat, objective, proposals, critiques,
                          adversary, ask)

    plan_text = judgment.get("text") or ""
    if not plan_text:
        # The judge is the only seat that can produce the merged plan; without
        # it there is no contract to sign, so degrade rather than sign a plan
        # nobody wrote.
        return fallback_contract(objective, dossier,
                                 reason="judge produced no synthesis")

    contract = make_contract(objective, dossier, plan_text, proposer_seats,
                             budget_usd=budget_usd)
    signed = sign_contract(contract)
    signed.update({
        "convened": True,
        "reason": "",
        "evidence": {
            "candidates_offered": len(candidates or []),
            "candidates_live": len(live),
            "proposals": proposals,
            "critiques": critiques,
            "adversary": adversary,
            "judge": judgment,
            "anonymized_labels": [a["label"] for a in anonymized],
        },
    })
    signed["artifact_path"] = persist(signed, persister=persister,
                                      artifact_dir=artifact_dir)
    return signed


def contract_brief(signed):
    """Render a signed contract for injection into a coder prompt."""
    c = (signed or {}).get("contract", {})
    if not c:
        return ""
    lines = [f"# Implementation contract {signed.get('contract_hash', '')[:12]} "
             f"(pinned @ {c.get('base_sha', '')[:12]} — follow it)"]
    lines.append(c.get("plan", ""))
    if c.get("non_goals"):
        lines.append("NON-GOALS: " + "; ".join(c["non_goals"]))
    if c.get("file_ownership"):
        lines.append("FILE OWNERSHIP: " + _canonical(c["file_ownership"]))
    if c.get("rollback"):
        lines.append("ROLLBACK: " + "; ".join(c["rollback"]))
    if c.get("tests"):
        lines.append("TESTS: " + "; ".join(c["tests"]))
    if c.get("escalation"):
        lines.append("ESCALATE: " + "; ".join(c["escalation"]))
    return "\n".join(x for x in lines if x)


if __name__ == "__main__":
    print("frontier_council: gate markers =", len(MATERIAL_MARKERS),
          "| seats", MIN_SEATS, "-", MAX_SEATS)

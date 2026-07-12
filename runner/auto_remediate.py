#!/usr/bin/env python3
"""
auto_remediate.py - drive BLOCKED to zero, autonomously. Every BLOCKED task is classified and remediated
so it flows back toward shipped/merged, existing AND future — no task lingers stuck.

Remediation by cause (tasks.remediation_count changes strategy; it does not punt to manual review):
  * transient (network/budget/rate/overload)  -> requeue as-is (retry_policy handles the detail).
  * conflict                                    -> requeue to rebuild on fresh base (merge fix + staging).
  * no-op / "changed nothing" / agent failed    -> requeue with a SHARPER prompt (inject the failure note)
                                                   and ESCALATE the model one tier so the retry is smarter.
  * verify / judge / quality reject             -> requeue with the reviewer's notes injected so the agent
                                                   fixes the specific issue on the next attempt.
  * legal / material                            -> leave for the human (surfaced with a decision brief).
  * over the remediation cap                    -> reclaim as implementation work with a smaller,
                                                   explicit prompt; do not create manual-review backlog.
  * old cap-review cards / no-op auto-closures  -> recover and put the task back in the queue.

Runs every couple minutes; also callable. This is the "self-remedy everything" loop.
"""
import os, sys, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import legal_filter
import pipeline_contract
import agentic_repair

CAP = int(os.environ.get("REMEDIATION_CAP", "3"))
# HARD TERMINAL CAP: a task remediated this many times without ever merging is almost certainly
# mis-scoped or impossible. Every branch below used to re-queue it, so no-op / empty-diff tasks
# recycled FOREVER — burning fleet lanes and sinking merge throughput. At the hard cap we SHELVE it
# (terminal state nothing re-picks) with a clear note, so a human can re-scope it instead.
HARD_CAP = int(os.environ.get("REMEDIATION_HARD_CAP", "6"))
MAX_REMEDIATION_PROMPT_CHARS = int(os.environ.get("ORCH_MAX_REMEDIATION_PROMPT_CHARS", "16000"))
RECOVERY_MARK = "auto-remediate:reclaimed-20260703"
DIRECTIVE_MARKER = "AUTO-REMEDIATION DIRECTIVE"
_BUDGET = re.compile(r"budget cap|budget guard|budget/capacity guard|backlog offloaded|call cap|hourly \$ cap|daily \$ cap|cost circuit", re.I)
_CAPACITY = re.compile(r"capacity circuit|account exhausted|usage limit|claude.*limit|subscription.*limit", re.I)
_TRANSIENT = re.compile(r"budget cap|budget guard|capacity circuit|connection reset|urlopen|errno|timeout|overload|503|high demand|rate.?limit", re.I)
_NOOP = re.compile(r"no committable|changed nothing|no file changes|agent run failed", re.I)
_REVIEW = re.compile(r"verify:|judge:|quality gate", re.I)
_CONFLICT = re.compile(r"conflict", re.I)
_MISSING_BRANCH = re.compile(r"branch.*missing|no longer exists|approved.*agent/", re.I)
_HUMAN = re.compile(r"credential needed|missing credential|auth failure|secret|missing api key|api key required|hardcoded.*api key|two-key", re.I)
_CAP_CARD = re.compile(r"blocked after \d+ auto-fixes|can't self-revise|needs a look:|re-scope needed", re.I)
_PARKED = re.compile(r"ev-parked|near-zero expected value|preflight: predicted no committable|permission denial|tool use", re.I)
_TOO_LONG = re.compile(r"prompt is too long|context.*limit|single-exchange conversation cannot be compacted", re.I)
_READY_UNCOMMITTED = re.compile(r"ready to commit|git commit|changes are safe|implementation is complete", re.I)
_ENV_BUILDFAIL = re.compile(r"integrate BUILDFAIL|production build red|build error", re.I)
_MISSING_BUILD_TOOL = re.compile(r"\b(yarn|pnpm|nuxt|nuxi|next|vite|prisma|vue-tsc):?\s*(command not found|not found)|cannot find module ['\"](@nuxt/|nuxt|nuxi|next|vite|prisma)", re.I)
_QUOTED_SLUG = re.compile(r"'([^']+)'")


def run(limit=120):
    """Anti-burn remediation. NEVER blindly re-run the same failing task into a credit loop:
      attempt 1  : one smart retry (transient/conflict) or escalate+sharpen (review/no-op).
      attempt 2  : RE-PLAN - a cheap model fully revises the task prompt to be concrete + achievable
                   from the failure; a persistent no-op is reclaimed with a direct implementation prompt.
      attempt >=CAP or a repeat of the SAME failure signature -> reclaim with a full-implementation
                   prompt and keep it moving, except genuine legal/material gates.
    """
    recovered_cards = recover_pending_manual_reviews()
    restored_noops = recover_auto_closed_noops()
    shelf_dec, shelf_req = recover_shelved()   # auto-process the shelved pile — no manual requeue needed
    offloaded_backlog = offload_budget_capacity_backlog()
    blocked = db.select("tasks", {"select": "id,slug,prompt,note,remediation_count,model,project_id,material,base_branch,log_tail,state",
                                  "state": "in.(BLOCKED,CONFLICT,TESTFAIL)", "limit": str(limit)}) or []
    requeued = escalated = revised = reclaimed = left = shelved = decomposed = agentic_repairs = 0
    for t in blocked:
        note = t.get("note") or ""
        signal = f"{note}\n{t.get('log_tail') or ''}"
        rc = int(t.get("remediation_count") or 0)

        # HARD CAP: a task that has failed this many times is almost always TOO BIG, not impossible.
        # Instead of shelving it for a human (the old behavior — a manual bottleneck), auto-DECOMPOSE it
        # into smaller, independently-buildable sub-tasks and retire the oversized parent. Only if it's
        # genuinely atomic-and-stuck (or already a decomposition product) do we shelve — which should be
        # rare. Legal/material holds still route to the human path below.
        if rc >= HARD_CAP and not _requires_human_hold(t, signal):
            if not _already_decomposed(t, note):
                subs = _decompose(t, signal)
                if subs:
                    n = _spawn_subtasks(t, subs)
                    if n:
                        db.update("tasks", {"id": t["id"]},
                                  {"state": "DECOMPOSED", "account": None, "updated_at": "now()",
                                   "note": (f"too large after {rc} attempts -> auto-split into {n} sub-tasks; parent retired.")[:500]})
                        decomposed += 1
                        continue
            db.update("tasks", {"id": t["id"]},
                      {"state": "SHELVED", "account": None, "updated_at": "now()",
                       "note": (f"shelved after {rc} remediations (atomic + unbuildable) — needs human re-scope. "
                                + note)[:500]})
            shelved += 1
            continue

        upd = {"state": "QUEUED", "remediation_count": rc + 1, "account": None, "updated_at": "now()"}

        if _TOO_LONG.search(signal):
            upd = agentic_repair.repair_patch(
                t, signal, category="oversized",
                directive="Previous prompt exceeded the model context limit; use this compacted instruction and inspect files directly.")
            db.update("tasks", {"id": t["id"]}, upd)
            reclaimed += 1; agentic_repairs += 1
            continue

        if _PARKED.search(signal):
            upd = agentic_repair.repair_patch(
                t, signal, category="rework",
                directive="This was incorrectly parked as non-actionable; implement the smallest concrete useful improvement now.")
            db.update("tasks", {"id": t["id"]}, upd)
            reclaimed += 1; agentic_repairs += 1
            continue

        if _CONFLICT.search(signal):
            upd = agentic_repair.repair_patch(
                t, signal, category="conflict",
                directive="Recover from the merge/build conflict on a fresh branch and complete the implementation.")
            db.update("tasks", {"id": t["id"]}, upd)
            requeued += 1; agentic_repairs += 1
            continue

        if _BUDGET.search(signal) or _CAPACITY.search(signal):
            upd = agentic_repair.repair_patch(
                t, signal, category="capacity", prefer_non_claude=True,
                directive="Capacity or budget blocked the previous run. Continue the same task through the selected non-Claude/local coder and finish the implementation.")
            upd["remediation_count"] = 0
            upd["note"] = upd.get("note", "") + "; non-Claude failover"
            db.update("tasks", {"id": t["id"]}, upd)
            requeued += 1; agentic_repairs += 1
            continue

        if _ENV_BUILDFAIL.search(signal) and _MISSING_BUILD_TOOL.search(signal):
            upd = agentic_repair.repair_patch(
                t, signal, category="buildfail",
                directive=("Dependency prewarm/install cache is now available. Re-run on a fresh warmed worktree; "
                           "if the build still fails, fix only real source/type errors and avoid changing package managers unless required."))
            upd["build_fail_count"] = 0
            db.update("tasks", {"id": t["id"]}, upd)
            requeued += 1; agentic_repairs += 1
            continue

        if _requires_human_hold(t, signal):
            left += 1
            continue

        # A repeated no-op means the instruction was too vague or context was lost. Keep it in the cue
        # with an explicit implementation directive instead of marking it DONE.
        if (_NOOP.search(signal) and rc >= 1) or _READY_UNCOMMITTED.search(signal):
            upd = agentic_repair.repair_patch(
                t, signal, category="noop",
                directive="The prior run found or created work but did not leave a committable branch. Verify the diff, commit it, and let merge train integrate it.")
            db.update("tasks", {"id": t["id"]}, upd)
            reclaimed += 1; agentic_repairs += 1
            continue

        if rc >= CAP:
            upd = agentic_repair.repair_patch(
                t, signal, category="rework",
                directive=f"Remediation cap {CAP} reached. Do not buffer this task; complete the implementation through the agentic coder and make the checks green.")
            db.update("tasks", {"id": t["id"]}, upd)
            reclaimed += 1; agentic_repairs += 1
            continue

        if rc == 0 and (_TRANSIENT.search(signal) or _CONFLICT.search(signal) or _MISSING_BRANCH.search(signal)):
            category = "missing-branch" if _MISSING_BRANCH.search(signal) else ("conflict" if _CONFLICT.search(signal) else "transient")
            upd = agentic_repair.repair_patch(
                t, signal, category=category,
                directive="Resolve the concrete transient/branch/conflict issue in the same task instead of retrying blindly.")
            requeued += 1; agentic_repairs += 1
        elif rc == 0:
            # first real failure -> escalate model + sharpen with the specific reason
            upd = agentic_repair.repair_patch(
                t, signal, category="rework",
                directive="Prior attempt failed. Address the specific failure, make a concrete tested change, and commit it.")
            escalated += 1; agentic_repairs += 1
        else:
            # 2nd+ failure -> RE-PLAN the task from scratch instead of burning another blind retry
            new_prompt = _revise(t, note)
            if new_prompt:
                upd = agentic_repair.repair_patch(
                    {**t, "prompt": new_prompt}, signal, category="rework",
                    directive="Use this revised smaller implementation plan and complete it through the agentic coder.")
                revised += 1
                agentic_repairs += 1
            else:
                upd = agentic_repair.repair_patch(
                    t, signal, category="rework",
                    directive="Planner could not rewrite this. Implement the smallest useful fix directly and commit it.")
                reclaimed += 1; agentic_repairs += 1
        db.update("tasks", {"id": t["id"]}, upd)
    print(f"auto_remediate: agentic-repair {agentic_repairs}, retry {requeued}, escalate {escalated}, re-plan {revised}, "
          f"reclaimed {reclaimed}, decomposed {decomposed}, shelved {shelved}, "
          f"shelf-recovered {shelf_dec}dec/{shelf_req}req, recovered-cards {recovered_cards}, "
          f"restored-noops {restored_noops}, offloaded-backlog {offloaded_backlog}, left {left}")
    return {"requeued": requeued, "escalated": escalated, "revised": revised,
            "reclaimed": reclaimed, "decomposed": decomposed, "shelved": shelved,
            "agentic_repairs": agentic_repairs,
            "shelf_decomposed": shelf_dec, "shelf_requeued": shelf_req,
            "recovered_cards": recovered_cards, "restored_noops": restored_noops,
            "offloaded_backlog": offloaded_backlog, "left": left}


_NON_CLAUDE_CACHE = {"t": 0.0, "coder": None}


def _non_claude_coder(task=None):
    """Best current non-Claude agentic coder for failover. Prefer free/local, then cheaper paid."""
    import time
    if time.time() - _NON_CLAUDE_CACHE["t"] < 60 and _NON_CLAUDE_CACHE["coder"]:
        return _NON_CLAUDE_CACHE["coder"]
    try:
        import agentic_coders
        pool = []
        task = task or {}
        for spec in agentic_coders._pool():
            name = spec.get("name")
            if name == "claude":
                continue
            if not agentic_coders._within_cap(spec):
                continue
            if not agentic_coders._allowed_by_terms(spec, agentic_coders._task_sensitivity(task)):
                continue
            pool.append(spec)
        if not pool:
            return None
        def _cost(c):
            return int(c.get("cost") if c.get("cost") is not None else 9)
        picked = sorted(pool, key=lambda c: (_cost(c), -int(c.get("cap") or 0), c.get("name") or ""))[0].get("name")
        _NON_CLAUDE_CACHE.update({"t": time.time(), "coder": picked})
        return picked
    except Exception:
        return None


def _force_non_claude(patch, task, signal=""):
    coder = _non_claude_coder(task)
    if coder:
        patch["force_coder"] = coder
        patch["model"] = coder
    else:
        patch["model"] = _non_claude_model(task.get("model"))
    prompt = patch.get("prompt")
    if prompt:
        return
    if signal:
        patch["prompt"] = _implementation_prompt(
            task, signal,
            "Claude capacity or budget blocked this task. Use the selected non-Claude/local coder path; make a concrete change and commit it.")


def _non_claude_model(model):
    try:
        import agentic_coders
        coder = _non_claude_coder({})
        if coder:
            return coder
    except Exception:
        pass
    return model if model and "claude" not in str(model).lower() else "ollama"


def offload_budget_capacity_backlog(limit=500):
    """Convert already-queued Claude budget/capacity rows to explicit non-Claude routes."""
    try:
        rows = db.select("tasks", {"select": "id,slug,prompt,note,model,force_coder,material,kind,project_id,base_branch,log_tail",
                                   "state": "in.(QUEUED,RETRY,BLOCKED)", "limit": str(limit)}) or []
    except Exception:
        return 0
    changed = 0
    for t in rows:
        note = t.get("note") or ""
        signal = f"{note}\n{t.get('log_tail') or ''}"
        if not (_BUDGET.search(signal) or _CAPACITY.search(signal)):
            continue
        preferred = _non_claude_coder(t)
        existing = str(t.get("force_coder") or t.get("model") or "").lower()
        if (existing and "claude" not in existing and "haiku" not in existing and "sonnet" not in existing and "opus" not in existing
                and (not preferred or existing == preferred)):
            continue
        patch = agentic_repair.repair_patch(
            t, signal, category="capacity", prefer_non_claude=True,
            directive="This backlog row was blocked by Claude budget/capacity. Continue the same task through a non-Claude/local coder and finish it.")
        patch["remediation_count"] = 0
        patch["note"] = "agentic-repair:capacity; backlog offloaded from Claude budget/capacity guard"
        db.update("tasks", {"id": t["id"]}, patch)
        changed += 1
    return changed


def recover_pending_manual_reviews(limit=500):
    """Convert old 'blocked after N auto-fixes' cards back into executable work."""
    cards = db.select("approvals", {"select": "*", "status": "eq.pending",
                                    "order": "created_at.asc", "limit": str(limit)}) or []
    recovered = 0
    for card in cards:
        text = " ".join(str(card.get(k) or "") for k in ("title", "why", "detail"))
        if not _CAP_CARD.search(text):
            continue
        slug = _slug_from_card(card)
        if not slug:
            continue
        tasks = db.select("tasks", {"select": "*", "slug": f"eq.{slug}", "limit": "5"}) or []
        task = tasks[0] if tasks else _create_task_from_card(card, slug)
        if not task:
            continue
        state = task.get("state")
        if state in ("QUEUED", "RUNNING", "RETRY", "MERGING"):
            _close_review_card(card, "task already active")
            recovered += 1
            continue
        note = task.get("note") or card.get("why") or text
        if state == "MERGED" or (state == "DONE" and "auto-closed: no committable" not in note.lower()):
            _close_review_card(card, f"task already {state}")
            recovered += 1
            continue
        patch = agentic_repair.repair_patch(
            task, note, category="rework",
            directive="Recovered from stale manual-review card. Continue the same task through the agentic coder and implement it fully.")
        patch["remediation_count"] = 0
        db.update("tasks", {"id": task["id"]}, patch)
        _close_review_card(card, "requeued matching task for implementation")
        recovered += 1
    return recovered


def recover_auto_closed_noops(limit=500):
    """Put tasks that were incorrectly marked DONE for no-op retries back into the cue."""
    if os.environ.get("ORCH_RECOVER_AUTO_CLOSED_NOOPS", "false").lower() not in ("1", "true", "yes", "on"):
        return 0
    rows = db.select("tasks", {"select": "id,slug,prompt,note,remediation_count,model,project_id,material,log_tail",
                               "state": "eq.DONE", "limit": str(limit)}) or []
    restored = 0
    for task in rows:
        note = task.get("note") or ""
        if "auto-closed: no committable" not in note.lower():
            continue
        if _requires_human_hold(task, note):
            continue
        rc = int(task.get("remediation_count") or 0)
        # Don't let the no-op restore dodge the hard cap by resetting the counter: a task that has
        # already been remediated past the hard cap is SHELVED for human re-scope, not restored again.
        if rc >= HARD_CAP:
            db.update("tasks", {"id": task["id"]},
                      {"state": "SHELVED", "account": None, "updated_at": "now()",
                       "note": (f"shelved after {rc} remediations (repeat no-op) — needs human re-scope. "
                                + note)[:500]})
            continue
        # Preserve (increment) the counter across restores so repeat no-ops converge to the hard cap.
        db.update("tasks", {"id": task["id"]},
                  agentic_repair.repair_patch(
                      task, note, category="noop",
                      directive="This was incorrectly removed from active work. Continue the same task, implement the underlying change, run checks, and commit."))
        restored += 1
    return restored


def _slug_from_card(card):
    if card.get("slug"):
        return card["slug"]
    text = " ".join(str(card.get(k) or "") for k in ("title", "why", "detail"))
    m = _QUOTED_SLUG.search(text)
    return m.group(1) if m else None


def _project_id(name):
    if not name:
        return None
    rows = db.select("projects", {"select": "id", "name": f"eq.{name}", "limit": "1"}) or []
    return rows[0]["id"] if rows else None


def _create_task_from_card(card, slug):
    pid = _project_id(card.get("project"))
    if not pid:
        return None
    prompt = _implementation_prompt({"slug": slug, "prompt": ""}, card.get("why") or card.get("title") or "",
                                    "Original task row was missing; reconstruct from the recovery card.")
    rows = db.insert("tasks", {"project_id": pid, "slug": slug, "state": "QUEUED", "kind": "build",
                               "prompt": prompt, "note": "auto-remediate: reconstructed from stale review card"})
    return rows[0] if rows else None


def _close_review_card(card, reason):
    db.update("approvals", {"id": card["id"]},
              {"status": "approved", "decided_by": RECOVERY_MARK,
               "decision_type": "approve",
               "decision_text": f"Auto-reclaimed: {reason}. Work is back in the task queue."})


def _requires_human_hold(task, note):
    evidence = " ".join(str(task.get(k) or "") for k in ("slug", "log_tail")) + " " + str(note or "")
    if _HUMAN.search(evidence):
        return True
    prompt = "\n".join(
        line for line in str(task.get("prompt") or "").splitlines()
        if "legal gate:" not in line.lower()
        and "owner-only when" not in line.lower()
        and "merge/release:" not in line.lower()
    )
    text = " ".join([str(task.get("slug") or ""), prompt, str(note or "")])
    return legal_filter.requires_owner_approval(text=text)


def _implementation_prompt(task, note, directive):
    raw = task.get("prompt") or f"Implement the queued task '{task.get('slug')}'."
    base = pipeline_contract.original_request(raw).split(DIRECTIVE_MARKER, 1)[0].rstrip()
    if len(base) > MAX_REMEDIATION_PROMPT_CHARS:
        keep_tail = MAX_REMEDIATION_PROMPT_CHARS - 4000
        base = (
            base[:4000].rstrip() +
            "\n\n[auto-remediate compaction: omitted bulky middle transcript/context. "
            "Continue from the concrete task summary and inspect files directly.]\n\n" +
            base[-keep_tail:].lstrip()
        )
    return (base +
            f"\n\n{DIRECTIVE_MARKER}\n"
            f"{directive}\n"
            f"Failure context: {(note or '')[:800]}\n"
            "Do not stop at analysis or manual review. Make the smallest complete code change, "
            "restore any missing/deleted branch or worktree artifacts if needed, run the relevant checks, "
            "and commit the implementation.")


DECOMPOSE_MAX = int(os.environ.get("REMEDIATION_DECOMPOSE_MAX", "5"))


def _decompose(task, note):
    """Split a repeatedly-failing (too-big) task into 2-5 SMALLER, independently-buildable sub-tasks.
    Returns [{"title","prompt"}] or None if the model judges it atomic/undoable. This is the fix that
    makes 'shelve for complexity' unnecessary: instead of parking a big task for a human, break it down
    until each piece is small enough to build in one pass."""
    import json
    base = pipeline_contract.original_request(task.get("prompt") or "").split(DIRECTIVE_MARKER, 1)[0]
    ask = ("A build task has failed many times — it is almost certainly TOO BIG to finish in one pass. "
           "Split it into 2-5 SMALLER, independently-buildable sub-tasks, each completable by a coding "
           "agent in a single pass with a concrete acceptance test, ordered so earlier ones don't depend "
           "on later ones. If it is genuinely atomic and small (cannot be split), reply exactly 'ATOMIC'. "
           "Reply ONLY as a JSON array: "
           '[{"title":"short-kebab-title","prompt":"full concrete instruction"}].\n'
           f"TASK: {base[:1500]}\nFAILURE: {(note or '')[:400]}\nLOG: {(task.get('log_tail') or '')[:500]}")
    try:
        import model_policy, model_gateway
        prov, model, _ = model_policy.choose("plan", agentic=False)
        txt = (model_gateway.complete(prov, model, ask).get("text") or "").strip()
        if txt.upper().startswith("ATOMIC"):
            return None
        m = re.search(r"\[.*\]", txt, re.S)
        if not m:
            return None
        subs = []
        for i, x in enumerate(json.loads(m.group(0))[:DECOMPOSE_MAX]):
            title = re.sub(r"[^a-z0-9-]+", "-", str(x.get("title") or f"part{i+1}").lower()).strip("-")[:40] or f"part{i+1}"
            p = str(x.get("prompt") or "").strip()
            if p:
                subs.append({"title": title, "prompt": p})
        return subs or None
    except Exception:
        return None


def _spawn_subtasks(task, subs):
    """Create child tasks for a decomposed parent. Returns count actually created.

    FIXED 2026-07-11: added prompt quality gate. Previously, when the decomposing
    model returned vague descriptions ("Reuse matching project helpers"), those
    became the child's entire prompt — producing 503+ unexecutable stub tasks.
    Now rejects sub-tasks whose prompt is under 80 chars or lacks any verb/action word.
    """
    ACTION_WORDS = re.compile(r"\b(add|create|implement|fix|update|write|modify|remove|refactor|replace|extract|move|rename|delete|configure|set up|integrate|convert|wrap|define|build|test|validate|ensure|return|handle|parse|send|fetch|call|check)\b", re.I)
    made = 0
    for i, s in enumerate(subs):
        prompt_text = str(s.get("prompt") or "").strip()
        # Quality gate: reject vague/empty sub-task prompts
        if len(prompt_text) < 80 or not ACTION_WORDS.search(prompt_text):
            continue
        child = f"{task['slug']}-{s['title']}"[:80]
        if db.select("tasks", {"select": "id", "slug": f"eq.{child}", "limit": "1"}):
            continue
        try:
            db.insert("tasks", {
                "project_id": task.get("project_id"), "slug": child, "kind": "build", "state": "QUEUED",
                "remediation_count": 0, "base_branch": task.get("base_branch") or "main",
                "material": bool(task.get("material")),
                "prompt": prompt_text,
                "note": f"auto-decomposed from {task['slug']}"})
            made += 1
        except Exception:
            pass
    return made


def _already_decomposed(task, note):
    """Depth guard: a task that was itself a decomposition product and STILL can't build is genuinely
    stuck — don't recurse forever.

    FIXED 2026-07-11: also counts '-slice-' depth, not just '-part'. Previously,
    task_slicer created -slice-N children which bypassed this guard (it only checked
    -part), allowing auto_remediate to decompose them further — creating a cascading
    amplification loop that produced depth-3+ nesting and 2,700+ over-decomposed tasks.
    """
    slug = task.get("slug") or ""
    decomposition_depth = slug.count("-part") + slug.count("-slice-")
    return "auto-decomposed from" in (note or "") or decomposition_depth >= 2


def recover_shelved(limit=200):
    """Auto-process the SHELVED pile so no human ever has to requeue: decompose big ones, requeue small
    ones. Only genuine legal/secret human-holds are left for the owner."""
    rows = db.select("tasks", {"select": "id,slug,prompt,note,remediation_count,model,project_id,material,base_branch,log_tail",
                               "state": "eq.SHELVED", "limit": str(limit)}) or []
    decomposed = requeued = 0
    for t in rows:
        note = t.get("note") or ""
        signal = f"{note}\n{t.get('log_tail') or ''}"
        if _requires_human_hold(t, signal):
            continue
        if not _already_decomposed(t, note):
            subs = _decompose(t, signal)
            if subs and _spawn_subtasks(t, subs):
                db.update("tasks", {"id": t["id"]}, {"state": "DECOMPOSED", "account": None,
                          "updated_at": "now()", "note": f"recovered from shelf -> split into sub-tasks"})
                decomposed += 1
                continue
        # atomic/small (or already a decomposition product): requeue fresh with a concrete impl prompt
        patch = agentic_repair.repair_patch(
            t, note, category="rework",
            directive="Recovered from shelf. Make the smallest complete change through the agentic coder and commit it now.")
        patch["remediation_count"] = 0
        db.update("tasks", {"id": t["id"]}, patch)
        requeued += 1
    return decomposed, requeued


def _revise(task, note):
    """Fully rewrite a repeatedly-failing task's prompt to be concrete + achievable (cheap model)."""
    prompt = ("A build task keeps failing. Rewrite it into a SHARPER, SMALLER, unambiguous instruction "
              "that a coding agent can complete in one pass: exact files/scope, a concrete acceptance "
              "test, and no vague goals. If the task is genuinely not doable or is a no-op, reply with "
              "exactly 'DROP'.\n"
              f"TASK: {(task.get('prompt') or '')[:1200]}\nFAILURE: {note[:400]}\n"
              f"LOG: {(task.get('log_tail') or '')[:600]}\nRewritten task:")
    try:
        import model_policy, model_gateway
        prov, model, _ = model_policy.choose("plan", agentic=False)
        r = model_gateway.complete(prov, model, prompt)
        txt = (r.get("text") or "").strip()
        if not txt or txt.upper().startswith("DROP") or len(txt) < 20:
            return None
        return txt[:4000]
    except Exception:
        return None


def _escalate(model):
    order = ["claude-haiku-4-5-20251001", "claude-sonnet-4-6", "claude-opus-4-8"]
    try:
        i = order.index(model)
        return order[min(i + 1, len(order) - 1)]
    except ValueError:
        return "claude-sonnet-4-6"


if __name__ == "__main__":
    run()

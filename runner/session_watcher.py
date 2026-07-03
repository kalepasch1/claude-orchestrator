#!/usr/bin/env python3
"""
session_watcher.py - the orchestrator reads Claude Code sessions when they pause/finish and
decides the best next step. Runs on the Mac, where it can read the transcripts at
~/.claude/projects/**/*.jsonl (set CLAUDE_PROJECTS_DIR to override). For each session that's
gone idle it: (1) extracts the last output + master prompt + phases, (2) asks a model for the
single best next step, (3) files a session_action (auto-queues a follow-up if the step is
low-risk and AUTO mode; otherwise files a decision card), (4) harvests any orchestrator
feedback so INTERACTIVE VS Code sessions feed the loop too, (5) flags merged worktrees for
the resource governor to reclaim, (6) closes finished VS Code tabs when the transcript
confirms all phases are done.
"""
import os, sys, json, glob, time, subprocess, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db, feedback, claude_cli

MODEL = os.environ.get("NEXTSTEP_MODEL", "claude-sonnet-4-6")
PROJECTS_DIR = os.environ.get("CLAUDE_PROJECTS_DIR", os.path.expanduser("~/.claude/projects"))
IDLE = int(os.environ.get("SESSION_IDLE_SECONDS", "120"))
AUTO = os.environ.get("SESSION_AUTO_CONTINUE", "true").lower() == "true"
FORCE_CONTINUE = os.environ.get("SESSION_FORCE_CONTINUE", "true").lower() == "true"
CLOSE_TABS = os.environ.get("SESSION_CLOSE_TABS", "true").lower() == "true"
STATE = os.path.join(os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator")), "watched.json")


def _seen():
    try:
        return json.load(open(STATE))
    except Exception:
        return {}


def _save(seen):
    try:
        json.dump(seen, open(STATE, "w"))
    except Exception:
        pass


def _last_output(path, max_lines=600):
    """Pull last assistant text, last user prompt, and the FIRST user message (master prompt)."""
    try:
        lines = open(path, errors="replace").readlines()
    except Exception:
        return "", "", ""
    last_assistant, last_user, first_user = "", "", ""
    for ln in lines[-max_lines:]:
        try:
            ev = json.loads(ln)
        except Exception:
            continue
        msg = ev.get("message", ev)
        role = msg.get("role") or ev.get("type")
        content = msg.get("content")
        text = ""
        if isinstance(content, list):
            text = " ".join(c.get("text", "") for c in content if isinstance(c, dict))
        elif isinstance(content, str):
            text = content
        if role == "assistant" and text.strip():
            last_assistant = text
        elif role == "user" and text.strip():
            last_user = text
    # first user message = master prompt (scan from the top of the full file)
    try:
        all_lines = open(path, errors="replace").readlines()
        for ln in all_lines[:200]:
            try:
                ev = json.loads(ln)
                msg = ev.get("message", ev)
                role = msg.get("role") or ev.get("type")
                content = msg.get("content")
                text = ""
                if isinstance(content, list):
                    text = " ".join(c.get("text", "") for c in content if isinstance(c, dict))
                elif isinstance(content, str):
                    text = content
                if role == "user" and text.strip():
                    first_user = text[:3000]
                    break
            except Exception:
                continue
    except Exception:
        pass
    return last_assistant[-6000:], last_user[-1500:], first_user


def _extract_phases(master_prompt):
    """Infer phases/waves from the master prompt text (look for numbered lists / 'phase N' markers)."""
    phases = re.findall(r"(?:phase|wave|step)\s*(\d+)[:\.\)]\s*([^\n]{0,120})", master_prompt, re.I)
    if not phases:
        # numbered list items
        phases = re.findall(r"^\s*(\d+)[\.:\)]\s+(.{10,120})", master_prompt, re.M)
    return [{"n": int(n), "label": l.strip()} for n, l in phases[:10]]


PROMPT = """A Claude Code session just paused/finished.

MASTER PROMPT (what the user originally asked): {master}

PHASES/WAVES DETECTED (from the master prompt): {phases}

LAST USER REQUEST: {req}

LAST OUTPUT: {out}

Decide the SINGLE best next step to keep the work moving, honoring any unfinished phases.
Reply ONE JSON object only (no prose):
{{"next_action":"<imperative next step>","auto_safe":true|false,"done":true|false,"phases_remaining":<int or null>}}

done=true ONLY if ALL phases/waves from the master prompt are complete.
auto_safe=true only if the step is low-risk and clearly defined."""


def _decide(req, out, master="", phases=None):
    phase_txt = json.dumps(phases or [])
    p = (PROMPT.replace("{req}", req).replace("{out}", out)
         .replace("{master}", master[:2000]).replace("{phases}", phase_txt))
    errors = []
    try:
        r = claude_cli.run(p, MODEL, permission=None, max_turns=1, timeout=120)
        parsed = _parse_decision(r.get("text") or "")
        if parsed:
            return parsed
        errors.append("claude returned no JSON")
    except Exception as e:
        errors.append(f"claude: {e}")
    for _ in range(4):
        try:
            import model_policy, model_gateway
            prov, model, _why = model_policy.choose("plan", agentic=False)
            r = model_gateway.complete(prov, model, p, project="orchestrator",
                                       operation="session_next_step", task_class="plan",
                                       fallback=True)
            parsed = _parse_decision(r.get("text") or "")
            if parsed:
                return parsed
            errors.append(f"{r.get('provider')}/{r.get('model')}: no JSON")
        except Exception as e:
            errors.append(str(e))
    return {"next_action": "Continue the unfinished implementation from this paused session. Inspect the transcript context, complete the remaining code changes, run the relevant checks, and let the normal merge train integrate the result.",
            "auto_safe": True, "done": False, "phases_remaining": None,
            "decision_fallback": "; ".join(errors)[-500:]}


def _parse_decision(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except Exception:
        return None
    if not isinstance(d, dict) or not d.get("next_action"):
        return None
    return {
        "next_action": str(d.get("next_action"))[:2000],
        "auto_safe": bool(d.get("auto_safe")),
        "done": bool(d.get("done")),
        "phases_remaining": d.get("phases_remaining"),
    }


def _project_for(path):
    enc = os.path.basename(os.path.dirname(path))
    return enc.replace("-", "/").split("/")[-1] or enc


def _is_in_progress(out):
    """Return True if the transcript output suggests the session is still actively working."""
    in_progress_signals = (
        "running", "executing", "installing", "building", "compiling",
        "please wait", "in progress", "🔄", "⠋", "⠙", "⠹", "⠸",
    )
    low = (out or "").lower()
    return any(s in low for s in in_progress_signals)


# ── VS Code tab closer ────────────────────────────────────────────────────────

def _close_vscode_tab(session_id, transcript_path):
    """
    Close a finished session's tab in VS Code via the `code` CLI.
    Uses code --reuse-window to focus the file, then code --command to close it.
    Writes to the close-queue if the CLI approach fails (e.g. no VS Code running).
    NEVER called unless the session is confirmed done=True.
    """
    queue_path = os.path.join(
        os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator")),
        "close_queue.jsonl")
    entry = json.dumps({"session_id": session_id, "path": transcript_path, "ts": time.time()})
    try:
        open(queue_path, "a").write(entry + "\n")
    except Exception:
        pass
    try:
        if not os.path.exists(transcript_path):
            return False
        subprocess.run(["code", "--reuse-window", transcript_path],
                       capture_output=True, timeout=5)
        time.sleep(0.4)
        subprocess.run(["code", "--command", "workbench.action.closeActiveEditor"],
                       capture_output=True, timeout=5)
        return True
    except Exception:
        return False


def scan():
    seen = _seen()
    made = 0
    cap = int(os.environ.get("SESSION_MAX_PER_SCAN", "8"))   # cost + noise guard
    known = {p["name"] for p in (db.select("projects", {"select": "name"}) or [])}
    for path in glob.glob(os.path.join(PROJECTS_DIR, "**", "*.jsonl"), recursive=True):
        try:
            mtime = os.path.getmtime(path)
        except Exception:
            continue
        if time.time() - mtime < IDLE:               # still active
            continue
        sid = os.path.splitext(os.path.basename(path))[0]
        if seen.get(sid) == mtime:                    # already handled this state
            continue
        # skip the orchestrator's OWN headless/worktree transcripts — only watch real,
        # registered interactive projects (prevents the 15k-card / 15k-model-call flood)
        if "-wt" in path or _project_for(path) not in known:
            seen[sid] = mtime; continue
        out, req, master = _last_output(path)
        if not out:
            seen[sid] = mtime; continue

        # GUARD: don't process if transcript still shows active signals
        if _is_in_progress(out[-500:]):
            continue

        phases = _extract_phases(master) if master else []

        # interactive sessions feed the feedback loop too
        try:
            feedback.extract_and_store(out, project=_project_for(path), slug=sid[:8], task_id=None)
        except Exception:
            pass

        d = _decide(req, out, master, phases)
        done = bool(d.get("done"))
        phases_remaining = d.get("phases_remaining")
        auto = bool((AUTO and d.get("auto_safe") and not done) or (FORCE_CONTINUE and not done))

        status = "finished" if done else ("queued" if auto else "paused")
        db.insert("session_actions", {
            "session_id": sid, "project": _project_for(path),
            "status": status, "summary": out[-500:],
            "next_action": d.get("next_action"), "auto": auto,
        })

        if auto:
            proj = db.select("projects", {"select": "id", "name": f"eq.{_project_for(path)}"}) or []
            if proj:
                db.insert("tasks", {"project_id": proj[0]["id"], "slug": f"cont-{sid[:6]}",
                                    "kind": "build", "state": "QUEUED", "prompt": d["next_action"]})
        # NOTE: routine "paused — next step" notices live in session_actions ONLY (the
        # dashboard Sessions panel reads that). We do NOT file an approval per paused session —
        # that flooded the approval queue (15k cards) and is pure noise. Approvals are reserved
        # for things that genuinely need a decision.

        # Close finished VS Code tabs (gated: done=True AND tab close is enabled)
        if done and CLOSE_TABS:
            _close_vscode_tab(sid, path)

        seen[sid] = mtime; made += 1
        if made >= cap:                               # per-scan cap (cost + noise guard)
            break
    _save(seen)
    print(f"session_watcher: processed {made} idle sessions (auto_continue={AUTO})")
    return made


def recover_paused(limit=200):
    """Convert old paused session_actions into queued continuation work."""
    rows = db.select("session_actions", {"select": "id,session_id,project,next_action,status",
                                         "status": "eq.paused", "limit": str(limit)}) or []
    projects = {p["name"]: p["id"] for p in (db.select("projects", {"select": "id,name"}) or [])}
    queued = hidden = 0
    for s in rows:
        action = (s.get("next_action") or "").strip()
        pid = projects.get(s.get("project"))
        if pid and action and not action.startswith("("):
            slug = f"cont-{(s.get('session_id') or s['id'])[:8]}"
            try:
                db.insert("tasks", {"project_id": pid, "slug": slug, "kind": "build", "state": "QUEUED",
                                    "prompt": action,
                                    "note": "source:session-autocontinue; recovered from paused session"})
                queued += 1
            except Exception:
                pass
        db.update("session_actions", {"id": s["id"]}, {"status": "queued"})
        hidden += 1
    print(f"session_watcher: recovered {queued} paused sessions, hid {hidden}")
    return {"queued": queued, "hidden": hidden}


if __name__ == "__main__":
    scan()

#!/usr/bin/env python3
"""
batch_pass.py - Claude Batch API integration for off-peak processing.

Tasks with kind='batch' (or any QUEUED tasks during the overnight batch window)
are submitted as a Batch API job at 50% cost with ~24 h turnaround. This handles
non-urgent research/efficiency passes without occupying the interactive runner.

Env:
  ANTHROPIC_API_KEY   - required (Batch API uses direct HTTP, not the CLI)
  BATCH_MODEL         - default claude-haiku-4-5-20251001 (cheapest)
  BATCH_MAX_TOKENS    - default 4096
  BATCH_STATE_FILE    - default ~/.claude-orchestrator/batches.json

Flow (called by periodic.py):
  submit()  - collect QUEUED batch tasks, send to /v1/messages/batches, save IDs
  poll()    - check pending batches; on completion, update task states in Supabase
  run()     - submit() then poll() (called by periodic.py batch job)
"""
import os, sys, json, time, urllib.request, urllib.error
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MODEL = os.environ.get("BATCH_MODEL", "claude-haiku-4-5-20251001")
MAX_TOKENS = int(os.environ.get("BATCH_MAX_TOKENS", "4096"))
BETA = "message-batches-2024-09-24"
BASE = "https://api.anthropic.com/v1"
HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
STATE_FILE = os.environ.get("BATCH_STATE_FILE", os.path.join(HOME, "batches.json"))
os.makedirs(HOME, exist_ok=True)


def _api(method, path, body=None):
    if not API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY not set — Batch API requires a direct API key")
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"x-api-key": API_KEY, "anthropic-version": "2023-06-01",
                 "anthropic-beta": BETA, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def _load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}       # {batch_id: {task_ids: [...], submitted_at: ...}}


def _save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def submit():
    """Collect QUEUED batch tasks and submit to the Batch API."""
    tasks = db.select("tasks", {"select": "*", "state": "eq.QUEUED",
                                "kind": "eq.batch"}) or []
    if not tasks:
        print("batch submit: no QUEUED batch tasks")
        return None

    requests = []
    for t in tasks:
        # inject project context into the prompt
        proj = (db.select("projects", {"select": "name", "id": f"eq.{t['project_id']}"}) or [{}])[0]
        requests.append({
            "custom_id": str(t["id"]),
            "params": {
                "model": MODEL,
                "max_tokens": MAX_TOKENS,
                "messages": [{"role": "user", "content": t["prompt"]}],
            }
        })
        db.update("tasks", {"id": t["id"]},
                  {"state": "WAITING", "note": "submitted to Batch API (pending)"})

    result = _api("POST", "/messages/batches", {"requests": requests})
    batch_id = result["id"]
    state = _load_state()
    state[batch_id] = {"task_ids": [t["id"] for t in tasks],
                       "submitted_at": time.time()}
    _save_state(state)
    print(f"batch submit: {len(requests)} tasks → {batch_id}")
    return batch_id


def poll():
    """Check all pending batches; process results when complete."""
    state = _load_state()
    if not state:
        print("batch poll: no pending batches")
        return
    done_batches = []
    for batch_id, meta in state.items():
        try:
            info = _api("GET", f"/messages/batches/{batch_id}")
        except Exception as e:
            print(f"batch poll: {batch_id} status error ({e})")
            continue

        status = info.get("processing_status")
        counts = info.get("request_counts", {})
        print(f"batch poll: {batch_id} status={status} {counts}")

        if status != "ended":
            continue

        # Fetch results (JSONL stream)
        results_url = info.get("results_url")
        if not results_url:
            print(f"batch {batch_id}: no results_url yet")
            continue

        _process_results(batch_id, results_url, meta["task_ids"])
        done_batches.append(batch_id)

    for b in done_batches:
        del state[b]
    _save_state(state)


def _process_results(batch_id, results_url, task_ids):
    req = urllib.request.Request(
        results_url,
        headers={"x-api-key": API_KEY, "anthropic-version": "2023-06-01",
                 "anthropic-beta": BETA})
    with urllib.request.urlopen(req, timeout=60) as r:
        lines = r.read().decode().splitlines()

    task_set = set(str(t) for t in task_ids)
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        task_id = row.get("custom_id")
        if not task_id or task_id not in task_set:
            continue

        result = row.get("result", {})
        rtype = result.get("type")
        if rtype == "succeeded":
            content = (result.get("message", {}).get("content") or [{}])
            text = next((c["text"] for c in content if c.get("type") == "text"), "")
            # store result as completed note (agent didn't write files, just produced text)
            db.update("tasks", {"id": task_id},
                      {"state": "DONE", "log_tail": text[-2000:],
                       "note": f"batch {batch_id[:16]} completed"})
            # store in knowledge base for reuse
            try:
                import knowledge_embed as ke
                task_row = (db.select("tasks", {"select": "slug,project_id",
                                                "id": f"eq.{task_id}"}) or [{}])[0]
                proj = (db.select("projects", {"select": "name",
                                               "id": f"eq.{task_row.get('project_id')}"}) or [{}])[0]
                ke.extract(proj.get("name", "?"), f"batch:{task_row.get('slug','?')}",
                           "batch,off-peak", text[:4000])
            except Exception:
                pass
        elif rtype == "errored":
            err = result.get("error", {}).get("message", "unknown")
            db.update("tasks", {"id": task_id},
                      {"state": "BLOCKED", "note": f"batch error: {err}"})
        elif rtype == "expired":
            db.update("tasks", {"id": task_id},
                      {"state": "QUEUED", "note": "batch expired — re-queued for interactive run"})

    print(f"batch {batch_id}: processed {len(lines)} results")


def run():
    """Full off-peak pass: submit new batch tasks, then poll all pending.
    GUARDED: the Batch API bills prepaid API credits (NOT your Max subscription) — it was a source
    of the ~$500 June invoice. It only runs if you've explicitly opted into API billing."""
    try:
        import subscription_guard
        if not subscription_guard.require_api_or_skip("batch_pass (Batch API)"):
            return
    except Exception:
        # if the guard can't load, fail CLOSED (do not bill) when a key isn't explicitly opted in
        if os.environ.get("ORCH_ALLOW_API_BILLING", "false").lower() != "true":
            print("batch_pass: skipped (billing guard unavailable; failing closed)")
            return
    submit()
    poll()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    {"submit": submit, "poll": poll, "run": run}.get(cmd, run)()

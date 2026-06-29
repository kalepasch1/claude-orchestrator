#!/usr/bin/env python3
"""
supabase_twin.py - Supabase branch digital-twin per PR.

On PR open: create an isolated Supabase branch so the preview app runs against
its own copy of the DB (no prod data leaks into testing, no review-app writes
pollute prod). On PR merge/close: delete the branch to avoid orphans.

Uses the Supabase Management API (requires SUPABASE_ACCESS_TOKEN and
SUPABASE_PROJECT_REF env vars — these are separate from the runner's service key).

  create(pr_number, branch_name=None)  → {"branch_id": ..., "db_url": ..., "ref": ...}
  delete(branch_id_or_pr_number)       → ok bool
  list_pr_branches()                   → [{pr, branch_id, name, status}]

The branch DB URL is written to a Vercel deployment's environment variables by
pr_integrate.py so the preview build picks it up automatically.
"""
import os, sys, json, time, urllib.request, urllib.error
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ACCESS_TOKEN = os.environ.get("SUPABASE_ACCESS_TOKEN", "")
PROJECT_REF = os.environ.get("SUPABASE_PROJECT_REF", "")
MGMT_BASE = "https://api.supabase.com/v1"

# Local registry mapping PR number → Supabase branch ID
HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
REGISTRY_FILE = os.path.join(HOME, "supabase-branches.json")
os.makedirs(HOME, exist_ok=True)


def _mgmt(method, path, body=None):
    if not ACCESS_TOKEN or not PROJECT_REF:
        raise RuntimeError("Set SUPABASE_ACCESS_TOKEN and SUPABASE_PROJECT_REF")
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        MGMT_BASE + path, data=data, method=method,
        headers={"Authorization": f"Bearer {ACCESS_TOKEN}",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        body_txt = e.read().decode()
        raise RuntimeError(f"Supabase API {method} {path} → {e.code}: {body_txt}")


def _load_registry():
    try:
        with open(REGISTRY_FILE) as f:
            return json.load(f)
    except Exception:
        return {}       # {str(pr_number): {branch_id, name, created_at}}


def _save_registry(reg):
    with open(REGISTRY_FILE, "w") as f:
        json.dump(reg, f, indent=2)


def create(pr_number, branch_name=None):
    """Create a Supabase branch for the given PR. Returns branch metadata."""
    name = branch_name or f"pr-{pr_number}"
    try:
        result = _mgmt("POST", f"/projects/{PROJECT_REF}/branches",
                       {"branch_name": name, "region": "us-east-1"})
    except RuntimeError as e:
        # Branch may already exist (idempotent call on re-opened PR)
        if "already exists" in str(e).lower():
            print(f"twin: branch {name} already exists, looking it up...")
            existing = [b for b in list_pr_branches() if b["name"] == name]
            if existing:
                return existing[0]
        raise

    branch_id = result.get("id") or result.get("branch_id", "")
    db_host = result.get("db_host") or result.get("db_url", "")

    reg = _load_registry()
    reg[str(pr_number)] = {"branch_id": branch_id, "name": name,
                           "db_host": db_host, "created_at": time.time()}
    _save_registry(reg)
    print(f"twin: created branch {name} ({branch_id}) for PR #{pr_number}")
    return {"branch_id": branch_id, "name": name, "db_host": db_host}


def delete(pr_number_or_branch_id):
    """Delete the Supabase branch associated with a PR (or by branch ID directly)."""
    reg = _load_registry()
    key = str(pr_number_or_branch_id)
    if key in reg:
        branch_id = reg[key]["branch_id"]
        name = reg[key]["name"]
    else:
        branch_id = str(pr_number_or_branch_id)
        name = branch_id

    try:
        _mgmt("DELETE", f"/projects/{PROJECT_REF}/branches/{branch_id}")
        if key in reg:
            del reg[key]
            _save_registry(reg)
        print(f"twin: deleted branch {name} ({branch_id})")
        return True
    except RuntimeError as e:
        if "not found" in str(e).lower() or "404" in str(e):
            print(f"twin: branch {name} already gone")
            if key in reg:
                del reg[key]; _save_registry(reg)
            return True
        print(f"twin: delete failed ({e})")
        return False


def list_pr_branches():
    """Return all PR branches tracked in the local registry."""
    reg = _load_registry()
    return [{"pr": k, **v} for k, v in reg.items()]


def vercel_env_update(pr_number, db_host, vercel_token=None, vercel_project=None):
    """
    Push SUPABASE_URL override to the Vercel preview for a specific PR/branch.
    Requires VERCEL_TOKEN and VERCEL_PROJECT_ID env vars (or pass directly).
    The Vercel preview Git branch must match the PR branch name.
    """
    token = vercel_token or os.environ.get("VERCEL_TOKEN", "")
    project = vercel_project or os.environ.get("VERCEL_PROJECT_ID", "")
    if not token or not project:
        print("twin: VERCEL_TOKEN/VERCEL_PROJECT_ID not set — skip Vercel env update")
        return False
    # Set NEXT_PUBLIC_SUPABASE_URL (or SUPABASE_URL) as a preview env var scoped to the PR branch
    branch_name = f"pr-{pr_number}"
    supabase_url = f"https://{db_host}" if db_host and not db_host.startswith("http") else db_host
    req = urllib.request.Request(
        f"https://api.vercel.com/v10/projects/{project}/env",
        data=json.dumps({
            "key": "SUPABASE_URL",
            "value": supabase_url,
            "type": "plain",
            "target": ["preview"],
            "gitBranch": branch_name,
        }).encode(),
        method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            print(f"twin: Vercel env SUPABASE_URL set for preview branch {branch_name}")
            return True
    except urllib.error.HTTPError as e:
        print(f"twin: Vercel env update failed ({e.code}: {e.read().decode()[:200]})")
        return False


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "create" and len(sys.argv) > 2:
        print(create(sys.argv[2]))
    elif cmd == "delete" and len(sys.argv) > 2:
        delete(sys.argv[2])
    elif cmd == "list":
        for b in list_pr_branches():
            print(b)
    else:
        print("usage: supabase_twin.py create <pr_number> | delete <pr_number> | list")

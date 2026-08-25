#!/usr/bin/env python3
"""
secrets_manager.py - resolves credentials for the runner WITHOUT ever storing the value in
the database or logs. Supabase only holds a REFERENCE (which store + key name); the actual
value is read from a real secret store at run time and injected into the task env.

Supported stores (set per secret in the `secrets` table .store):
  env        -> os.environ[ref]
  keychain   -> macOS: security find-generic-password -s <ref> -w
  doppler    -> doppler secrets get <ref> --plain
  onepassword-> op read <ref>            (1Password CLI)
Values are never printed; resolve() returns them only for direct env injection.
"""
import os, sys, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db


def register(provider, name, ref, store="env", project=None, scope="runner"):
    """Record a REFERENCE (not a value). The value must already live in the chosen store."""
    db.insert("secrets", {"provider": provider, "name": name, "ref": ref, "store": store,
                          "project": project, "scope": scope, "status": "active"}, upsert=True)


def _read(store, ref):
    """Read a secret value from the backing store. stderr is suppressed to prevent
    secret material from leaking into logs via error messages."""
    try:
        if store == "env":
            return os.environ.get(ref)
        if store == "keychain":
            return subprocess.check_output(["security", "find-generic-password", "-s", ref, "-w"],
                                           text=True, stderr=subprocess.DEVNULL).strip()
        if store == "doppler":
            return subprocess.check_output(["doppler", "secrets", "get", ref, "--plain"],
                                           text=True, stderr=subprocess.DEVNULL).strip()
        if store == "onepassword":
            return subprocess.check_output(["op", "read", ref],
                                           text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return None
    return None


def resolve(provider, name, project=None):
    """Return the secret VALUE for injection, or None. Never logs it.

    Precedence is EXPLICIT and the fallback is None:

        1. the row registered to this exact project  (an override, and it must win)
        2. the row registered globally (project is None)
        3. nothing — fail closed

    The previous selection was a single filter followed by rows[0]:

        rows = [r for r in rows if r.get("project") in (project, None)] or rows
        return _read(rows[0]["store"], rows[0]["ref"])

    which had two defects, both reachable on the hot path (runner.py builds every task's
    env through inject_env/resolve, so this runs for every task the fleet starts):

      (a) No precedence. The project row and the global row BOTH satisfy
          `in (project, None)`, so rows[0] took whichever PostgREST happened to return
          first. A project override therefore applied or did not apply depending on row
          order — the same task could pick up the global credential on one run and the
          project one on the next, with nothing in the logs to say which.

      (b) `or rows` leaked ACROSS projects. When this project has no row and there is no
          global row either, the comprehension yields [] — which is falsy — and the
          fallback restored the ENTIRE unfiltered result set, including secrets
          registered to a DIFFERENT project. That value was then read out of the store
          and injected into this project's task env: one project's credential handed to
          another project's agent. A missing secret must be a missing secret.
    """
    q = {"select": "*", "provider": f"eq.{provider}", "name": f"eq.{name}", "status": "eq.active"}
    rows = db.select("secrets", q) or []
    row = None
    if project is not None:
        row = next((r for r in rows if r.get("project") == project), None)
    if row is None:
        row = next((r for r in rows if r.get("project") is None), None)
    if row is None:
        return None
    return _read(row.get("store"), row.get("ref"))


def inject_env(project):
    """Build an env dict of all active secrets scoped to a project (value never logged)."""
    env = {}
    rows = db.select("secrets", {"select": "*", "status": "eq.active"}) or []
    for r in rows:
        if r.get("project") not in (project, None):
            continue
        val = _read(r["store"], r["ref"])
        if val:
            env[r["name"]] = val
    return env


if __name__ == "__main__":
    print("secrets_manager: stores only references; values stay in env/keychain/doppler/1Password.")

#!/usr/bin/env python3
"""
vercel_diag.py — one-shot diagnostic: latest deployment status + real build-error text
for every Vercel project on the kalepasch1 team, plus the specific failed deployments
flagged in recent email notifications.

Run from anywhere with network access and a valid VERCEL_TOKEN, e.g.:
    python3 vercel_diag.py

It will look for VERCEL_TOKEN in (in order): $VERCEL_TOKEN env var, then
~/Documents/apparently/.env, then ~/Documents/beethoven/claude-orchestrator/.env
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

VBASE = "https://api.vercel.com"

CANDIDATE_ENV_FILES = [
    os.path.expanduser("~/Documents/apparently/.env"),
    os.path.expanduser("~/Documents/beethoven/claude-orchestrator/.env"),
    os.path.expanduser("~/claude-orchestrator/.env"),
]

# specific deployments flagged by email notifications worth checking directly
KNOWN_FAILED_DEPLOYS = {
    "pareto": "dpl_EwnAn3hCdhEhFinVdLBtv6aexTd6",
}

PROJECTS = ["tomorrow", "apparently", "smarter", "pareto", "2080", "galop", "hisanta",
            "darwn", "sustainable-barks", "claude-orchestrator", "web"]


def _load_token():
    tok = os.environ.get("VERCEL_TOKEN", "").strip()
    if tok:
        return tok
    for path in CANDIDATE_ENV_FILES:
        if os.path.isfile(path):
            for line in open(path):
                line = line.strip()
                if line.startswith("VERCEL_TOKEN="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def _get(tok, path, team=None):
    qs = {}
    if team:
        qs["teamId"] = team
    url = VBASE + path + ("?" + urllib.parse.urlencode(qs) if qs else "")
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"__error__": e.code, "__body__": e.read().decode()[:800]}


def _print_events(tok, deploy_id):
    ev = _get(tok, f"/v3/deployments/{deploy_id}/events")
    if isinstance(ev, dict) and ev.get("__error__"):
        print(f"    (events fetch failed: {ev['__error__']} {ev['__body__'][:200]})")
        return
    lines = ev if isinstance(ev, list) else ev.get("events") or []
    # keep only stderr/error-ish lines, last 30
    interesting = [l for l in lines if l.get("type") in ("stderr",) or "error" in json.dumps(l).lower()]
    show = interesting[-30:] if interesting else lines[-15:]
    for l in show:
        text = l.get("text") or l.get("payload", {}).get("text") or ""
        if text.strip():
            print("   ", text.rstrip()[:300])


def main():
    tok = _load_token()
    if not tok:
        print("No VERCEL_TOKEN found (checked env var + apparently/.env + claude-orchestrator/.env).")
        print("Set one: export VERCEL_TOKEN=... (from https://vercel.com/account/tokens)")
        return

    me = _get(tok, "/v2/user")
    if isinstance(me, dict) and me.get("__error__"):
        print(f"VERCEL_TOKEN rejected: {me['__error__']} {me['__body__'][:300]}")
        return
    print(f"Authenticated as: {(me.get('user') or {}).get('username') or (me.get('user') or {}).get('email')}\n")

    teams = _get(tok, "/v2/teams")
    team_id = None
    for t in (teams.get("teams") or []):
        if "kalepasch1" in (t.get("slug") or "") or "kalepasch1" in (t.get("name") or "").lower():
            team_id = t.get("id")
            print(f"Team match: {t.get('name')} ({t.get('slug')}) id={team_id}")
    print()

    print("=" * 70)
    print("LATEST DEPLOYMENT PER PROJECT")
    print("=" * 70)
    for proj in PROJECTS:
        data = _get(tok, "/v6/deployments", team=team_id)
        # filter client-side by name since /v6 doesn't take a name filter reliably across accounts
        qs = {"app": proj, "limit": "3"}
        if team_id:
            qs["teamId"] = team_id
        url = VBASE + "/v6/deployments?" + urllib.parse.urlencode(qs)
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            print(f"\n[{proj}] fetch failed: {e.code}")
            continue
        deps = data.get("deployments") or []
        if not deps:
            continue
        print(f"\n[{proj}]")
        for d in deps[:2]:
            state = d.get("state") or d.get("readyState")
            print(f"  {d.get('uid') or d.get('id')}  state={state}  target={d.get('target')}  created={d.get('created')}")
            if state in ("ERROR", "CANCELED", "FAILED"):
                _print_events(tok, d.get("uid") or d.get("id"))

    print("\n" + "=" * 70)
    print("KNOWN FAILED DEPLOYMENTS FROM EMAIL ALERTS")
    print("=" * 70)
    for proj, dep_id in KNOWN_FAILED_DEPLOYS.items():
        print(f"\n[{proj}] {dep_id}")
        info = _get(tok, f"/v13/deployments/{dep_id}", team=team_id)
        if isinstance(info, dict) and info.get("__error__"):
            print(f"  fetch failed: {info['__error__']} {info['__body__'][:300]}")
            continue
        print(f"  state={info.get('readyState')}  error={json.dumps(info.get('errorMessage') or info.get('error'))[:300]}")
        _print_events(tok, dep_id)


if __name__ == "__main__":
    main()

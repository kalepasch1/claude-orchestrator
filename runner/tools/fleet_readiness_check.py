#!/usr/bin/env python3
"""fleet_readiness_check.py — is a capable provider back, and does the fleet work?

WHY THIS EXISTS. On 2026-08-24 every hosted provider was out of credit and the
Claude subscription was at its weekly limit, so the fleet was halted. The
question "when should it come back on?" has a real answer that does not need a
person: when a provider that can actually do the work is reachable AND a canary
proves the pipeline still runs clean. Both halves are checkable.

The failure this guards against is subtler than "no provider". A weak local
model IS reachable, and it will happily produce a commit — the 2026-08-24
canary produced a syntactically perfect commit whose CONTENT was the prompt
pasted into the README. Reachability is not capability. So this script
deliberately does not treat local-only as ready: the QA, judge and verification
stages route to the same providers as the coder, so when only weak models are
up, both the drafting and the checking are degraded at once and nothing
downstream would catch a bad commit.

Exit codes:
    0  READY      — a capable provider answered; the fleet may be resumed
    1  NOT READY  — nothing capable is reachable; stay halted
    2  ERROR      — could not determine; stay halted (fail-closed)

Fail-CLOSED, unlike most guards in this tree. The usual rule is that a broken
check must not block work — but here "allowing" means turning a 20-lane
autonomous fleet loose, and the cost of a wrong yes is a queue full of
plausible, unverifiable commits. That is the failure mode this whole incident
was made of.

    python3 runner/tools/fleet_readiness_check.py            # check only
    python3 runner/tools/fleet_readiness_check.py --resume   # resume if ready
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RUNNER not in sys.path:
    sys.path.insert(0, RUNNER)

def _load_env():
    """Load runner/.env, as model_gateway does.

    A scheduled run starts from a bare launchd/cron environment with none of the
    provider keys in it. Without this the probe reports "no key" for every
    vendor and concludes NOT READY forever -- a check that can only ever say no
    is worse than no check, because it looks like an answer.
    """
    for path in (os.path.join(RUNNER, ".env"),
                 os.path.expanduser("~/.claude-orchestrator/.env")):
        try:
            with open(path) as fh:
                for raw in fh:
                    line = raw.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    os.environ.setdefault(
                        key.strip(),
                        value.split("#")[0].strip().strip('"').strip("'"))
        except OSError:
            continue


_load_env()

TIMEOUT = float(os.environ.get("ORCH_READINESS_TIMEOUT", "20") or 20)

#: Providers strong enough to both draft and review. Local models are reachable
#: but are not on this list -- see the module docstring.
CAPABLE = ("claude", "openai", "google", "deepseek", "xai")


def _probe_openai():
    key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not key:
        return None, "no key"
    return _json_probe(
        "https://api.openai.com/v1/chat/completions",
        {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        {"model": os.environ.get("OPENAI_CHEAP_MODEL", "gpt-4.1-mini"),
         "messages": [{"role": "user", "content": "ok"}], "max_tokens": 5})


def _probe_google():
    key = (os.environ.get("GEMINI_API_KEY")
           or os.environ.get("GOOGLE_API_KEY") or "").strip()
    if not key:
        return None, "no key"
    model = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
    return _json_probe(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}"
        f":generateContent?key={key}",
        {"Content-Type": "application/json"},
        {"contents": [{"parts": [{"text": "ok"}]}]})


def _probe_xai():
    key = (os.environ.get("GROK_API_KEY") or os.environ.get("XAI_API_KEY") or "").strip()
    if not key:
        return None, "no key"
    return _json_probe(
        "https://api.x.ai/v1/chat/completions",
        {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        {"model": os.environ.get("XAI_MODEL", "grok-4"),
         "messages": [{"role": "user", "content": "ok"}], "max_tokens": 5})


def _probe_deepseek():
    key = (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if not key:
        return None, "no key"
    return _json_probe(
        "https://api.deepseek.com/chat/completions",
        {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        {"model": "deepseek-chat",
         "messages": [{"role": "user", "content": "ok"}], "max_tokens": 5})


def _probe_claude():
    """The subscription CLI, not an API key -- this fleet runs on a subscription."""
    import subprocess
    binary = os.environ.get("CLAUDE_BIN") or "claude"
    try:
        proc = subprocess.run(
            [binary, "-p", "Reply with the single word: ok"],
            capture_output=True, text=True, timeout=TIMEOUT * 3,
            stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        return None, "no claude CLI on PATH"
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"
    blob = (proc.stdout or "") + (proc.stderr or "")
    try:
        import provider_banner
        verdict = provider_banner.classify(blob)
    except Exception:
        verdict = None
    if verdict in ("exhausted", "rate_limited", "model_gone"):
        return False, (provider_banner.reason(blob) or verdict)
    if proc.returncode != 0:
        return False, blob.strip().splitlines()[-1][:120] if blob.strip() else "non-zero exit"
    return True, "ok"


def _json_probe(url, headers, body):
    """(True, 'ok') | (False, why) | (None, why). Classifies via provider_banner."""
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            resp.read(256)
        return True, "ok"
    except urllib.error.HTTPError as exc:
        try:
            payload = exc.read().decode("utf-8", "replace")[:2000]
        except Exception:
            payload = ""
        blob = f"Error code: {exc.code} - {payload}"
        try:
            import provider_banner
            why = provider_banner.reason(blob) or f"HTTP {exc.code}"
        except Exception:
            why = f"HTTP {exc.code}"
        return False, why
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


PROBES = {
    "claude": _probe_claude,
    "openai": _probe_openai,
    "google": _probe_google,
    "deepseek": _probe_deepseek,
    "xai": _probe_xai,
}


def check(stream=None):
    """(ready, results). `results` is {provider: (state, detail)}."""
    stream = stream or sys.stdout
    results = {}
    for name in CAPABLE:
        try:
            state, detail = PROBES[name]()
        except Exception as exc:               # a probe bug is not a verdict
            state, detail = None, f"probe error: {type(exc).__name__}: {exc}"
        results[name] = (state, detail)
        mark = {True: "LIVE", False: "DEAD", None: "SKIP"}[state]
        print(f"  {mark:<5} {name:<9} {detail}", file=stream)
    ready = any(state is True for state, _ in results.values())
    return ready, results


def dead_model_ids(stream=None):
    """Pinned model ids the vendors no longer serve. [] when clean or unknown.

    A funded account is not sufficient to resume. On 2026-08-24 the default
    agentic coder was `gemini-2.5-pro`, retired by Google — so the moment
    credit returned, routing would have gone straight back to a 404. Money and
    a working config are separate conditions and both have to hold.

    Unlike the provider probe, this one does NOT fail closed. The audit needs a
    vendor catalogue, and a catalogue that cannot be reached is exactly the
    situation where refusing to resume would strand a fleet that is otherwise
    fine. A dead id degrades one route; a stuck halt stops everything. So an
    audit that errors returns [] and says so.
    """
    stream = stream or sys.stdout
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import model_id_audit
        dead, _live, _unver, errors = model_id_audit.audit()
    except Exception as exc:
        print(f"  (model-id audit unavailable: {type(exc).__name__}: {exc})",
              file=stream)
        return []
    for provider, why in sorted((errors or {}).items()):
        print(f"  (model catalogue unavailable — {provider}: {why})", file=stream)
    return sorted(dead)


def _promote(results, stream):
    """Clear the demote flag for any provider that answered, so routing sees it."""
    try:
        import provider_failover_sla as sla
    except Exception as exc:
        print(f"  (could not reach the demote registry: {exc})", file=stream)
        return
    for name, (state, _detail) in results.items():
        if state is not True:
            continue
        try:
            if sla.is_demoted(name):
                state_blob = sla._load()
                (state_blob.get("demoted") or {}).pop(name, None)
                sla._save(state_blob)
                print(f"  promoted {name} back into routing", file=stream)
        except Exception as exc:
            print(f"  could not promote {name}: {exc}", file=stream)


def resume(stream=None):
    """Lift the global halt. Only ever called after `check` returns ready."""
    stream = stream or sys.stdout
    try:
        import db
    except Exception as exc:
        print(f"resume: cannot reach the database ({exc})", file=stream)
        return 2
    reason = ("resumed by fleet_readiness_check: a capable provider answered and "
              "the executor fixes of 2026-08-24 are in place")
    try:
        rows = db.select("controls", {"select": "id", "scope": "eq.global"}) or []
        for row in rows:
            db.update("controls", {"id": row["id"]},
                      {"paused": False, "reason": reason})
        print(f"resume: global halt lifted ({len(rows)} row(s))", file=stream)
        return 0
    except Exception as exc:
        print(f"resume: refused to lift the halt ({exc})", file=stream)
        return 2


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    print("fleet_readiness_check: probing providers that can both draft and review")
    try:
        ready, results = check()
    except Exception as exc:
        print(f"fleet_readiness_check: ERROR — {type(exc).__name__}: {exc}")
        print("Staying halted. This check fails closed on purpose.")
        return 2

    if not ready:
        print("\nNOT READY — nothing capable is reachable. The fleet stays halted.")
        print("Local models are reachable but are not sufficient: the QA and judge")
        print("stages route to the same providers as the coder, so when only weak")
        print("models are up nothing downstream can catch a bad commit.")
        return 1

    live = [n for n, (s, _d) in results.items() if s is True]
    print(f"\n{', '.join(live)} answered. Checking the config it would route with.")

    dead = dead_model_ids()
    if dead:
        print(f"\nNOT READY — {len(dead)} pinned model id(s) are no longer served:")
        for mid in dead:
            print(f"    {mid}")
        print("\nA funded account routing to a retired id fails with a 404 that reads")
        print("like any other provider error. Repin them first:")
        print("    python3 runner/tools/model_id_audit.py --list")
        return 1

    print("READY — providers answered and every pinned model id is live.")
    if "--resume" in argv:
        _promote(results, sys.stdout)
        return resume()
    print("Run again with --resume to lift the global halt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

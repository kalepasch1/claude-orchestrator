#!/usr/bin/env python3
"""
action_drafter.py - turn every operator/credential to-do into "review + run one line". For each
pending action card without a draft, a CHEAP model (costless-first via model_policy) generates:
  * draft      - crisp, human "what to do" steps,
  * draft_cmd  - the single exact shell command when one exists (else empty),
  * executable - True ONLY if draft_cmd matches a SAFE, reversible allowlist (no secrets/payments/deletes).

So the cockpit shows the exact command pre-filled; safe ones get a guarded "Run for me" button.
Schedule every few minutes. Never runs anything — it only drafts.
"""
import os, sys, re, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

# Safe, reversible operator commands we allow one-click execution for.
# Criteria: idempotent, no data loss, no secret exposure, no billing side-effects.
# Everything not matching this allowlist stays manual-only in the cockpit.
SAFE_CMD = re.compile(r"^\s*(npx prisma migrate deploy|npx prisma generate|supabase db push|"
                      r"supabase migration up|vercel env pull|npm run (migrate|seed|build)|"
                      r"git pull --ff-only)\s*$", re.I)
# Never auto-run anything touching these keywords — force manual review regardless of
# whether the command otherwise matches SAFE_CMD.
UNSAFE = re.compile(r"(secret|token|api[_-]?key|password|delete|drop |rm -rf|payment|charge|"
                    r"transfer|prod.*delete|revoke|force)", re.I)

PROMPT = """You are drafting a precise operator runbook item from a task card. Reply with ONE JSON:
{"steps":"<=4 short imperative steps a developer can follow>","cmd":"<the single exact shell command
to accomplish it, or empty string if there is no single safe command>"}
Rules: cmd must be ONE line, non-interactive, reversible; NEVER put a secret/token/key value in cmd
(reference the env var name instead); if the task is provisioning a credential or a legal/registration
step, cmd MUST be empty. CARD TITLE: {title}
CONTEXT: {why}"""


def _draft_one(title, why):
    prompt = PROMPT.replace("{title}", (title or "")[:300]).replace("{why}", (why or "")[:600])
    try:
        import model_policy, model_gateway
        prov, model, _ = model_policy.choose("plan", agentic=False)
        r = model_gateway.complete(prov, model, prompt)
        m = re.search(r"\{.*\}", r.get("text") or "", re.S)
        d = json.loads(m.group(0)) if m else {}
    except Exception:
        d = {}
    steps = (d.get("steps") or "").strip()
    cmd = (d.get("cmd") or "").strip()
    executable = bool(cmd) and bool(SAFE_CMD.match(cmd)) and not UNSAFE.search(cmd) and not UNSAFE.search(title or "")
    return steps, cmd, executable


def run(limit=40):
    rows = db.select("approvals", {"select": "id,title,why,draft", "status": "eq.pending",
                                   "kind": "in.(secret,operator)", "limit": str(limit)}) or []
    drafted = 0
    for a in rows:
        if a.get("draft"):
            continue
        steps, cmd, execu = _draft_one(a.get("title"), a.get("why"))
        if not steps and not cmd:
            continue
        db.update("approvals", {"id": a["id"]},
                  {"draft": steps[:1500], "draft_cmd": cmd[:500], "executable": execu})
        drafted += 1
    print(f"action_drafter: drafted {drafted} action items ({len(rows)} scanned)")
    return drafted


if __name__ == "__main__":
    run()

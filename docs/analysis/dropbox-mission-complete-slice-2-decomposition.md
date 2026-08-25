# Decomposition — `dropbox-mission-complete-merge-and-deploy-the-full-slice-2`

Parent task: `dropbox-mission-complete-merge-and-deploy-the-full-slice-2` (state
`DECOMPOSED`, project `beethoven`).
Split authored by: `dropbox-mission-complete-merge-and-deploy-the-full-slice-2-split-the-build-task-`.

The parent is the "merge and deploy the full backlog to Vercel" mission, sliced to
its deploy-enablement half. It is untestable as a single unit because it mixes three
independent failure domains: **local runner configuration**, **credential resolution**,
and **the Vercel release path**. Each has its own owner module, its own failure
signature, and its own already-existing test surface — so each gets its own task with
an acceptance test that is a command, not a judgement call.

## Why three and not one

The parent failed repeatedly as a single task because a green result in any one domain
says nothing about the other two: `runner/.env` can be complete while every provider key
in it is expired, and every key can be live while `vercel.json` silently skips the build
(the `ignoreCommand`-exits-0 class of outage that `runner/vercel_config_guard.py` exists
to catch). Splitting makes each failure attributable.

---

## Sub-task 1 — `…-slice-2-env-loader`

**Scope.** `runner/.env` completeness and load order only. Reconcile `runner/.env`
against `runner/.env.example` and `runner/orchestrator.env.example`: every key present
in an example file must be present (possibly empty) in the loaded environment, and the
loader must fail loudly rather than silently yielding an empty string for a required key.
Touch `runner/env_during_import.py` and the loader it calls. Do **not** put secret values
in the repo — example files carry names, never values.

**Out of scope.** Whether the values are *valid* (sub-task 2), anything under `vercel.json`.

**Acceptance test.**

```bash
cd /Users/kpasch/Documents/beethoven/claude-orchestrator
python3 -m pytest runner/test_config_deploy_early.py -q
python3 - <<'PY'
import re, pathlib
ex = set()
for f in ("runner/.env.example", "runner/orchestrator.env.example"):
    for line in pathlib.Path(f).read_text().splitlines():
        m = re.match(r"^([A-Z0-9_]+)=", line.strip())
        if m: ex.add(m.group(1))
have = {re.match(r"^([A-Z0-9_]+)=", l.strip()).group(1)
        for l in pathlib.Path("runner/.env").read_text().splitlines()
        if re.match(r"^[A-Z0-9_]+=", l.strip())}
missing = sorted(ex - have)
assert not missing, f"keys in example but absent from runner/.env: {missing}"
print("env-loader OK")
PY
```

**Done when** both commands exit 0 and the second prints `env-loader OK`.

---

## Sub-task 2 — `…-slice-2-credential-resolution`

**Scope.** Credential *validity and resolution*, not presence. `runner/credential_broker.py`,
`runner/credential_auto_resolver.py`, `runner/provider_credentials.py`,
`runner/secrets_manager.py`. Every provider the scheduler can route to must either resolve
to a working credential or be marked unavailable in a way the router respects — a provider
that is out of credit must be *known* to be out of credit, not discovered mid-task.

Hard constraint, non-negotiable and pre-existing: **no credential value is ever read from
or written to `fleet_config`.** Those rows were purged in the 2026-08-02 plaintext-credential
incident and a DB guard rejects them. `git` uses the osxkeychain helper against each repo's
existing origin; the `vercel` CLI is already logged in. Ambient credentials are used as-is.

**Out of scope.** Adding new providers; anything that spends money.

**Acceptance test.**

```bash
cd /Users/kpasch/Documents/beethoven/claude-orchestrator
python3 -m pytest runner/test_account_pool_credential_rework.py \
                  runner/test_account_pool_secret_outcomes.py \
                  runner/test_secrets_integration_bottleneck.py -q
python3 - <<'PY'
import re, sys
sys.path.insert(0, "runner")
import db
pat = re.compile(r"(token|secret|api_key|_pat)", re.I)
bad = sorted(r["key"] for r in db.select_all("fleet_config", {"select": "key"})
             if pat.search(r["key"]))
assert not bad, f"credential-shaped keys must not live in fleet_config: {bad}"
print("credential-resolution OK")
PY
```

**Done when** the pytest run is green and the guard prints `credential-resolution OK`
(i.e. the incident regression has not returned).

---

## Sub-task 3 — `…-slice-2-vercel-release-path`

**Scope.** The contract between the committed tree and Vercel, for every project in
`runner/deployment_bindings.json`. Run `runner/vercel_config_guard.py` and fix what it
reports: uncommitted lockfile under `npm ci`, build inputs stripped by `.vercelignore`,
`vercel.json` referencing a missing `package.json` script, an `ignoreCommand` that exits 0
for the production branch (a *skip*, which Vercel records as a **success** — this is how
`illuminati` lost a day of production deploys with nothing alerting), and
`git.deploymentEnabled` mapping the production branch to `false`.

**Out of scope.** Triggering a deploy. Production is release-train-only; this task must
never invoke the Vercel CLI directly. It repairs configuration and lets
`runner/release_train.py` do the deploying.

**Acceptance test.**

```bash
cd /Users/kpasch/Documents/beethoven/claude-orchestrator
python3 runner/vercel_config_guard.py            # advisory sweep, all projects
python3 -m pytest runner/test_deploy_skip_guard.py -q
```

**Done when** the sweep reports zero `block`-severity violations across the bound
projects and `test_deploy_skip_guard.py` is green.

---

## Ordering

`1 → 2 → 3`. Sub-task 2 cannot be evaluated until the loader reliably surfaces the keys,
and sub-task 3's guard reads project bindings through the same configured environment.
Encode as `deps` on the child rows if they are enqueued.

## Enqueue note

These three are specified but **not inserted into `tasks`** by this run. The fleet is
under a Guardrail-8 halt (global `controls` pause since 2026-08-24, five open
`escalate`/`human-decision` records awaiting `operator_approved_at`), and adding rows to a
queue that is not draining would deepen the backlog this decomposition is meant to unblock.
Enqueue them when the halt lifts, using the slugs and `deps` above.

# chatgpt-bridge

Lands code from **no-network agent sessions** (ChatGPT code interpreter, any sandbox
without outbound internet) onto GitHub from this Mac.

## Why

ChatGPT's code-execution sandbox has no outbound network. `git push` and even DNS
resolution (`Could not resolve host: github.com`) fail there and always will — it is a
platform limitation, not a misconfiguration. So the sandbox produces a **patch**, and
this Mac does the pushing.

## The loop

1. In ChatGPT: make the changes, then `git diff > /mnt/data/<repo>--<slug>.patch`
   (or zip the changed files). Download it.
2. Save it to `~/Documents/chatgpt-dropbox/`.
3. Within 30 seconds it is on GitHub and registered with the orchestrator queue: new
   branch, PR/recovery task, and a macOS notification with the result.

## Naming

The repo is taken from the filename prefix:

```
tomorrow--fix-login-redirect.patch
claude-orchestrator--add-retry-backoff.patch
apparently--licensing-engine-guard.diff
```

Or from a header line inside the patch:

```
# repo: tomorrow
# message: fix: login redirect loop on Safari
```

Known repos come from `runner/deployment_bindings.json`, including Apparently,
Apparently Law, Beethoven/Madeus, Tomorrow, Smarter, Illuminati, Vigil, Darwn,
Pareto 2080, Racefeed, HiSanta, Sustainable Barks, kalepasch.com, and PMI. Common
legacy aliases (`claude-orchestrator`, `2080`, `hisanta`, `galop`, `pasch`, `pmi`,
`trojun`) resolve to their canonical app names.

## Guarantees

- Work happens in an isolated worktree `{repo}-wt/<slug>` — never a `git checkout`
  in the main repo, per the orchestrator worktree convention (`sentinel.py`).
- Every commit is authored `kalepasch1 <kalepasch@gmail.com>`; the author is verified
  and rewritten if wrong, because Vercel blocks production deploys from other authors.
- Branch + PR by default. Nothing reaches a production branch without a merge.
- A patch that does not apply cleanly fails loudly into `_failed/` with the error —
  the worktree and branch are torn down, nothing partial is pushed, and the preserved
  artifact is registered as an orchestrator recovery task.
- A successful patch is also registered with orchestrator intake so its PR cannot exist
  outside the improvement queue.
- Every 30 minutes a read-only audit checks registered repos, attached worktrees,
  local-only commits, stashes, rescue refs, Codex session workspaces, output bundles,
  and bridge failures. Stable evidence older than six hours becomes an idempotent
  reconciliation task; active/fresh edits are left alone and caught by a later sweep.

## Manual use

```bash
chatgpt-patch ~/Downloads/tomorrow--thing.patch          # branch + PR
chatgpt-patch file.patch --repo tomorrow --branch fix/x  # explicit
chatgpt-patch file.patch --no-pr                         # push branch only
chatgpt-patch file.patch --push-to-default               # straight to main (careful)
```

## Files

| File | Role |
|------|------|
| `apply-patch.sh` | Core: resolve repo → worktree → apply → commit → push → PR |
| `watch-dropbox.sh` | One sweep of the drop-box; run by launchd every 30s |
| `local_build_audit.py` | Reconcile bridge + Codex/local git residue into queue intake |
| `install.sh` | Idempotent setup: drop-box, `~/bin/chatgpt-patch`, launchd agent |
| `deploy-to-repos.sh` | Installs `CHATGPT.md` + `chatgpt-patch.yml` into every repo |
| `chatgpt-patch.workflow.yml` | Source of the browser-fallback workflow |
| `CHATGPT.template.md` | Source of the per-repo agent instructions |

launchd label: `com.claudeorchestrator.chatgptbridge`
Logs: `~/Documents/chatgpt-dropbox/_logs/bridge.log`

### Legacy/deep audit

Run an immediate, all-history local snapshot (the scanner never resets or deletes source):

```bash
python3 tools/chatgpt-bridge/local_build_audit.py --force --stale-hours 0 \
  --report ~/Documents/chatgpt-dropbox/_logs/local-build-audit.md
```

Queue slugs include a content fingerprint, and the scanner keeps a local registry at
`_logs/local-build-audit.json`, so unchanged evidence is never enqueued twice.

### Why it runs through ClaudeRunner.app, and how it tells you when that breaks

launchd cannot execute or even read files under `~/Documents` — macOS TCC denies it
(`Operation not permitted`), and both the scripts and the repos live there. So the
agent invokes `ClaudeRunner.app`, the bundle that already holds this fleet's Full Disk
Access grant, exactly as the other orchestrator agents do. Its launcher accepts a `.sh`
job path relative to the repo root.

The dangerous part is what happens if that grant is lost: the watcher can neither run
**nor report** it, because the script itself becomes unreadable. Patches would sit in
the drop-box looking accepted while nothing shipped. Two things prevent that:

- **`watchdog.sh`** runs from its own launchd agent every 5 minutes and lives at
  `~/Library/Application Support/chatgpt-bridge/` — deliberately outside `~/Documents`,
  so it stays readable when the grant is gone. The heartbeat it reads is at
  `~/Library/Logs/claude-orchestrator/chatgpt-bridge.heartbeat` for the same reason.
  No sweep for 10 minutes ⇒ a notification, rate-limited to hourly.
- **`install.sh`** proves the whole chain before declaring success: it clears the
  heartbeat, kickstarts the agent, and waits for a real sweep. If none arrives it tells
  you exactly which grant to restore and exits non-zero.

To recover: System Settings → Privacy & Security → Full Disk Access → add
`ClaudeRunner.app`, then re-run `install.sh`. `chatgpt-patch <file>` from a terminal
keeps working throughout — a terminal has its own access.

### Production branches

`--push-to-default` (and `deploy-to-repos.sh --direct`) detect `production_push_guard`
and refuse or fall back to a PR. The guard requires a green release-train proof for the
exact commit, so a direct push is guaranteed to be rejected there. The bridge does not
route around it.

## Fallback without this Mac

Every repo also has `.github/workflows/chatgpt-patch.yml` — a `workflow_dispatch`
that accepts a base64 patch pasted straight into the GitHub web UI. Same guarantees,
runs on GitHub's runners. See `CHATGPT.md` in each repo.

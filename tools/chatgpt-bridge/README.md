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
3. Within 30 seconds it is on GitHub: new branch, PR opened, macOS notification with
   the link.

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

Known repos: `claude-orchestrator`, `tomorrow`, `apparently`, `smarter`,
`illuminati`, `vigil`, `2080`.

## Guarantees

- Work happens in an isolated worktree `{repo}-wt/<slug>` — never a `git checkout`
  in the main repo, per the orchestrator worktree convention (`sentinel.py`).
- Every commit is authored `kalepasch1 <kalepasch@gmail.com>`; the author is verified
  and rewritten if wrong, because Vercel blocks production deploys from other authors.
- Branch + PR by default. Nothing reaches a production branch without a merge.
- A patch that does not apply cleanly fails loudly into `_failed/` with the error —
  the worktree and branch are torn down, nothing partial is pushed.

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
| `install.sh` | Idempotent setup: drop-box, `~/bin/chatgpt-patch`, launchd agent |
| `deploy-to-repos.sh` | Installs `CHATGPT.md` + `chatgpt-patch.yml` into every repo |
| `chatgpt-patch.workflow.yml` | Source of the browser-fallback workflow |
| `CHATGPT.template.md` | Source of the per-repo agent instructions |

launchd label: `com.claudeorchestrator.chatgptbridge`
Logs: `~/Documents/chatgpt-dropbox/_logs/bridge.log`

### Why it runs through ClaudeRunner.app

launchd cannot execute or even read files under `~/Documents` — macOS TCC denies it
(`Operation not permitted`), and both the scripts and the repos live there. So the
agent invokes `ClaudeRunner.app`, the bundle that already holds this fleet's Full Disk
Access grant, exactly as the other orchestrator agents do. Its launcher accepts a `.sh`
job path relative to the repo root.

If the watcher silently stops firing, check `_logs/launchd.err.log` for
`Operation not permitted` — that means the FDA grant on ClaudeRunner.app was lost
(System Settings → Privacy & Security → Full Disk Access).

## Fallback without this Mac

Every repo also has `.github/workflows/chatgpt-patch.yml` — a `workflow_dispatch`
that accepts a base64 patch pasted straight into the GitHub web UI. Same guarantees,
runs on GitHub's runners. See `CHATGPT.md` in each repo.

# Working on this repo from ChatGPT (or any no-network sandbox)

**Read this before attempting `git push`.**

ChatGPT's code-execution sandbox has **no outbound network**. `git push`, `git fetch`,
`gh`, `pip install`, and even DNS resolution fail there:

```
fatal: unable to access 'https://github.com/...': Could not resolve host: github.com
```

This is a platform limitation of the sandbox, not a misconfiguration of this repo.
It cannot be fixed with a token, a remote URL change, a proxy, or a retry. **Do not
spend turns debugging it, and do not report the work as blocked.**

## What to do instead

Finish the work, then emit a patch as the deliverable.

```bash
# stage everything you changed (including new files)
git add -A

# write the handoff patch
{
  echo "# repo: claude-orchestrator"
  echo "# message: <conventional commit message>"
  echo
  git diff --cached
} > /mnt/data/claude-orchestrator--<short-slug>.patch
```

Then tell the user, in one line:

> Done — download `claude-orchestrator--<slug>.patch` and drop it in `~/Documents/chatgpt-dropbox/`.

No git clone in the session? Zip the changed files instead, preserving paths from the
repo root, and name it `claude-orchestrator--<slug>.zip`. The bridge accepts
`.patch`, `.diff`, `.zip`, `.tar.gz`.

## What happens after the user drops the file

A launchd agent on their Mac picks it up within 30 seconds and:

1. creates an isolated worktree off the default branch (never touches the main checkout),
2. applies the patch,
3. commits it authored `kalepasch1 <kalepasch@gmail.com>` — **required**, Vercel blocks
   production deploys authored by anyone else,
4. pushes a `chatgpt/<slug>` branch and opens a PR,
5. notifies with the PR link.

Nothing reaches a production branch without a human merge. If the patch does not apply
cleanly it lands in `_failed/` with the exact error — so keep patches small, scoped, and
based on current `origin/HEAD`.

## Away from that Mac

The same patch can be applied from a browser: repo → **Actions** → **Apply ChatGPT
patch** → *Run workflow*, paste `git diff | base64 | tr -d '\n'`. Same author rule, same
PR-only guarantee.

## Rules that still apply in a sandbox session

- Commit author is always `kalepasch1 <kalepasch@gmail.com>`.
- Keep a patch to one logical change. One patch, one PR.
- Never put secrets, `.env` contents, or tokens in a patch.
- Base the patch on the current default branch, not on a stale local state.

Bridge source and README: `claude-orchestrator/tools/chatgpt-bridge/`.

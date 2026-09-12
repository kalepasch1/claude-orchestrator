## Branch flow (enforced — read before pushing anything)

**Every project in this fleet promotes production from `orchestrator/dev`. Nothing
is pushed to `main`/`master` directly.**

    feature branch  ->  orchestrator/dev  ->  main / master  ->  Vercel

Develop wherever you like — `agent/*`, `feat/*`, a worktree, another machine. But
the change has to land on `orchestrator/dev` before it can reach production, and
that merge is where conflicts get resolved. Resolving them there is the whole
point: it is the one place every in-flight change meets, so the better side can be
kept deliberately instead of whichever branch happened to push last winning by
accident.

`production_push_guard.py` refuses a push to `main`/`master` whose commit is not
contained in `origin/orchestrator/dev`, and prints the four commands that fix it.
The rule is structural and runs before the build and test gates, because a green
build and a green suite say nothing about whether the tree was integrated.

    git fetch origin
    git checkout -B orchestrator/dev origin/orchestrator/dev
    git merge <your-sha>        # resolve conflicts HERE, keeping the better side
    git push origin HEAD:refs/heads/orchestrator/dev
    git push origin <new-dev-sha>:refs/heads/main

Two escape hatches exist and they are deliberately separate switches, so reaching
for one never silently waives the others:

| switch | waives |
|---|---|
| `ORCH_ALLOW_DIRECT_PROD_PUSH=1` | the integration rule above |
| `ORCH_ALLOW_UNVERIFIED_PROD_PUSH=1` | the green-build requirement |
| `ORCH_ALLOW_RED_TESTS=1` | the green-suite requirement |

A repo whose remote has no `orchestrator/dev` is not held to the rule. Set
`ORCH_STAGING_BRANCH` if a project integrates somewhere else.

The guard only reaches a repo whose `core.hooksPath` points at
`runner/hooks`. After cloning:

    git config core.hooksPath /Users/kpasch/Documents/beethoven/claude-orchestrator/runner/hooks


## Git identity (required — read before committing)

All commits in this repo MUST be authored as the repo owner:

    git config user.name "kalepasch1"
    git config user.email "kalepasch@gmail.com"

Run this immediately after cloning, before your first commit. Vercel blocks
production deployments whose commit author is anyone else — commits authored
as e.g. mandyjustinepasch@gmail.com or kale@heretomorrow.us end up in BLOCKED
state and never deploy. Do not use your platform account identity.

## No-network agent sessions (ChatGPT sandbox)

ChatGPT's code sandbox has no outbound network — `git push` and DNS always fail
there. Do not debug it. Emit a patch instead: see [CHATGPT.md](./CHATGPT.md).

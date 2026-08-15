# launchd PATH diagnostic — do node/npm/expo resolve for the orchestrator runner?

**Date:** 2026-08-06
**Task:** `toolchain-diagnose-launchd-path-cowork-20260806`
**Mode:** READ-ONLY. No files outside this report were changed, nothing was
installed, no launchd config was modified.

---

## VERDICT

**VERDICT: CONFIRMED — node, npm, npx, vercel and expo are all NOT resolvable
under the PATH that launchd hands the orchestrator jobs, while every one of them
(except `expo`, see below) resolves fine in the interactive shell.**

Two independent defects, both real:

1. **`launchctl getenv PATH` is EMPTY**, so any job without an explicit
   `EnvironmentVariables:PATH` falls back to the launchd default
   `/usr/bin:/bin:/usr/sbin:/sbin`. `com.claudeorchestrator.runner.plist` — the
   main runner — has **no `EnvironmentVariables` key at all**. It is running
   blind on the 4-entry default PATH.
2. **`/usr/local/bin` is empty of Node tooling on this machine.** Node is
   Homebrew-on-Apple-Silicon, i.e. `/opt/homebrew/bin`. Seven plists specify
   `PATH = /usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin` — which for
   node/npm/npx/vercel purposes is *identical to the broken default*. Two of
   those seven (`overnight-deploy`, `research-window`) are the plists that
   execute `runner.py`, i.e. the ones that run the QA/build gate.

`expo` is a separate, additional problem: it is not installed globally anywhere
(not Homebrew, not nvm). It exists only as a per-repo binary in
`racefeed/node_modules/.bin/expo`, reachable solely through `npm run` / `npx` —
both of which need `npm` on PATH first. So the `sh: expo: command not found`
class of failure is downstream of defect (1)/(2), not independent of it.

---

## Evidence, verbatim

### 1. `echo $PATH` (interactive / login shell — identical output for both)

```
/usr/local/bin:/System/Cryptexes/App/usr/bin:/usr/bin:/bin:/usr/sbin:/sbin:/var/run/com.apple.security.cryptexd/codex.system/bootstrap/usr/local/bin:/var/run/com.apple.security.cryptexd/codex.system/bootstrap/usr/bin:/var/run/com.apple.security.cryptexd/codex.system/bootstrap/usr/appleinternal/bin:/pkg/env/global/bin:/Library/Apple/usr/bin:/opt/homebrew/bin:/Users/kpasch/.nvm/versions/node/v22.23.1/bin:/opt/homebrew/sbin:/Users/kpasch/.local/bin:/Users/kpasch/Library/pnpm:/Users/kpasch/bin:/Users/kpasch/.local/bin
```

### 2. `launchctl getenv PATH`

```
(no output — exit status 0)
```

**EMPTY.** This is the load-bearing finding. A launchd job with no
`EnvironmentVariables:PATH` therefore gets the hardcoded fallback
`/usr/bin:/bin:/usr/sbin:/sbin`.

### 3. `command -v <tool>` + version, interactive shell

| tool | resolved path | version |
|---|---|---|
| `node` | `/opt/homebrew/bin/node` | `v25.8.1` |
| `npm` | `/opt/homebrew/bin/npm` | `11.11.0` |
| `npx` | `/opt/homebrew/bin/npx` | `11.11.0` |
| `expo` | **NOT FOUND** | — |
| `vercel` | `/opt/homebrew/bin/vercel` | `Vercel CLI 58.7.1` |

`/opt/homebrew/bin/node` is a symlink → `../Cellar/node/25.8.1_1/bin/node`.
`/usr/local/bin/node` **does not exist** (`ls: No such file or directory`).

### 4. Resolvability under the launchd fallback PATH `/usr/bin:/bin:/usr/sbin:/sbin`

| tool | result |
|---|---|
| `node` | **NOT-RESOLVABLE** |
| `npm` | **NOT-RESOLVABLE** |
| `npx` | **NOT-RESOLVABLE** |
| `expo` | **NOT-RESOLVABLE** |
| `vercel` | **NOT-RESOLVABLE** |

All five. Because `/usr/local/bin` holds no Node tooling either, the same table
holds verbatim for the seven plists that declare
`PATH = /usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin`.

### 5. `launchctl list | grep -iE "claude|orchestrator"`

```
-	0	com.claudeorchestrator.research-window
-	0	com.claudeorchestrator.self-review
-	0	com.claudeorchestrator.overnight-deploy
-	0	com.claudeorchestrator.commonbrain
-	0	com.claudeorchestrator.demand
-	0	com.claudeorchestrator.chatgptbridge
-	0	com.claudeorchestrator.batch
98618	0	com.claudeorchestrator.medic
-	0	com.anthropic.claudefordesktop.ShipIt
-	0	com.claudeorchestrator.roi
-	0	com.claudeorchestrator.maturity
75984	0	application.com.anthropic.claudefordesktop.1742040540.1742040546
86230	143	com.claudeorchestrator.runner
-	0	com.claudeorchestrator.scout
-	0	com.claudeorchestrator.agentmarket
-	0	com.claudeorchestrator.radar
-	0	com.claudeorchestrator.chatgptbridge.watchdog
-	0	com.claudeorchestrator.txn
-	0	com.claudeorchestrator.deploy
-	0	com.claudeorchestrator.anomaly
-	0	com.claudeorchestrator.modelscout
-	0	com.claudeorchestrator.chaos
-	0	com.claudeorchestrator.spec
-	0	com.claudeorchestrator.sentinel
-	0	com.claudeorchestrator.editorial
```

Side observation, not part of the PATH question: `com.claudeorchestrator.runner`
shows last exit status **143** (SIGTERM).

### 6. `ls -la ~/Library/LaunchAgents/ | grep -iE "claude|orchestrator"`

24 active `com.claudeorchestrator.*.plist` files plus two disabled
(`com.claudeorchestrator.daily-report.plist.disabled`,
`com.orchestrator.runner.plist.disabled`). Full listing captured; the relevant
per-plist detail is table 7 below.

### 7. Per-plist `EnvironmentVariables:PATH`

Every job runs `/Applications/ClaudeRunner.app/Contents/MacOS/ClaudeRunner`
with the module name as `argv[1]` (except `chatgptbridge.watchdog`, which runs
`/bin/bash …/watchdog.sh` directly).

| plist | declared PATH | node/npm resolvable? |
|---|---|---|
| `runner` | **no `EnvironmentVariables` key** | ❌ falls back to launchd default |
| `overnight-deploy` | `/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin` | ❌ |
| `research-window` | `/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin` | ❌ |
| `self-review` | `/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin` | ❌ |
| `anomaly` | `/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin` | ❌ |
| `demand` | `/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin` | ❌ |
| `maturity` | `/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin` | ❌ |
| `radar` | `/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin` | ❌ |
| `chatgptbridge.watchdog` | `EnvironmentVariables` present but **no PATH key** | ❌ |
| `agentmarket` | `/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin` | ✅ |
| `batch` | `/opt/homebrew/bin:…` | ✅ |
| `chaos` | `/opt/homebrew/bin:…` | ✅ |
| `chatgptbridge` | `/opt/homebrew/bin:…` | ✅ |
| `commonbrain` | `/opt/homebrew/bin:…` | ✅ |
| `deploy` | `/opt/homebrew/bin:…` | ✅ |
| `editorial` | `/opt/homebrew/bin:…` | ✅ |
| `medic` | `/opt/homebrew/bin:…` | ✅ |
| `modelscout` | `/opt/homebrew/bin:…` | ✅ |
| `roi` | `/opt/homebrew/bin:…` | ✅ |
| `scout` | `/opt/homebrew/bin:…` | ✅ |
| `sentinel` | `/opt/homebrew/bin:…` | ✅ |
| `spec` | `/opt/homebrew/bin:…` | ✅ |
| `txn` | `/opt/homebrew/bin:…` | ✅ |

**9 of 24 jobs are broken. The two that run `runner.py` — `overnight-deploy` and
`research-window` — are both in the broken set, as is `runner` itself.** That is
precisely the population that executes the build/QA gate, which matches the
reported failure distribution (467 "command not found", 353 npm/dependency
prewarm, 281 build-red ≈ 30% of 3,630 failed releases).

### 8. Node version managers present

- `~/.nvm` — **PRESENT**, one version: `v22.23.1`
- `~/.volta` — absent
- `~/.asdf` — absent
- Homebrew — **PRESENT**, `brew --prefix` = `/opt/homebrew`

Authoritative `node` in the interactive shell is the Homebrew one (`v25.8.1`),
because `/opt/homebrew/bin` precedes the nvm dir on PATH.

### 9. `node_modules` and build/test first-binary resolution

**beethoven** (`/Users/kpasch/Documents/beethoven/claude-orchestrator`):
`node_modules` **MISSING**. Its only script is
`test: python3 -m pytest runner/tests/ -x --tb=short -q 2>&1 || true` — pure
Python, so beethoven itself needs no Node. It is unaffected by this defect.

Sibling app repos — all have `node_modules`:

| repo | script | first binary | in `node_modules/.bin`? |
|---|---|---|---|
| tomorrow | `test: npx vitest run` | `npx` | no — needs PATH |
| tomorrow | `build: NODE_OPTIONS=… node scripts/check` | `node` (after env prefix) | no — needs PATH |
| apparently | `build: nuxt build` / `test: vitest run` | `nuxt` / `vitest` | ✅ in `.bin` |
| smarter | `build: nuxt build` / `test: vitest run` | `nuxt` / `vitest` | ✅ in `.bin` |
| darwn | `build: nuxt build` / `test: vitest run` | `nuxt` / `vitest` | ✅ in `.bin` |
| Sustainable_Barks | `build: nuxt build` | `nuxt` | ✅ in `.bin` |
| Sustainable_Barks | `test: npm run typecheck` | `npm` | no — needs PATH |
| pareto-2080 | `build: npm rebuild … && npx prisma generate` | `npm` | no — needs PATH |
| pareto-2080 | `test: node scripts/lint-esm.mjs && node --test …` | `node` | no — needs PATH |
| racefeed | `build: expo export --platform web && node tools/…` | `expo` | ✅ in `.bin` |
| racefeed | `test: node --test 'lib/**/*.test.ts'` | `node` | no — needs PATH |
| hisanta | `build: npm run build:web` | `npm` | no — needs PATH |
| hisanta | `test: node --test 'lib/__tests__/*.test.ts'` | `node` | no — needs PATH |

The `.bin` entries only help when invoked through `npm run`/`npx`, which
prepend `node_modules/.bin` — and that still requires `npm`/`npx` itself on
PATH. Under the broken PATH nothing in the table is reachable.

This also explains the `sh: expo: command not found` signature exactly:
`racefeed`'s `expo` **is** present at `node_modules/.bin/expo`, so the failure
is not a missing dependency — it is `npm` never resolving, so `.bin` is never
prepended, so `expo` is looked up on the bare launchd PATH and missed.

---

## RECOMMENDED-PATH

```
/opt/homebrew/bin:/opt/homebrew/sbin:/Users/kpasch/.nvm/versions/node/v22.23.1/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
```

Built from where the binaries actually are: `node`, `npm`, `npx`, `vercel` and
`brew` all live in `/opt/homebrew/bin`; `/opt/homebrew/sbin` is on the
interactive PATH; the nvm dir is included as a fallback and is deliberately
placed *after* Homebrew so the authoritative `node v25.8.1` keeps winning, as it
does interactively. `/usr/local/bin` is retained last for any non-Node tooling
that may land there later. `expo` is intentionally not addressed by PATH — see
the caveat below.

### Plists that would need `EnvironmentVariables:PATH` set to the above

Highest priority first (the first three are the ones running the QA/build gate):

1. `~/Library/LaunchAgents/com.claudeorchestrator.runner.plist` — **add the
   whole `EnvironmentVariables` dict; it currently has none**
2. `~/Library/LaunchAgents/com.claudeorchestrator.overnight-deploy.plist`
3. `~/Library/LaunchAgents/com.claudeorchestrator.research-window.plist`
4. `~/Library/LaunchAgents/com.claudeorchestrator.self-review.plist`
5. `~/Library/LaunchAgents/com.claudeorchestrator.anomaly.plist`
6. `~/Library/LaunchAgents/com.claudeorchestrator.demand.plist`
7. `~/Library/LaunchAgents/com.claudeorchestrator.maturity.plist`
8. `~/Library/LaunchAgents/com.claudeorchestrator.radar.plist`
9. `~/Library/LaunchAgents/com.claudeorchestrator.chatgptbridge.watchdog.plist`
   — has an `EnvironmentVariables` dict but no `PATH` key

The 15 plists already carrying `/opt/homebrew/bin:…` are fine as-is; normalising
them to the recommended string is optional tidy-up, not a fix.

A belt-and-braces alternative to editing nine files is
`launchctl config user path "<RECOMMENDED-PATH>"`, which sets the domain-wide
default that `launchctl getenv PATH` currently reports as empty. It requires
sudo and a reboot to take effect, and it does **not** override a plist that
declares its own wrong `PATH` — so items 2–8 above would still need editing.
Editing the plists is the more surgical option.

### Caveat — `expo` is a genuinely missing global

Fixing PATH makes `npm`/`npx` resolve, which makes `racefeed`'s
`node_modules/.bin/expo` reachable through `npm run build`. That is expected to
clear the `sh: expo: command not found` failures. If any job invokes `expo`
*directly* rather than via `npm run`/`npx`, PATH alone will not fix it and a
global install (`npm i -g expo` or use of `npx expo`) would additionally be
needed. Worth re-measuring after the PATH change rather than pre-emptively
installing.

### Not addressed here

`com.claudeorchestrator.runner` last exited **143 (SIGTERM)**. That is a separate
signal from the PATH defect and is out of scope for this diagnostic.

---

## Applying the fix

Deliberately **not applied**, per the task instruction. The operator asked to
read the diagnosis before anything on the machine changes. A follow-up task
should carry out the nine plist edits plus `launchctl unload`/`load` (or
`bootout`/`bootstrap`) for each, then confirm with
`launchctl print gui/$(id -u)/com.claudeorchestrator.runner | grep -A2 PATH`.

# Recovery: unregistered checkouts `darwinLife` and `vinci`

Audit fingerprint: `165f6c7173b5d94520d186103651ae1146b51ab0aa61065abc4676767b5e5fa4`
Source: `tools/reconcile_unregistered_repos.py`, classification `RECOVERABLE_VALUE`.
Both source checkouts were treated as READ-ONLY. Nothing was deleted, reset,
cleaned or moved in either one.

## 1. `/Users/kpasch/Documents/darwinLife` — RECOVERED, landed

**What it is.** A second checkout of the registered `darwn` project
(`github.com/kalepasch1/darwn.git`). The registered checkout at
`/Users/kpasch/Documents/darwn/darwn` sits on `master`; this one sits on
`main`, and its HEAD (`1643c0a`) is contained in `origin/main`. The two
checkouts are therefore on *different branches of the same repo*, which is why
the reconciler saw it as a separate tree.

**Uncommitted state.** Two paths: `package.json` and `package-lock.json`.

| change | verdict |
|---|---|
| `package.json`: add `cheerio ^1.0.0-rc.12`, `puppeteer ^21.6.1` to `dependencies` | **real** |
| `package-lock.json`: corresponding dependency tree | real but diverged (see below) |
| `package-lock.json`: `"name"` rewritten to `"darwinLife"` | **tool noise** — npm rewrites `name` from the containing directory |

The dependency additions are genuine and load-bearing: six committed files
under `scripts/scrape-attorneys/` already `import` puppeteer and cheerio —

```
scripts/scrape-attorneys/scrapers/base-scraper.ts
scripts/scrape-attorneys/scrapers/california.ts
scripts/scrape-attorneys/scrapers/florida.ts
scripts/scrape-attorneys/scrapers/illinois.ts
scripts/scrape-attorneys/scrapers/new-york.ts
scripts/scrape-attorneys/scrapers/pennsylvania.ts
scripts/scrape-attorneys/scrapers/texas.ts
```

— while neither package was declared anywhere on `origin/main`. The scraper
track has been un-installable on a clean clone for as long as those files have
existed. That is exactly the kind of value the reconciler exists to catch.

**How it was landed.** A newly allocated isolated worktree of the correct repo,
`darwn-wt/remediate-recover-unregistered-repos-darwinlife-and-vinci-a39890`,
cut from `origin/main`, delivered as
`agent/remediate-recover-unregistered-repos-darwinlife-and-vinci-a39890` on
`kalepasch1/darwn` for merge-train pickup.

**Deliberate scope reduction: the lockfile was not transplanted.** The
`darwinLife` lockfile had drifted ~3.5k lines from `origin/main` (unrelated
`dev: true` flips across the tree) and carried the checkout-local `name`
rename. Copying it wholesale would have clobbered newer resolutions on `main`
to smuggle in two dependencies. The manifest change alone is the minimal
correct recovery; `npm install` regenerates the lock deterministically. If the
merge train wants a committed lock, regenerate it on `main` rather than
importing this one.

## 2. `/Users/kpasch/Documents/vinci` — REPORTED, not landed, **needs operator sign-off**

**What it is.** Origin `github.com/kalepasch1/vinci.git`, matching no
registered project. Entirely outside orchestrator coverage.

**Uncommitted state.** One path, `current-events/feed.md`: a hand-written
weekly research digest ("Week of 2026-08-12") — twelve sourced entries across
derivatives / gaming law / consumer finance / AI-ML / game design, each mapped
to specific curriculum weeks, plus an explicit note that the tax-law slot was
skipped rather than padded.

**Verdict: real, high-value, and human-authored.** This is editorial work, not
tool output. It is also the single most likely thing in the audit to be lost
silently, because nothing watches this repo.

**Not landed, by design.** The change belongs in `vinci` itself, and `vinci` is
unregistered; landing it would require either registering the project or
writing to a read-only source checkout. Both are out of scope for an
autonomous run.

**Recommendation — register `vinci` as a project.** It has a real origin, a
real working cadence, and content that is expensive to reconstruct. The
counter-argument is that it looks like a personal study repo rather than a
deployable product, and the fleet's value there is backup, not automation.
Either way the current state is the worst of both: unwatched *and* uncommitted.

**Minimum action even if registration is declined:** commit the feed entry in
`vinci` by hand. It is one file and it is finished work.

## Follow-ups for the operator

1. Sign off (or decline) registration of `kalepasch1/vinci`.
2. Decide whether `darwinLife` should keep existing as a second checkout of
   `darwn` on `main`. Two checkouts of one repo on two branches is how this
   drift happened, and `sentinel.py` does not watch the unregistered one.
3. If the `darwn` scraper track is live, regenerate `package-lock.json` on
   `main` after the dependency branch merges.

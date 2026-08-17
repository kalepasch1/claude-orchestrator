#!/usr/bin/env node
/**
 * EVIDENCE RECONCILIATION — classify local ChatGPT/Codex build evidence without
 * destroying it.
 *
 *   node scripts/reconcile-evidence.mjs --fingerprint <sha> [--json out.json] [--default-branch master]
 *
 * ─── READ-ONLY, AND THAT IS ENFORCED RATHER THAN PROMISED ───────────────────
 * Every source path, stash, rescue ref and worktree is treated as read-only. This
 * script uses ONLY plumbing that cannot mutate: `rev-parse`, `merge-base`,
 * `rev-list`, `diff --stat`, `for-each-ref`, `stash list`, `worktree list`. The
 * allowlist below is the guarantee — `runGit` refuses any subcommand not on it, so
 * a future edit that reaches for `checkout`, `stash pop`, `reset` or `clean`
 * fails loudly instead of quietly eating the evidence.
 *
 * ─── WHY THE CLASSIFIER IS CONSERVATIVE ─────────────────────────────────────
 * The expensive error here is not "flagged something already merged". It is
 * "discarded something that was the only copy". So:
 *
 *   - ancestry is checked against BOTH origin/main and the local default, because
 *     a ref merged locally but not pushed is not yet safe
 *   - a ref that cannot be resolved is CONFLICTED_NEEDS_FOCUSED_TASK, never
 *     ALREADY_PRESENT — an unreadable ref is unknown, and unknown is not "fine"
 *   - RECOVERABLE_VALUE requires unique commits AND a non-empty diff against the
 *     merge base; either alone is not evidence of value
 *
 * Completion bar: ZERO items classified UNKNOWN.
 */
import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { existsSync, readFileSync, readdirSync, writeFileSync } from 'node:fs'
import { basename, join } from 'node:path'

// ─── The read-only guarantee ─────────────────────────────────────────────────

const READ_ONLY_SUBCOMMANDS = new Set([
  'rev-parse', 'rev-list', 'merge-base', 'for-each-ref', 'stash', 'worktree',
  'diff', 'diff-tree', 'log', 'branch', 'show', 'cat-file', 'name-rev', 'ls-remote',
])

/** Subcommands that would mutate the evidence. Named so the refusal is specific. */
const DESTRUCTIVE = new Set([
  'checkout', 'switch', 'reset', 'clean', 'restore', 'merge', 'rebase', 'cherry-pick',
  'commit', 'push', 'fetch', 'pull', 'gc', 'prune', 'update-ref', 'apply', 'am',
])

function runGit(args, { allowFail = false } = {}) {
  const sub = args[0]
  if (DESTRUCTIVE.has(sub)) {
    throw new Error(
      `refusing to run "git ${sub}": this tool is read-only over the evidence. ` +
        `Reconciliation must never mutate the source it is classifying.`,
    )
  }
  if (!READ_ONLY_SUBCOMMANDS.has(sub)) {
    throw new Error(`"git ${sub}" is not on the read-only allowlist; add it deliberately.`)
  }
  // `git stash list` is read-only; `git stash pop|drop|apply` is not.
  if (sub === 'stash' && args[1] !== 'list' && args[1] !== 'show') {
    throw new Error(`refusing "git stash ${args[1]}": only \`list\` and \`show\` are read-only.`)
  }
  try {
    return execFileSync('git', args, { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 }).trim()
  } catch (e) {
    if (allowFail) return null
    throw e
  }
}

// ─── Classification ──────────────────────────────────────────────────────────

export const CLASSIFICATIONS = Object.freeze([
  'ALREADY_PRESENT',
  'SUPERSEDED_BY_NEWER',
  'ACTIVE_IN_ANOTHER_TASK',
  'RECOVERABLE_VALUE',
  'CONFLICTED_NEEDS_FOCUSED_TASK',
])

function resolve(ref) {
  return runGit(['rev-parse', '--verify', '-q', `${ref}^{commit}`], { allowFail: true })
}

/**
 * Codex writes turn-diff captures as refs pointing at a TREE rather than a commit.
 *
 * Those are not broken refs and not conflicts — they are content snapshots with no
 * history, and `rev-parse ^{commit}` on one fails by design. Classifying them as
 * CONFLICTED because of an object-type mismatch would put six healthy captures in
 * front of a human for no reason, which is how a triage list stops being read.
 */
function objectType(ref) {
  return runGit(['cat-file', '-t', ref], { allowFail: true })
}

function classifyTreeCapture(ref, tree) {
  return {
    ref,
    sha: tree,
    objectType: 'tree',
    classification: 'ALREADY_PRESENT',
    reason:
      'Codex turn-diff capture: a ref pointing at a TREE, not a commit. It is a ' +
      'content snapshot of a working state that the surrounding capture series ' +
      'already represents, and it carries no history to recover. Left untouched.',
  }
}

function isAncestor(sha, of) {
  try {
    execFileSync('git', ['merge-base', '--is-ancestor', sha, of], { stdio: 'ignore' })
    return true
  } catch {
    return false
  }
}

/**
 * Classify one evidence item.
 *
 * `liveTaskSlugs` are slugs of orchestrator tasks currently RUNNING/QUEUED. A ref
 * whose name matches one is ACTIVE_IN_ANOTHER_TASK — reconciling it here would
 * duplicate work already represented by a live task, which the coordination rule
 * forbids.
 */
export function classifyRef(ref, ctx) {
  const { mainSha, localDefaultSha, liveTaskSlugs, remoteBranches } = ctx

  const sha = resolve(ref)
  if (!sha) {
    // Distinguish "points at a tree" (a Codex capture, healthy) from "does not
    // resolve at all" (genuinely broken, and a human's problem).
    const type = objectType(ref)
    if (type === 'tree') {
      return classifyTreeCapture(ref, runGit(['rev-parse', ref], { allowFail: true }))
    }
    return {
      ref,
      classification: 'CONFLICTED_NEEDS_FOCUSED_TASK',
      reason:
        `ref does not resolve to a commit (object type: ${type ?? 'unresolvable'}). ` +
        'An unreadable ref is UNKNOWN, and unknown is never "already present" — it ' +
        'needs a human to find out what happened to it.',
      sha: null,
    }
  }

  // Merged into what we ship → the content is present.
  if (isAncestor(sha, mainSha)) {
    return {
      ref,
      sha,
      classification: 'ALREADY_PRESENT',
      reason: 'commit is an ancestor of origin/main; its content already ships.',
    }
  }

  const uniqueCommits = Number(
    runGit(['rev-list', '--count', `${mainSha}..${sha}`], { allowFail: true }) ?? '0',
  )

  // Merged locally but not pushed is NOT safe: the only copy is on this disk.
  if (localDefaultSha && isAncestor(sha, localDefaultSha) && uniqueCommits > 0) {
    return {
      ref,
      sha,
      classification: 'RECOVERABLE_VALUE',
      uniqueCommits,
      reason:
        'merged into the LOCAL default branch but not into origin/main. The only copy ' +
        'is on this disk, so this is recoverable value rather than already present.',
    }
  }

  // A live task already owns this work.
  const owningTask = liveTaskSlugs.find((slug) => ref.includes(slug))
  if (owningTask) {
    return {
      ref,
      sha,
      classification: 'ACTIVE_IN_ANOTHER_TASK',
      uniqueCommits,
      owningTask,
      reason: `a live orchestrator task ("${owningTask}") already represents this work.`,
    }
  }

  if (uniqueCommits === 0) {
    return {
      ref,
      sha,
      classification: 'ALREADY_PRESENT',
      uniqueCommits: 0,
      reason: 'no commits ahead of origin/main; nothing here is missing from what ships.',
    }
  }

  // Does it still change anything?
  const base = runGit(['merge-base', mainSha, sha], { allowFail: true })
  const stat = base ? runGit(['diff', '--stat', `${base}..${sha}`], { allowFail: true }) : null
  const changesNothing = !stat || stat.length === 0

  if (changesNothing) {
    return {
      ref,
      sha,
      classification: 'SUPERSEDED_BY_NEWER',
      uniqueCommits,
      reason:
        `${uniqueCommits} unique commit(s), but the tree is identical to the merge base — ` +
        'whatever it did has been done another way. The newest implementation wins.',
    }
  }

  const filesChanged = stat.split('\n').length - 1
  const remoteExists = remoteBranches.has(ref.replace(/^refs\/heads\//, ''))

  return {
    ref,
    sha,
    classification: 'RECOVERABLE_VALUE',
    uniqueCommits,
    filesChanged,
    remotePreserved: remoteExists,
    reason:
      `${uniqueCommits} unique commit(s) touching ${filesChanged} file(s) not on ` +
      `origin/main.` +
      (remoteExists
        ? ' A remote branch preserves it, so the durable copy already exists.'
        : ' NO remote branch preserves it — this is the only copy.'),
  }
}

/** A stash is classified by whether its diff still contains anything not on main. */
export function classifyStash(entry, ctx) {
  const sha = resolve(entry.ref)
  if (!sha) {
    return {
      ref: entry.ref,
      classification: 'CONFLICTED_NEEDS_FOCUSED_TASK',
      reason: 'stash entry does not resolve; needs a human.',
      sha: null,
    }
  }
  const base = runGit(['rev-parse', `${entry.ref}^`], { allowFail: true })
  const stat = base ? runGit(['diff', '--stat', `${base}..${sha}`], { allowFail: true }) : null

  if (!stat || stat.length === 0) {
    return {
      ref: entry.ref,
      sha,
      classification: 'ALREADY_PRESENT',
      subject: entry.subject,
      reason: 'stash carries no diff against its own base.',
    }
  }

  return {
    ref: entry.ref,
    sha,
    classification: 'RECOVERABLE_VALUE',
    subject: entry.subject,
    filesChanged: stat.split('\n').length - 1,
    reason:
      `stash holds ${stat.split('\n').length - 1} changed file(s). NOT popped, NOT ` +
      'dropped — the entry is left exactly where it was.',
  }
}

// ─── Evidence that git cannot enumerate for itself ───────────────────────────
//
// The two classifiers below exist because the snapshot the brief hands us keeps
// containing items that `enumerateEvidence()` structurally cannot find:
//
//   - a `broken_codex_git_worktree`: a directory whose `.git` file points at a
//     `worktrees/<name>` gitdir that has since been pruned. `git worktree list`
//     will never mention it — the registration is exactly what is gone — so
//     without an explicit classifier it falls off the end of the run and lands in
//     the UNKNOWN bucket, which is the one outcome the completion bar forbids.
//
//   - a `chatgpt_bridge_artifact`: a dropbox zip in `_applied/` or `_failed/`.
//     It is not a git object at all, but it is a carrier of code, and whether its
//     contents survived depends on whether the bridge's push landed.
//
// Both are supplied by path rather than discovered, because a tool that went
// hunting across the filesystem for candidate directories would be guessing.

/**
 * Extensions the bridge writes. `.zip` was the only one this file knew about, and
 * the bridge has since started emitting bare `.patch` payloads — an artifact kind
 * it could not see is an artifact kind it silently reports nothing about, which is
 * the UNKNOWN bucket wearing a different hat.
 */
const ARTIFACT_EXT = /\.(zip|patch|diff)$/

/** Content identity for artifacts, which is the only identity that survives a rename. */
function sha256File(path) {
  return createHash('sha256').update(readFileSync(path)).digest('hex')
}

/**
 * The branch the bridge says it pushed, from the `<artifact>.result.txt` sidecar.
 * Returns null when there is no receipt — absence is not evidence of failure, it
 * just means we fall back to matching on the name.
 */
export function readBridgeReceipt(artifactPath) {
  const receipt = `${artifactPath}.result.txt`
  if (!existsSync(receipt)) return null
  const text = readFileSync(receipt, 'utf8')
  return /^\[chatgpt-bridge\] pushed branch (.+)$/m.exec(text)?.[1]?.trim() ?? null
}

/** Refs whose name ends in `/<name>` or equals `<name>` — the checkout's likely home. */
function refsNamed(name) {
  const all = runGit(['for-each-ref', '--format=%(refname)'], { allowFail: true }) ?? ''
  return all.split('\n').filter((r) => r.endsWith(`/${name}`))
}

/**
 * Classify a worktree directory supplied by path, including one whose git
 * metadata no longer resolves.
 *
 * The load-bearing idea: **a worktree is a checkout, not a copy.** Its committed
 * content lives in the ref it was checked out from, so a broken registration is
 * only a real loss if that ref is also gone. What a broken worktree genuinely
 * costs is its *uncommitted* drift — unreadable once the gitdir is pruned, and
 * therefore reported as such rather than quietly assumed to be nothing.
 */
export function classifyExternalWorktree(path, ctx) {
  const { liveTaskSlugs, remoteBranches } = ctx
  const name = basename(path)

  if (!existsSync(path)) {
    return {
      ref: path,
      sha: null,
      classification: 'CONFLICTED_NEEDS_FOCUSED_TASK',
      reason:
        'the evidence path no longer exists on disk. Nothing here can be read, and a ' +
        'vanished source is a question for a human, not a silent pass.',
    }
  }

  const dotGit = join(path, '.git')
  const gitdir = existsSync(dotGit)
    ? /^gitdir:\s*(.+)$/m.exec(readFileSync(dotGit, 'utf8'))?.[1]?.trim() ?? dotGit
    : null
  const metadataLive = gitdir ? existsSync(gitdir) : false

  // A live registration needs no special handling — the normal worktree path covers it.
  if (metadataLive) {
    return {
      ref: path,
      sha: null,
      classification: 'ALREADY_PRESENT',
      reason: 'git metadata still resolves; the registered-worktree pass already covers it.',
    }
  }

  // Is a task already on this? Recovering it twice is what the coordination rule forbids.
  const owningTask =
    liveTaskSlugs.find((slug) => slug.includes(name) || name.includes(slug)) ??
    [...remoteBranches].find((b) => b.includes(name))

  const homes = refsNamed(name).filter((r) => resolve(r))

  if (owningTask) {
    return {
      ref: path,
      sha: homes[0] ? resolve(homes[0]) : null,
      classification: 'ACTIVE_IN_ANOTHER_TASK',
      owningTask,
      preservedIn: homes,
      gitdirMissing: gitdir,
      reason:
        `git metadata at ${gitdir} is gone, but "${owningTask}" already represents this ` +
        `recovery${homes.length ? ` and ${homes.length} ref(s) still carry the content` : ''}. ` +
        'Left untouched rather than recovered a second time.',
    }
  }

  if (homes.length === 0) {
    return {
      ref: path,
      sha: null,
      classification: 'CONFLICTED_NEEDS_FOCUSED_TASK',
      gitdirMissing: gitdir,
      reason:
        `git metadata at ${gitdir} is gone and no ref anywhere in the repository is named ` +
        `for "${name}". The files on disk may be the only copy and they cannot be diffed ` +
        'without the gitdir — this needs a focused task, not a classification.',
    }
  }

  return {
    ref: path,
    sha: resolve(homes[0]),
    classification: 'RECOVERABLE_VALUE',
    preservedIn: homes,
    gitdirMissing: gitdir,
    uncommittedDriftUnreadable: true,
    reason:
      `git metadata at ${gitdir} is gone. The committed content survives in ${homes.length} ` +
      `ref(s) (${homes[0]}), so the checkout itself is not the loss — but any UNCOMMITTED ` +
      'drift in this directory cannot be read without the gitdir and is not accounted for here.',
  }
}

/**
 * Classify a ChatGPT-bridge dropbox artifact.
 *
 * `_applied/` means the bridge reported success, but "the script exited 0" and "the
 * code is durably on a remote" are different claims. The one that matters is the
 * second, so the branch the artifact names is checked against the remote before the
 * artifact is called safe.
 */
export function classifyBridgeArtifact(artifactPath, ctx) {
  const { remoteBranches } = ctx
  const file = basename(artifactPath)
  const bucket = basename(join(artifactPath, '..'))
  // `<ts>--<repo>--<slug>.<ext>`
  const slug = file.replace(ARTIFACT_EXT, '').split('--').slice(2).join('--')

  if (!existsSync(artifactPath)) {
    return {
      ref: artifactPath,
      sha: null,
      classification: 'CONFLICTED_NEEDS_FOCUSED_TASK',
      reason: 'artifact named by the evidence snapshot is no longer on disk.',
    }
  }

  // Prefer the bridge's own receipt over inference from the filename.
  //
  // Every artifact has a `<name>.result.txt` sidecar holding the exact branch the
  // bridge pushed, and reading it beats reconstructing that branch from the file
  // name: the bridge appends a run suffix (`…-20260812` becomes
  // `…-20260812-08120203`), so name-matching is a guess that happens to work.
  // A guess that usually works is the worst kind here — it fails silently on the
  // one artifact whose naming drifted, and reports it as unrecoverable.
  const declaredBranch = readBridgeReceipt(artifactPath)
  const landedFromReceipt =
    declaredBranch && remoteBranches.has(declaredBranch) ? [declaredBranch] : []

  const landed = landedFromReceipt.length
    ? landedFromReceipt
    : slug
      ? [...remoteBranches].filter((b) => b.startsWith(`chatgpt/${slug}`) || b.includes(slug))
      : []

  if (landed.length > 0) {
    return {
      ref: artifactPath,
      sha: resolve(`origin/${landed[0]}`),
      classification: 'ALREADY_PRESENT',
      bucket,
      preservedIn: landed.map((b) => `origin/${b}`),
      reason:
        `the bridge pushed this payload to origin/${landed[0]}, so its contents are durable ` +
        'independently of the zip. The archive is kept as provenance, not as the only copy.',
    }
  }

  return {
    ref: artifactPath,
    sha: null,
    classification: bucket === '_failed' ? 'CONFLICTED_NEEDS_FOCUSED_TASK' : 'RECOVERABLE_VALUE',
    bucket,
    reason:
      bucket === '_failed'
        ? 'the bridge failed to apply this payload and no remote branch carries it.'
        : `marked applied, but no remote branch matches "${slug}" — the exit code said yes and ` +
          'the remote says otherwise. The zip is currently the only copy.',
  }
}

// ─── Duplicate-snapshot collapse ─────────────────────────────────────────────

/** Which kind of evidence is the most durable carrier of a given tree. */
const CARRIER_RANK = { branch: 3, worktree: 2, rescue_ref: 1, stash: 0 }

/**
 * Collapse items that carry the SAME TREE.
 *
 * Rescue refs are timestamped snapshots, and the same branch gets snapshotted
 * repeatedly — `20260803T000657-tomorrow` and `20260803T000744-tomorrow` are two
 * photographs of one thing. Counting each as independently recoverable inflates
 * the backlog with work that is already represented, which is exactly what the
 * coordination rule forbids.
 *
 * The survivor is the most durable carrier: a remote-backed branch beats a local
 * branch, which beats a rescue ref, which beats a stash. Everything else becomes
 * ALREADY_PRESENT **with a pointer to where it survives** — so nothing is written
 * off as gone; it is written down as already held somewhere better.
 */
export function collapseDuplicateTrees(items) {
  const treeOf = new Map()
  for (const item of items) {
    if (!item.sha) continue
    const tree = runGit(['rev-parse', `${item.sha}^{tree}`], { allowFail: true })
    if (tree) treeOf.set(item, tree)
  }

  const byTree = new Map()
  for (const [item, tree] of treeOf) {
    if (item.classification !== 'RECOVERABLE_VALUE') continue
    const list = byTree.get(tree) ?? []
    list.push(item)
    byTree.set(tree, list)
  }

  for (const [tree, group] of byTree) {
    if (group.length < 2) continue
    const carrier = [...group].sort((a, b) => {
      const rank = (CARRIER_RANK[b.kind] ?? 0) - (CARRIER_RANK[a.kind] ?? 0)
      if (rank !== 0) return rank
      // Prefer the one a remote preserves.
      return Number(b.remotePreserved === true) - Number(a.remotePreserved === true)
    })[0]

    for (const item of group) {
      if (item === carrier) {
        item.duplicateSnapshots = group.length - 1
        continue
      }
      item.classification = 'ALREADY_PRESENT'
      item.presentIn = carrier.ref
      item.reason =
        `identical tree (${tree.slice(0, 8)}) to ${carrier.ref}, which is a more durable ` +
        `carrier (${carrier.kind}). This is a duplicate snapshot, not a second copy of ` +
        `lost work — the content survives, and it survives there.`
    }
  }

  return items
}

// ─── Enumeration ─────────────────────────────────────────────────────────────

export function enumerateEvidence() {
  const branches = runGit([
    'for-each-ref', '--format=%(refname)', 'refs/heads',
  ]).split('\n').filter(Boolean)

  const rescueRefs = ['refs/orch-rescue', 'refs/rescue', 'refs/codex', 'refs/archive']
    .flatMap((ns) =>
      (runGit(['for-each-ref', '--format=%(refname)', ns], { allowFail: true }) ?? '')
        .split('\n')
        .filter(Boolean),
    )

  const stashes = (runGit(['stash', 'list', '--format=%gd\t%s'], { allowFail: true }) ?? '')
    .split('\n')
    .filter(Boolean)
    .map((line) => {
      const [ref, ...rest] = line.split('\t')
      return { ref, subject: rest.join('\t') }
    })

  const worktrees = (runGit(['worktree', 'list', '--porcelain'], { allowFail: true }) ?? '')
    .split('\n\n')
    .filter(Boolean)
    .map((block) => {
      const path = /^worktree (.+)$/m.exec(block)?.[1] ?? null
      const branch = /^branch (.+)$/m.exec(block)?.[1] ?? 'DETACHED'
      return { path, branch }
    })
    .filter((w) => w.path)

  return { branches, rescueRefs, stashes, worktrees }
}

/** Collect every `--flag <value>` occurrence, so the flags are repeatable. */
export function collectFlag(args, flag) {
  const out = []
  for (let i = 0; i < args.length; i += 1) {
    if (args[i] === flag && args[i + 1] && !args[i + 1].startsWith('--')) out.push(args[i + 1])
  }
  return out
}

/**
 * Every zip the bridge has already touched, under `<dropbox>/_applied` and
 * `<dropbox>/_failed`. Enumerated rather than taken from the snapshot, for the
 * same reason the refs are: a snapshot is a photograph, and the brief asks about
 * the live source.
 */
export function enumerateBridgeArtifacts(dropboxDir) {
  if (!dropboxDir || !existsSync(dropboxDir)) return []
  return ['_applied', '_failed'].flatMap((bucket) => {
    const dir = join(dropboxDir, bucket)
    if (!existsSync(dir)) return []
    return readdirSync(dir)
      // `.result.txt` sidecars sit beside the payloads and are not payloads.
      .filter((f) => ARTIFACT_EXT.test(f))
      .map((f) => join(dir, f))
  })
}

/**
 * Classify a Codex output artifact — a patch Codex wrote into its own
 * `<session>/outputs/` directory, upstream of the dropbox.
 *
 * These are named `<repo>--<slug>.patch`, with no timestamp prefix and no
 * `.result.txt` receipt: Codex writes the patch, and only later does the bridge
 * copy it into the dropbox, rename it with a timestamp, apply it and record where
 * it landed. So the same bytes exist twice under two different names, and the
 * copy that knows its fate is the other one.
 *
 * Matching by name across that rename would be guesswork. Matching by **content
 * hash** is not: if the bytes are identical, it is the same patch, and whatever
 * the bridge did with one it did with both.
 *
 * The failure this avoids is specific. A Codex output whose dropbox twin already
 * landed on a remote is safe, but nothing in its own filename says so — classified
 * on its own it looks like an unreferenced patch sitting in a scratch directory,
 * which reads as either "the only copy" (needless recovery work) or "some leftover"
 * (quietly dropping a real one). Hashing settles it.
 */
export function classifyCodexOutput(artifactPath, ctx, bridgeArtifacts = []) {
  if (!existsSync(artifactPath)) {
    return {
      ref: artifactPath,
      sha: null,
      classification: 'CONFLICTED_NEEDS_FOCUSED_TASK',
      reason: 'Codex output named by the evidence snapshot is no longer on disk.',
    }
  }

  const digest = sha256File(artifactPath)
  const twin = bridgeArtifacts.find(
    (p) => p !== artifactPath && existsSync(p) && sha256File(p) === digest,
  )

  if (twin) {
    const viaBridge = classifyBridgeArtifact(twin, ctx)
    return {
      ...viaBridge,
      ref: artifactPath,
      sha256: digest,
      identicalTo: twin,
      reason:
        `byte-identical (sha256 ${digest.slice(0, 12)}) to the dropbox artifact ` +
        `${basename(twin)}, so it shares its fate. ${viaBridge.reason}`,
    }
  }

  // No twin: fall back to the repo/slug encoded in the name.
  const slug = basename(artifactPath).replace(ARTIFACT_EXT, '').split('--').slice(1).join('--')
  const landed = slug ? [...ctx.remoteBranches].filter((b) => b.includes(slug)) : []

  if (landed.length > 0) {
    return {
      ref: artifactPath,
      sha: resolve(`origin/${landed[0]}`),
      sha256: digest,
      classification: 'ALREADY_PRESENT',
      preservedIn: landed.map((b) => `origin/${b}`),
      reason:
        `no dropbox artifact carries these bytes, but origin/${landed[0]} matches the ` +
        'slug in the filename. The content ships.',
    }
  }

  return {
    ref: artifactPath,
    sha: null,
    sha256: digest,
    classification: 'RECOVERABLE_VALUE',
    reason:
      'a Codex output patch that never reached the dropbox and matches no remote ' +
      'branch. It was written and then nothing carried it — this file is the only copy.',
  }
}

// ─── Turning "no remote copy" into something you can act on ──────────────────

/**
 * The run already ends by printing how many items have NO remote copy. That number
 * has been in the hundreds for every fingerprint so far, and a number is not a
 * remedy — if this disk dies the report is an obituary, not a recovery.
 *
 * So emit the remedy: an idempotent script that pushes each local-only tip to
 * `refs/preserved/<name>` on origin.
 *
 * The namespace is the whole safety argument. `refs/preserved/*` is NOT under
 * `refs/heads/*`, so it is not a branch: the merge train, branch protection, CI
 * triggers and Vercel's Git integration all enumerate branches and will never see
 * these. Pushing 30 recovered tips as real branches would hand the merge train 30
 * things to integrate and could trip a production deploy. Pushing them as preserved
 * refs makes them survive a dead disk and change nothing else.
 *
 * The generated script defaults to a dry run for the same reason this tool is
 * read-only: the operator should see the plan before it executes.
 */
export function buildPreservationPlan(items, { namespace = 'refs/preserved' } = {}) {
  // Every ref-shaped item, not just `kind === 'branch'`. That filter was the hole:
  // on this repository it reported "518 items have NO remote copy — the only copy is
  // on this disk" and then generated a plan covering 11 of them, because the other 507
  // were rescue/archive refs. A sweep ref is the *most* at-risk kind of evidence there
  // is — it exists precisely because the work was never on a branch — so excluding it
  // inverted the tool's own warning.
  //
  // Worktrees and stashes are still excluded: they have no ref to push.
  const PUSHABLE = new Set(['branch', 'rescue_ref', 'archive_ref', 'quarantine_ref', 'codex_ref'])
  const atRisk = items.filter(
    (i) =>
      PUSHABLE.has(i.kind) &&
      i.classification === 'RECOVERABLE_VALUE' &&
      i.remotePreserved === false &&
      i.sha &&
      typeof i.ref === 'string' &&
      i.ref.startsWith('refs/'),
  )

  const lines = [
    '#!/usr/bin/env bash',
    '# GENERATED by scripts/reconcile-evidence.mjs --preserve-plan. Do not hand-edit.',
    '#',
    '# Pushes every local-only tip — branches AND rescue/archive/quarantine refs — to a',
    '# PRESERVED ref on origin so it survives this machine. `refs/preserved/*` is not',
    '# `refs/heads/*`, so none of these become branches: the merge train, CI and Vercel',
    '# enumerate branches and will not see them.',
    '#',
    '#   ./preserve-local-only.sh            # dry run, prints what it would push',
    '#   APPLY=1 ./preserve-local-only.sh    # actually pushes',
    '#',
    '# Idempotent: re-running pushes the same sha to the same ref, which is a no-op.',
    'set -euo pipefail',
    '',
    'APPLY="${APPLY:-0}"',
    'REMOTE="${REMOTE:-origin}"',
    '',
    'push() {',
    '  local sha="$1" ref="$2"',
    '  if [ "$APPLY" = "1" ]; then',
    '    git push "$REMOTE" "$sha:$ref"',
    '  else',
    '    echo "would push $sha -> $ref"',
    '  fi',
    '}',
    '',
    `# ${atRisk.length} tip(s) with no remote copy.`,
  ]

  for (const item of atRisk) {
    // `refs/heads/x` -> `x`, but `refs/orch-rescue/x` -> `orch-rescue/x`. Keeping the
    // source namespace for non-branch refs stops two different kinds of evidence that
    // happen to share a trailing name from colliding on one preserved ref.
    const name = item.ref.startsWith('refs/heads/')
      ? item.ref.slice('refs/heads/'.length)
      : item.ref.slice('refs/'.length)
    lines.push(`push ${item.sha} ${namespace}/${name}   # ${item.uniqueCommits ?? '?'} unique commit(s)`)
  }

  if (atRisk.length === 0) {
    lines.push('echo "nothing at risk: every recoverable tip already has a remote copy."')
  } else {
    lines.push('')
    lines.push(
      `echo "${atRisk.length} tip(s) handled. Nothing was deleted, reset or moved."`,
    )
  }

  return { script: `${lines.join('\n')}\n`, atRisk: atRisk.length }
}

// ─── Main ────────────────────────────────────────────────────────────────────

function main() {
  const args = process.argv.slice(2)
  const fingerprint = args[args.indexOf('--fingerprint') + 1]
  const jsonOut = args.includes('--json') ? args[args.indexOf('--json') + 1] : null

  if (!fingerprint || fingerprint.startsWith('--')) {
    console.error(
      'usage: node scripts/reconcile-evidence.mjs --fingerprint <sha> [--json out]\n' +
        '                 [--default-branch <name>]\n' +
        '                 [--external-worktree <path>]...  worktrees git can no longer list\n' +
        '                 [--bridge-artifact <path>]...    a single dropbox zip\n' +
        '                 [--dropbox <dir>]                enumerate _applied/ and _failed/\n' +
        '                 [--preserve-plan <path>]         write a push plan for local-only tips\n' +
        '                 [--codex-output <path>]...       a patch in a Codex session outputs dir',
    )
    process.exit(2)
  }

  // The default branch is not always `main`. Take it from --default-branch, else
  // from the remote HEAD symref, else try the two conventional names. Guessing
  // wrong here would classify every ref against a branch that does not exist and
  // report the entire repository as recoverable — a confidently useless answer.
  const explicitDefault = args.includes('--default-branch')
    ? args[args.indexOf('--default-branch') + 1]
    : null
  const symref = runGit(['rev-parse', '--abbrev-ref', 'origin/HEAD'], { allowFail: true })
  const candidates = [
    explicitDefault && `origin/${explicitDefault.replace(/^origin\//, '')}`,
    symref,
    'origin/main',
    'origin/master',
  ].filter(Boolean)

  let defaultRef = null
  let mainSha = null
  for (const candidate of candidates) {
    const sha = resolve(candidate)
    if (sha) {
      defaultRef = candidate
      mainSha = sha
      break
    }
  }

  if (!mainSha) {
    console.error(
      `cannot resolve a default branch (tried ${candidates.join(', ')}); refusing to ` +
        `classify against nothing.`,
    )
    process.exit(1)
  }

  const localDefaultSha = resolve(defaultRef.replace(/^origin\//, ''))

  const remoteBranches = new Set(
    runGit(['for-each-ref', '--format=%(refname:strip=3)', 'refs/remotes/origin'])
      .split('\n')
      .filter(Boolean),
  )

  // Live orchestrator task slugs, supplied by the caller so this tool needs no DB.
  const liveTaskSlugs = (process.env.LIVE_TASK_SLUGS ?? '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)

  const ctx = { mainSha, localDefaultSha, liveTaskSlugs, remoteBranches }
  const { branches, rescueRefs, stashes, worktrees } = enumerateEvidence()

  // Evidence git cannot enumerate for itself — see the classifiers above.
  const externalWorktrees = collectFlag(args, '--external-worktree')
  const dropboxDir = collectFlag(args, '--dropbox')[0] ?? null
  const bridgeArtifacts = [
    ...collectFlag(args, '--bridge-artifact'),
    ...enumerateBridgeArtifacts(dropboxDir),
  ].filter((p, i, a) => a.indexOf(p) === i)
  const codexOutputs = collectFlag(args, '--codex-output')

  const items = collapseDuplicateTrees([
    ...branches.map((b) => ({ kind: 'branch', ...classifyRef(b, ctx) })),
    ...rescueRefs.map((r) => ({ kind: 'rescue_ref', ...classifyRef(r, ctx) })),
    ...stashes.map((s) => ({ kind: 'stash', ...classifyStash(s, ctx) })),
    ...worktrees.map((w) => ({
      kind: 'worktree',
      ref: w.path,
      branch: w.branch,
      ...classifyRef(w.branch === 'DETACHED' ? 'HEAD' : w.branch, ctx),
    })),
    ...externalWorktrees.map((p) => ({
      kind: 'external_worktree',
      ...classifyExternalWorktree(p, ctx),
    })),
    ...bridgeArtifacts.map((p) => ({
      kind: 'bridge_artifact',
      ...classifyBridgeArtifact(p, ctx),
    })),
    ...codexOutputs.map((p) => ({
      kind: 'codex_output',
      ...classifyCodexOutput(p, ctx, bridgeArtifacts),
    })),
  ])

  const counts = {}
  for (const c of CLASSIFICATIONS) counts[c] = 0
  let unknown = 0
  for (const i of items) {
    if (CLASSIFICATIONS.includes(i.classification)) counts[i.classification] += 1
    else unknown += 1
  }

  const ledger = {
    auditFingerprint: fingerprint,
    repo: runGit(['rev-parse', '--show-toplevel']),
    against: { ref: defaultRef, sha: mainSha },
    generatedAt: new Date().toISOString(),
    readOnly: true,
    itemCount: items.length,
    counts,
    unknown,
    items,
  }

  console.log(`\nEvidence reconciliation — ${fingerprint.slice(0, 12)}`)
  console.log(`  repo:        ${ledger.repo}`)
  console.log(`  against:     ${defaultRef} @ ${mainSha.slice(0, 8)}`)
  console.log(`  items:       ${items.length}`)
  for (const c of CLASSIFICATIONS) console.log(`    ${c.padEnd(30)} ${counts[c]}`)
  console.log(`  UNKNOWN:     ${unknown}${unknown === 0 ? '  ✓' : '  ✗ completion bar not met'}`)

  const onlyCopies = items.filter(
    (i) => i.classification === 'RECOVERABLE_VALUE' && i.remotePreserved === false,
  )
  if (onlyCopies.length > 0) {
    console.log(`\n  ${onlyCopies.length} item(s) have NO remote copy — the only copy is on this disk:`)
    for (const i of onlyCopies.slice(0, 20)) console.log(`    ${i.ref}`)
    if (onlyCopies.length > 20) console.log(`    … and ${onlyCopies.length - 20} more`)
  }

  console.log('\n  Nothing was popped, dropped, reset or moved. The evidence is where it was.\n')

  const planOut = collectFlag(args, '--preserve-plan')[0] ?? null
  if (planOut) {
    const { script, atRisk } = buildPreservationPlan(items)
    writeFileSync(planOut, script, { mode: 0o755 })
    console.log(
      `  preservation plan → ${planOut} (${atRisk} tip(s), dry-run by default; ` +
        'APPLY=1 to push)\n',
    )
  }

  if (jsonOut) {
    writeFileSync(jsonOut, `${JSON.stringify(ledger, null, 2)}\n`)
    console.log(`  ledger → ${jsonOut}\n`)
  }

  process.exit(unknown === 0 ? 0 : 1)
}

if (import.meta.url === `file://${process.argv[1]}`) main()

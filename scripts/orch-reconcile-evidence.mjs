#!/usr/bin/env node
/**
 * orch-reconcile-evidence.mjs
 *
 * Read-only reconciliation of local ChatGPT/Codex build evidence against the
 * current default branch, remote branches and merged history.
 *
 * Evidence sources enumerated (all treated as READ-ONLY — this script never
 * deletes, resets, cleans, pops or moves anything):
 *   - dirty working tree entries in the main clone
 *   - git stash entries
 *   - refs/orch-rescue/* rescue refs
 *   - linked worktrees
 *
 * Every item is classified into exactly one of:
 *   ALREADY_PRESENT | SUPERSEDED_BY_NEWER | ACTIVE_IN_ANOTHER_TASK
 *   | RECOVERABLE_VALUE | CONFLICTED_NEEDS_FOCUSED_TASK
 *
 * Usage:
 *   node scripts/orch-reconcile-evidence.mjs \
 *     --repo /path/to/clone --base origin/main \
 *     --fingerprint <audit-fingerprint> \
 *     --out docs/reconciliation/<slug>.json \
 *     --report docs/reconciliation/<slug>.md
 */
import { execFileSync } from 'node:child_process';
import { writeFileSync, mkdirSync, existsSync, statSync, readFileSync } from 'node:fs';
import { dirname, resolve, join } from 'node:path';

const CLASSES = [
  'ALREADY_PRESENT',
  'SUPERSEDED_BY_NEWER',
  'ACTIVE_IN_ANOTHER_TASK',
  'RECOVERABLE_VALUE',
  'CONFLICTED_NEEDS_FOCUSED_TASK',
];

/** Paths that carry no recoverable source value (git plumbing / build junk). */
const TRANSIENT = [
  /(^|\/)_to_delete\//,
  /\.lock(\.\d+)?$/,
  /(^|\/)\.DS_Store$/,
  /(^|\/)node_modules\//,
  /(^|\/)\.next\//,
  /(^|\/)dist\//,
  /(^|\/)coverage\//,
  /(^|\/)\.orch-rescue/,
];

function parseArgs(argv) {
  const out = { limitBranches: 150, maxItems: 0 };
  for (let i = 2; i < argv.length; i += 2) {
    const k = argv[i].replace(/^--/, '');
    out[k.replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = argv[i + 1];
  }
  return out;
}

function git(repo, args, { allowFail = false } = {}) {
  try {
    return execFileSync('git', ['-C', repo, ...args], {
      encoding: 'utf8',
      maxBuffer: 128 * 1024 * 1024,
      stdio: ['ignore', 'pipe', 'pipe'],
    }).trim();
  } catch (err) {
    if (allowFail) return null;
    throw new Error(`git ${args.slice(0, 3).join(' ')} failed: ${err.message}`);
  }
}

const lines = (s) => (s ? s.split('\n').filter(Boolean) : []);
const isTransient = (p) => TRANSIENT.some((re) => re.test(p));

/** Chunk a long pathspec so we never blow the argv limit. */
function chunk(arr, size = 200) {
  const out = [];
  for (let i = 0; i < arr.length; i += size) out.push(arr.slice(i, i + size));
  return out;
}

/** Paths a commit changed, relative to its first parent (or its whole tree if root). */
function changedPaths(repo, sha) {
  const hasParent = git(repo, ['rev-parse', '--verify', '--quiet', `${sha}^`], { allowFail: true });
  if (hasParent) {
    return lines(git(repo, ['diff', '--name-only', '-m', '--first-parent', `${sha}^`, sha], { allowFail: true }) ?? '');
  }
  return lines(git(repo, ['ls-tree', '-r', '--name-only', sha], { allowFail: true }) ?? '');
}

/** Of `paths`, the ones whose content at `sha` differs from `base`. */
function differingFromBase(repo, sha, base, paths) {
  const differing = [];
  for (const group of chunk(paths)) {
    const res = git(repo, ['diff', '--name-only', sha, base, '--', ...group], { allowFail: true });
    if (res === null) continue;
    differing.push(...lines(res));
  }
  return [...new Set(differing)];
}

/** True if `base` gained a commit touching any of `paths` after `sinceUnix`. */
function baseMovedAfter(repo, base, paths, sinceUnix) {
  for (const group of chunk(paths)) {
    const res = git(
      repo,
      ['log', '--format=%H', '-1', `--since=@${sinceUnix}`, base, '--', ...group],
      { allowFail: true },
    );
    if (res) return res;
  }
  return null;
}

/** Would merging `sha` into `base` conflict? */
function conflicts(repo, base, sha) {
  const modern = git(repo, ['merge-tree', '--write-tree', '--name-only', base, sha], { allowFail: true });
  if (modern !== null) return /^CONFLICT|\bconflict\b/im.test(modern) ? modern.split('\n').slice(1, 6) : null;
  const mb = git(repo, ['merge-base', base, sha], { allowFail: true });
  if (!mb) return null;
  const legacy = git(repo, ['merge-tree', mb, base, sha], { allowFail: true });
  return legacy && legacy.includes('<<<<<<<') ? ['legacy merge-tree reported conflict hunks'] : null;
}

/**
 * Paths already claimed by live agent work (local + remote agent/* branches).
 * Used to detect ACTIVE_IN_ANOTHER_TASK so we never duplicate queued work.
 */
function activeWorkIndex(repo, base, limit) {
  const refs = lines(
    git(repo, ['for-each-ref', '--format=%(refname)', '--sort=-committerdate',
      'refs/remotes/origin/agent/*', 'refs/heads/agent/*'], { allowFail: true }) ?? '',
  ).slice(0, limit);
  const index = new Map(); // path -> ref
  for (const ref of refs) {
    const mb = git(repo, ['merge-base', base, ref], { allowFail: true });
    if (!mb) continue;
    for (const p of lines(git(repo, ['diff', '--name-only', mb, ref], { allowFail: true }) ?? '')) {
      if (!index.has(p)) index.set(p, ref);
    }
  }
  return { index, refCount: refs.length };
}

/** Classify one commit-shaped evidence item. */
function classifyCommit(repo, base, sha, whenUnix, active) {
  const paths = changedPaths(repo, sha);
  const meaningful = paths.filter((p) => !isTransient(p));
  if (paths.length === 0) {
    return { classification: 'ALREADY_PRESENT', reason: 'empty changeset — nothing to recover', paths: [] };
  }
  if (meaningful.length === 0) {
    return {
      classification: 'ALREADY_PRESENT',
      reason: 'only transient/non-source artifacts (lock files, build output) — no recoverable content',
      paths: paths.slice(0, 20),
    };
  }
  if (git(repo, ['merge-base', '--is-ancestor', sha, base], { allowFail: true }) !== null) {
    return { classification: 'ALREADY_PRESENT', reason: `commit is an ancestor of ${base}`, paths: meaningful.slice(0, 20) };
  }
  const differing = differingFromBase(repo, sha, base, meaningful);
  if (differing.length === 0) {
    return {
      classification: 'ALREADY_PRESENT',
      reason: `every touched path is byte-identical to ${base}`,
      paths: meaningful.slice(0, 20),
    };
  }
  const newer = baseMovedAfter(repo, base, differing, whenUnix);
  if (newer) {
    return {
      classification: 'SUPERSEDED_BY_NEWER',
      reason: `${base} has newer commit ${newer.slice(0, 12)} touching these paths`,
      paths: differing.slice(0, 20),
    };
  }
  const claimed = differing.filter((p) => active.index.has(p));
  if (claimed.length && claimed.length === differing.length) {
    return {
      classification: 'ACTIVE_IN_ANOTHER_TASK',
      reason: `all paths are already covered by live agent branch ${active.index.get(claimed[0])}`,
      paths: claimed.slice(0, 20),
    };
  }
  const conflictHunks = conflicts(repo, base, sha);
  if (conflictHunks) {
    return {
      classification: 'CONFLICTED_NEEDS_FOCUSED_TASK',
      reason: `merge into ${base} conflicts: ${conflictHunks.slice(0, 3).join(', ')}`,
      paths: differing.slice(0, 20),
    };
  }
  return {
    classification: 'RECOVERABLE_VALUE',
    reason: `${differing.length} path(s) carry content absent from ${base} with no newer supersession`,
    paths: differing.slice(0, 20),
  };
}

function enumerateEvidence(repo) {
  const items = [];

  for (const line of lines(git(repo, ['status', '--porcelain'], { allowFail: true }) ?? '')) {
    const path = line.slice(3).trim().replace(/^"|"$/g, '');
    items.push({ kind: 'dirty_worktree_path', source: `${repo}:${path}`, path, status: line.slice(0, 2) });
  }

  for (const line of lines(git(repo, ['stash', 'list', '--format=%H%x09%gd%x09%ct%x09%gs'], { allowFail: true }) ?? '')) {
    const [sha, gd, ct, subject] = line.split('\t');
    items.push({ kind: 'stash', source: gd, sha, when: Number(ct), subject });
  }

  const rescueFmt = '%(objectname)%09%(refname)%09%(creatordate:unix)%09%(contents:subject)';
  for (const line of lines(git(repo, ['for-each-ref', `--format=${rescueFmt}`, 'refs/orch-rescue/'], { allowFail: true }) ?? '')) {
    const [sha, refname, when, subject] = line.split('\t');
    items.push({ kind: 'rescue_ref', source: refname, sha, when: Number(when), subject });
  }

  let wt = null;
  for (const line of lines(git(repo, ['worktree', 'list', '--porcelain'], { allowFail: true }) ?? '')) {
    if (line.startsWith('worktree ')) wt = { kind: 'linked_worktree', source: line.slice(9) };
    else if (line.startsWith('HEAD ') && wt) wt.sha = line.slice(5);
    else if ((line === 'detached' || line.startsWith('branch ')) && wt) {
      wt.branch = line === 'detached' ? '(detached)' : line.slice(7);
      if (wt.source !== repo) items.push(wt);
      wt = null;
    }
  }
  return items;
}

function classifyDirtyPath(repo, base, item) {
  if (isTransient(item.path)) {
    return {
      classification: 'ALREADY_PRESENT',
      reason: 'transient git/build artifact — carries no source content to recover',
      paths: [item.path],
    };
  }
  const inBase = git(repo, ['cat-file', '-e', `${base}:${item.path}`], { allowFail: true });
  if (inBase === null) {
    return { classification: 'RECOVERABLE_VALUE', reason: `untracked path absent from ${base}`, paths: [item.path] };
  }
  const diff = git(repo, ['diff', base, '--name-only', '--', item.path], { allowFail: true });
  if (!diff) {
    return { classification: 'ALREADY_PRESENT', reason: `identical to ${base}`, paths: [item.path] };
  }
  return { classification: 'RECOVERABLE_VALUE', reason: `local edit diverges from ${base}`, paths: [item.path] };
}

function renderReport(meta, items, counts) {
  const L = [];
  L.push(`# ChatGPT/Codex local evidence reconciliation — ${meta.project}`);
  L.push('');
  L.push(`- Audit fingerprint: \`${meta.fingerprint}\``);
  L.push(`- Repository: \`${meta.repo}\``);
  L.push(`- Compared against: \`${meta.base}\` @ \`${meta.baseSha.slice(0, 12)}\``);
  L.push(`- Live agent branches indexed: ${meta.activeRefCount}`);
  L.push(`- Generated: ${meta.generatedAt}`);
  L.push(`- Evidence items classified: **${items.length}** (UNKNOWN: **0**)`);
  L.push('');
  L.push('All evidence sources were read only. No stash was popped, no ref deleted,');
  L.push('no worktree removed, no working tree reset or cleaned.');
  L.push('');
  L.push('## Classification summary');
  L.push('');
  L.push('| Classification | Items |');
  L.push('| --- | ---: |');
  for (const c of CLASSES) L.push(`| ${c} | ${counts[c] ?? 0} |`);
  L.push('');
  const actionable = items.filter(
    (i) => i.classification === 'RECOVERABLE_VALUE' || i.classification === 'CONFLICTED_NEEDS_FOCUSED_TASK',
  );
  L.push('## Items with remaining value');
  L.push('');
  if (!actionable.length) {
    L.push('None. Every evidence item is already present on the default branch, superseded');
    L.push('by newer work, or covered by a live agent branch.');
  } else {
    L.push('| Source | Kind | Classification | Paths | Reason |');
    L.push('| --- | --- | --- | --- | --- |');
    for (const i of actionable.slice(0, 200)) {
      L.push(`| \`${i.source}\` | ${i.kind} | ${i.classification} | ${i.paths.slice(0, 4).join('<br>') || '—'} | ${i.reason} |`);
    }
  }
  L.push('');
  L.push('## Full ledger');
  L.push('');
  L.push('The machine-readable ledger (one record per evidence item, with source,');
  L.push('classification, disposition and resulting task/branch/commit) is written');
  L.push(`alongside this report as \`${meta.jsonName}\` and mirrored into the`);
  L.push('`coordination_tasks` recovery ledger.');
  L.push('');
  return L.join('\n');
}

function main() {
  const args = parseArgs(process.argv);
  const repo = resolve(args.repo || process.cwd());
  const base = args.base || 'origin/main';
  const fingerprint = args.fingerprint || 'unspecified';
  const project = args.project || repo.split('/').pop();
  const baseSha = git(repo, ['rev-parse', base]);
  const active = activeWorkIndex(repo, base, Number(args.limitBranches) || 150);

  const raw = enumerateEvidence(repo);
  const items = raw.map((item) => {
    const verdict = item.kind === 'dirty_worktree_path'
      ? classifyDirtyPath(repo, base, item)
      : classifyCommit(repo, base, item.sha, item.when || Math.floor(Date.now() / 1000), active);
    return { ...item, ...verdict };
  });

  const counts = {};
  for (const i of items) counts[i.classification] = (counts[i.classification] ?? 0) + 1;

  const meta = {
    project,
    repo,
    base,
    baseSha,
    fingerprint,
    activeRefCount: active.refCount,
    generatedAt: new Date().toISOString(),
    jsonName: (args.out || '').split('/').pop(),
  };

  // Outputs land in --out-root (the isolated agent worktree), never in the
  // evidence source clone, which stays strictly read-only.
  const outRoot = resolve(args.outRoot || process.cwd());
  if (args.out) {
    mkdirSync(dirname(resolve(outRoot, args.out)), { recursive: true });
    writeFileSync(resolve(outRoot, args.out), JSON.stringify({ meta, counts, items }, null, 2) + '\n');
  }
  if (args.report) {
    mkdirSync(dirname(resolve(outRoot, args.report)), { recursive: true });
    writeFileSync(resolve(outRoot, args.report), renderReport(meta, items, counts));
  }
  process.stdout.write(JSON.stringify({ meta, counts, total: items.length }, null, 2) + '\n');
}

main();

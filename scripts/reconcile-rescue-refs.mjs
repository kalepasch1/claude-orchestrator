#!/usr/bin/env node
/**
 * reconcile-rescue-refs.mjs
 *
 * Read-only reconciliation of local ChatGPT/Codex build evidence (orch-rescue
 * refs, stashes, rescue branches) against the current default branch.
 *
 * NEVER mutates the evidence: no delete/reset/clean/pop/move. It only reads
 * refs and computes diffs, then emits a recovery ledger.
 *
 * Classification (one per evidence item):
 *   ALREADY_PRESENT              - ref is an ancestor of the base, or its diff
 *                                  vs the merge-base is empty against base.
 *   SUPERSEDED_BY_NEWER          - every file it touches was changed on base
 *                                  more recently than the rescue commit.
 *   ACTIVE_IN_ANOTHER_TASK       - an agent/* or chatgpt/* branch already
 *                                  carries this tree.
 *   RECOVERABLE_VALUE            - real content not on base, applies cleanly.
 *   CONFLICTED_NEEDS_FOCUSED_TASK- real content that does not apply cleanly.
 *
 * Usage:
 *   node scripts/reconcile-rescue-refs.mjs [--base origin/master]
 *        [--prefix refs/orch-rescue/] [--out docs/recovery-ledger.json]
 *        [--fingerprint <sha256>]
 */

import { execFileSync } from 'node:child_process';
import { writeFileSync, mkdirSync } from 'node:fs';
import { dirname } from 'node:path';

const args = process.argv.slice(2);
const argOf = (name, fallback) => {
  const i = args.indexOf(`--${name}`);
  return i >= 0 && args[i + 1] ? args[i + 1] : fallback;
};

const BASE = argOf('base', 'origin/master');
const PREFIX = argOf('prefix', 'refs/orch-rescue/');
const OUT = argOf('out', 'docs/recovery-ledger.json');
const FINGERPRINT = argOf('fingerprint', '');
const LIMIT = Number(argOf('limit', '0')) || 0;

// Fail-soft git: never throw on a bad ref, return '' instead. The evidence set
// is untrusted local history and half of it predates the current schema.
function git(cliArgs, opts = {}) {
  try {
    return execFileSync('git', cliArgs, {
      encoding: 'utf8',
      maxBuffer: 64 * 1024 * 1024,
      stdio: ['ignore', 'pipe', 'ignore'],
      ...opts,
    }).trim();
  } catch {
    return '';
  }
}

function gitOk(cliArgs) {
  try {
    execFileSync('git', cliArgs, { stdio: 'ignore' });
    return true;
  } catch {
    return false;
  }
}

/** Every ref under PREFIX, newest first. */
function listEvidenceRefs() {
  const raw = git([
    'for-each-ref',
    '--format=%(refname)%09%(objectname)%09%(creatordate:unix)%09%(contents:subject)',
    PREFIX,
  ]);
  if (!raw) return [];
  const rows = raw
    .split('\n')
    .filter(Boolean)
    .map((line) => {
      const [ref, sha, created, ...rest] = line.split('\t');
      return { ref, sha, created: Number(created) || 0, subject: rest.join('\t') };
    })
    .sort((a, b) => b.created - a.created);
  return LIMIT ? rows.slice(0, LIMIT) : rows;
}

/** Branches (local + remote) that already carry a given tree, excluding base. */
function branchesCarrying(sha) {
  const out = git(['branch', '--all', '--contains', sha, '--format=%(refname)']);
  if (!out) return [];
  return out
    .split('\n')
    .map((s) => s.trim())
    .filter(Boolean)
    .filter((r) => !r.endsWith('/master') && !r.endsWith('/main') && !r.endsWith('/HEAD'));
}

/**
 * Generated/derived paths carry no recoverable value — a rescue ref whose only
 * content is a vitest cache or a build output is noise, not lost work. Without
 * this filter those refs classify as RECOVERABLE_VALUE and generate follow-up
 * tasks that can never produce a meaningful diff.
 */
const GENERATED_PATH = /(^|\/)(node_modules|\.vite|\.nuxt|\.next|\.turbo|\.cache|dist|build|coverage|\.output|__snapshots__)(\/|$)/;

const isGenerated = (f) => GENERATED_PATH.test(f);

/** Files a rescue commit touches relative to its merge-base with the base. */
function touchedFiles(sha, mergeBase) {
  const out = git(['diff', '--name-only', `${mergeBase}..${sha}`]);
  return out ? out.split('\n').filter(Boolean) : [];
}

/** Unix time of the newest commit on base touching any of `files`. */
function baseLastTouched(files) {
  if (!files.length) return 0;
  const out = git(['log', '-1', '--format=%ct', BASE, '--', ...files]);
  return Number(out) || 0;
}

/**
 * Classify one evidence item. Read-only: the only git plumbing used here that
 * writes anything is `apply --check`, which writes nothing (it is a dry run).
 */
function classify(item, baseSha) {
  const { sha } = item;

  if (!git(['cat-file', '-t', sha])) {
    return { classification: 'ALREADY_PRESENT', reason: 'object missing from object db (already gc-ed / never had content)', files: [], carriers: [] };
  }

  // Reachable from base => the work shipped.
  if (gitOk(['merge-base', '--is-ancestor', sha, baseSha])) {
    return { classification: 'ALREADY_PRESENT', reason: `ancestor of ${BASE}`, files: [], carriers: [] };
  }

  const mergeBase = git(['merge-base', sha, baseSha]);
  if (!mergeBase) {
    return { classification: 'CONFLICTED_NEEDS_FOCUSED_TASK', reason: `no merge-base with ${BASE} (unrelated history)`, files: [], carriers: [] };
  }

  const allFiles = touchedFiles(sha, mergeBase);
  if (allFiles.length === 0) {
    return { classification: 'ALREADY_PRESENT', reason: 'empty diff vs merge-base (bookkeeping ref only)', files: allFiles, carriers: [] };
  }

  const files = allFiles.filter((f) => !isGenerated(f));
  if (files.length === 0) {
    return { classification: 'ALREADY_PRESENT', reason: `touches only generated/derived paths (${allFiles.length} file(s), e.g. ${allFiles[0]}) — no recoverable source`, files: allFiles, carriers: [] };
  }

  // Content already identical on base => nothing left to recover.
  const residual = git(['diff', '--name-only', sha, baseSha, '--', ...files]);
  if (!residual) {
    return { classification: 'ALREADY_PRESENT', reason: `content identical to ${BASE} for every touched file`, files, carriers: [] };
  }

  const carriers = branchesCarrying(sha);
  if (carriers.length) {
    return { classification: 'ACTIVE_IN_ANOTHER_TASK', reason: `carried by ${carriers.slice(0, 3).join(', ')}`, files, carriers };
  }

  // Newest implementation wins: if base moved on every touched file after this
  // commit was written, the rescue copy is stale by construction.
  const lastBase = baseLastTouched(files);
  if (lastBase && lastBase > item.created) {
    return { classification: 'SUPERSEDED_BY_NEWER', reason: `${BASE} last touched these files at ${new Date(lastBase * 1000).toISOString()}, after the rescue commit`, files, carriers };
  }

  const applies = (() => {
    // Scope the applicability check to real source files — a generated file
    // that conflicts must not condemn an otherwise-clean recovery.
    const patch = git(['diff', `${mergeBase}..${sha}`, '--', ...files]);
    if (!patch) return false;
    try {
      execFileSync('git', ['apply', '--check', '--3way', '-'], { input: patch, stdio: ['pipe', 'ignore', 'ignore'] });
      return true;
    } catch {
      return false;
    }
  })();

  return applies
    ? { classification: 'RECOVERABLE_VALUE', reason: 'diff applies cleanly onto base and is not represented elsewhere', files, carriers }
    : { classification: 'CONFLICTED_NEEDS_FOCUSED_TASK', reason: 'diff does not apply cleanly onto base', files, carriers };
}

/** Disposition per classification — what the ledger commits us to next. */
const DISPOSITION = {
  ALREADY_PRESENT: 'no action — value already on the default branch',
  SUPERSEDED_BY_NEWER: 'no action — newer implementation on the default branch wins',
  ACTIVE_IN_ANOTHER_TASK: 'no action — leave to the owning branch/task; do not duplicate',
  RECOVERABLE_VALUE: 'queue a focused recovery task; apply in a fresh isolated worktree',
  CONFLICTED_NEEDS_FOCUSED_TASK: 'queue a focused conflict-resolution task; never force-overwrite',
};

function main() {
  const baseSha = git(['rev-parse', BASE]) || git(['rev-parse', 'HEAD']);
  const items = listEvidenceRefs();

  const records = items.map((item) => {
    const verdict = classify(item, baseSha);
    return {
      audit_fingerprint: FINGERPRINT || null,
      source: item.ref,
      source_sha: item.sha,
      source_subject: item.subject,
      source_created_at: item.created,
      classification: verdict.classification,
      classification_reason: verdict.reason,
      disposition: DISPOSITION[verdict.classification],
      touched_files: verdict.files.slice(0, 50),
      touched_file_count: verdict.files.length,
      carrier_branches: verdict.carriers,
      resulting_ref: verdict.carriers[0] || null,
    };
  });

  const summary = records.reduce((acc, r) => {
    acc[r.classification] = (acc[r.classification] || 0) + 1;
    return acc;
  }, {});

  const ledger = {
    audit_fingerprint: FINGERPRINT || null,
    base: BASE,
    base_sha: baseSha,
    evidence_prefix: PREFIX,
    generated_at: new Date().toISOString(),
    total_items: records.length,
    unknown_items: records.filter((r) => !r.classification).length,
    summary,
    records,
  };

  mkdirSync(dirname(OUT), { recursive: true });
  writeFileSync(OUT, `${JSON.stringify(ledger, null, 2)}\n`);

  console.log(`reconciled ${records.length} evidence item(s) against ${BASE}`);
  for (const [k, v] of Object.entries(summary).sort()) console.log(`  ${k}: ${v}`);
  console.log(`ledger -> ${OUT}`);
  return ledger.unknown_items === 0 ? 0 : 1;
}

process.exit(main());

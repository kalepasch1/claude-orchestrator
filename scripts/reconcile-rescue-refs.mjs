#!/usr/bin/env node
// reconcile-rescue-refs.mjs — classify recovered build evidence against live history.
//
// PURPOSE
// The orchestrator's crash-recovery sweeps park work-in-progress under
// refs/orch-rescue/**, refs/recovery/**, refs/orchestrator/** and stashes.
// Over time these accumulate into a large opaque pile: nobody can say which
// entries still hold value and which were long ago merged. That ambiguity is
// itself the risk — the pile gets either blindly deleted (losing real work) or
// blindly replayed (clobbering newer code).
//
// This script answers the question mechanically and repeatably, and is
// deliberately READ-ONLY: it never deletes, resets, cleans, pops, or moves any
// evidence ref. It only reads and classifies.
//
// CLASSIFICATIONS (the newest/most complete implementation always wins)
//   ALREADY_PRESENT             commit is an ancestor of the default branch, or
//                               its tree is identical to it — nothing to recover.
//   SUPERSEDED_BY_NEWER         every file it touches has been modified on the
//                               default branch AFTER this commit was authored.
//   ACTIVE_IN_ANOTHER_TASK      still reachable from a live agent/* branch, so a
//                               different task already owns it.
//   RECOVERABLE_VALUE           carries a real delta and replays cleanly.
//   CONFLICTED_NEEDS_FOCUSED_TASK  carries a real delta but does not replay
//                               cleanly — needs a focused human/agent task, not
//                               a forced overwrite.
//
// USAGE
//   node scripts/reconcile-rescue-refs.mjs [--base origin/main] [--json out.json]
//   node scripts/reconcile-rescue-refs.mjs --namespaces refs/orch-rescue

import { execFileSync } from "node:child_process";
import { writeFileSync } from "node:fs";

const DEFAULT_NAMESPACES = [
  "refs/orch-rescue",
  "refs/recovery",
  "refs/orchestrator",
];

function arg(flag, fallback) {
  const i = process.argv.indexOf(flag);
  return i !== -1 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
}

function git(args, { allowFail = false } = {}) {
  try {
    return execFileSync("git", args, {
      encoding: "utf8",
      maxBuffer: 256 * 1024 * 1024,
      stdio: ["ignore", "pipe", "pipe"],
    }).trim();
  } catch (err) {
    if (allowFail) return null;
    throw err;
  }
}

function gitOk(args) {
  try {
    execFileSync("git", args, { stdio: "ignore" });
    return true;
  } catch {
    return false;
  }
}

const BASE = arg("--base", "origin/main");
const NAMESPACES = arg("--namespaces", DEFAULT_NAMESPACES.join(","))
  .split(",")
  .map((s) => s.trim())
  .filter(Boolean);

// ---------------------------------------------------------------------------
// Collect evidence refs
// ---------------------------------------------------------------------------
function collectRefs() {
  const rows = [];
  for (const ns of NAMESPACES) {
    const out = git(
      ["for-each-ref", "--format=%(objectname)%09%(refname)%09%(creatordate:unix)", `${ns}/**`],
      { allowFail: true },
    );
    if (!out) continue;
    for (const line of out.split("\n").filter(Boolean)) {
      const [sha, ref, created] = line.split("\t");
      rows.push({ sha, ref, created: Number(created) || 0, namespace: ns });
    }
  }
  return rows;
}

// ---------------------------------------------------------------------------
// Per-commit classification
// ---------------------------------------------------------------------------
function filesTouched(sha) {
  // Diff against the merge-base so we describe the commit's own contribution,
  // not the entire divergence of history.
  const mb = git(["merge-base", BASE, sha], { allowFail: true });
  if (!mb) return null;
  const out = git(["diff", "--name-only", `${mb}`, sha], { allowFail: true });
  return out ? out.split("\n").filter(Boolean) : [];
}

function baseTouchedAllAfter(files, sinceUnix) {
  // SUPERSEDED only if EVERY file that the base ALSO has saw a later change on
  // the base branch.
  //
  // Restricting to paths present on the base matters. A crash snapshot drags
  // along orchestrator scratch files (.commit-message, .recovery-intent-*.txt)
  // that the base has never tracked and never will. Those paths can never have
  // a "later change on base", so counting them silently defeats the whole test
  // — which is how three snapshots that predate the RIA fail-closed compliance
  // gate were nearly classified RECOVERABLE_VALUE. Replaying them would have
  // stripped that gate back out. A path the base does not carry cannot be
  // evidence that the base is stale.
  const tracked = files.filter((f) => gitOk(["cat-file", "-e", `${BASE}:${f}`]));
  if (!tracked.length) return false;
  for (const f of tracked) {
    const last = git(["log", "-1", "--format=%ct", BASE, "--", f], { allowFail: true });
    if (!last || Number(last) <= sinceUnix) return false;
  }
  return true;
}

// Paths the orchestrator writes for its own bookkeeping. These are captured by
// crash sweeps but are never deliverable product content, so they must not be
// counted as a snapshot's contribution. Anchored at the repo root on purpose —
// a real source file is never matched by these.
const SCRATCH_PATTERNS = [
  /^\.recovery-intent[-.]/,
  /^\.commit[-_]messages?$/,
  /^\.deploy-canary$/,
  /^\.canary-/,
  /^\.copyfix-/,
  /^\.orch(-|$)/,
  /^\.gitignore\.bak$/,
  /^\.aider\./,
];

function isScratchPath(p) {
  return SCRATCH_PATTERNS.some((re) => re.test(p));
}

function liveBranchesContaining(sha) {
  const out = git(["branch", "-a", "--contains", sha], { allowFail: true });
  if (!out) return [];
  return out
    .split("\n")
    .map((l) => l.replace(/^[*+]?\s*/, "").trim())
    .filter((l) => l && !l.includes("HEAD detached"))
    .filter((l) => /(^|\/)agent\//.test(l));
}

function replaysCleanly(sha) {
  // Dry-run the patch against the base tree. Never mutates the worktree.
  const mb = git(["merge-base", BASE, sha], { allowFail: true });
  if (!mb) return false;
  const patch = git(["diff", "--binary", mb, sha], { allowFail: true });
  if (patch === null) return false;
  if (!patch.trim()) return true;
  try {
    execFileSync("git", ["apply", "--check", "--3way", "-"], {
      input: patch + "\n",
      stdio: ["pipe", "ignore", "ignore"],
    });
    return true;
  } catch {
    return false;
  }
}

// A crash sweep snapshots the *uncommitted* worktree of a branch that was
// mid-flight, and records it as "On <branch>: orch-rescue: periodic sweep".
// Such a snapshot has no independent authorship — its value is entirely
// derivative of the branch it was taken from. Judging it purely by "does this
// diff replay cleanly" badly overstates its worth: a sweep taken from a branch
// that has since merged is stale by construction, and one taken from a branch
// that is still live is already owned by that branch's task. Resolving the
// provenance first is what makes this reconciliation trustworthy rather than a
// pile of 60+ spurious "recoverable" items.
function sweepProvenance(subject) {
  const m = /^On (\S+?):/.exec(subject || "");
  if (!m) return null;
  const branch = m[1];
  const head = git(["rev-parse", "--verify", "--quiet", `origin/${branch}`], { allowFail: true });
  if (!head) return { branch, state: "gone" };
  return {
    branch,
    state: gitOk(["merge-base", "--is-ancestor", head, BASE]) ? "merged" : "live",
  };
}

function classify(sha, createdAt, subject) {
  if (gitOk(["merge-base", "--is-ancestor", sha, BASE])) {
    return { classification: "ALREADY_PRESENT", reason: `ancestor of ${BASE}` };
  }
  if (gitOk(["diff", "--quiet", BASE, sha])) {
    return { classification: "ALREADY_PRESENT", reason: `tree identical to ${BASE}` };
  }

  const sweep = sweepProvenance(subject);
  if (sweep && sweep.state === "merged") {
    return {
      classification: "SUPERSEDED_BY_NEWER",
      reason: `mid-flight sweep of ${sweep.branch}, which has since merged into ${BASE}`,
      source_branch: sweep.branch,
    };
  }
  if (sweep && sweep.state === "live") {
    return {
      classification: "ACTIVE_IN_ANOTHER_TASK",
      reason: `mid-flight sweep of ${sweep.branch}, which is still live and unmerged`,
      source_branch: sweep.branch,
    };
  }
  // sweep.state === "gone" falls through: the branch was deleted, so the
  // snapshot may be the only surviving copy. Judge it on its delta.

  const files = filesTouched(sha);
  if (files === null) {
    return {
      classification: "CONFLICTED_NEEDS_FOCUSED_TASK",
      reason: "no merge-base with the default branch (unrelated history)",
      files: [],
    };
  }
  if (files.length === 0) {
    return { classification: "ALREADY_PRESENT", reason: "empty delta vs merge-base", files };
  }

  const authored = Number(git(["log", "-1", "--format=%ct", sha], { allowFail: true })) || createdAt;

  // What does this snapshot actually CONTRIBUTE relative to the base?
  // Direction matters: in `diff BASE sha`, a "D" means the base has the path
  // and the snapshot does not — that is the base being ahead, never a reason to
  // recover the snapshot. Only added/modified paths are contributions, and only
  // those may be weighed as evidence that the snapshot still holds value.
  const statusRows = (git(["diff", "--name-status", BASE, sha], { allowFail: true }) || "")
    .split("\n")
    .filter(Boolean)
    .map((l) => l.split("\t"));
  const rawContributions = statusRows.filter(([code]) => code && code[0] !== "D").map((r) => r[r.length - 1]);
  // Orchestrator scratch artifacts are not deliverable value. A crash sweep
  // captures the runner's own bookkeeping (.recovery-intent-*.txt, .commit-message,
  // .deploy-canary, .canary-*), and because the base has never tracked those paths
  // they register as "new content the base lacks" — which is how a snapshot whose
  // real source contribution is exactly nothing still reads as recoverable.
  // Strip them before judging. A genuinely new source file is untouched by this.
  const contributions = rawContributions.filter((p) => !isScratchPath(p));
  const scratchOnly = rawContributions.length > 0 && contributions.length === 0;
  const deletions = statusRows.length - rawContributions.length;

  const branches = liveBranchesContaining(sha);
  if (branches.length) {
    return {
      classification: "ACTIVE_IN_ANOTHER_TASK",
      reason: `reachable from live agent branch(es): ${branches.slice(0, 3).join(", ")}`,
      files,
      branches,
    };
  }

  // SAFETY: "the patch applies cleanly" is NOT the same as "the patch adds
  // value". A stale snapshot taken before a batch of files landed will apply
  // cleanly and, in doing so, DELETE live code. If it contributes nothing at
  // all, the base strictly dominates it and replaying would be a regression
  // dressed as a recovery. The newest implementation wins.
  if (statusRows.length && contributions.length === 0) {
    return {
      classification: "SUPERSEDED_BY_NEWER",
      reason: scratchOnly
        ? `snapshot contributes only orchestrator scratch artifacts (${rawContributions.length} path(s)) ` +
          `and drops ${deletions} path(s) ${BASE} still has — no deliverable content`
        : `snapshot is a strict subset of ${BASE}: all ${statusRows.length} differing path(s) ` +
          `exist on ${BASE} and are absent here — replaying it would delete live code`,
      files,
      deletions_vs_base: deletions,
      scratch_only: scratchOnly,
      strict_subset: !scratchOnly,
    };
  }

  // Weigh supersession over the CONTRIBUTED paths only. Measuring it over the
  // merge-base diff instead lets untracked scratch files and pure deletions
  // outvote the real signal — the failure that nearly recovered three
  // snapshots predating the RIA fail-closed compliance gate.
  if (baseTouchedAllAfter(contributions, authored)) {
    return {
      classification: "SUPERSEDED_BY_NEWER",
      reason:
        `every path this snapshot contributes and ${BASE} also tracks was changed on ` +
        `${BASE} after the snapshot was taken (it also drops ${deletions} path(s) ${BASE} still has)`,
      files,
      contributions,
      deletions_vs_base: deletions,
    };
  }

  if (replaysCleanly(sha)) {
    return {
      classification: "RECOVERABLE_VALUE",
      reason: `delta over ${files.length} path(s) replays cleanly onto ${BASE} and contributes new or changed content`,
      files,
    };
  }

  return {
    classification: "CONFLICTED_NEEDS_FOCUSED_TASK",
    reason: `delta over ${files.length} path(s) does not replay cleanly onto ${BASE}`,
    files,
  };
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------
function main() {
  const refs = collectRefs();
  if (!refs.length) {
    console.log("reconcile: no evidence refs found in", NAMESPACES.join(", "));
    return;
  }

  // Classify once per distinct commit; fan the verdict back out to every ref
  // that points at it. Many sweeps park the same sha under several names.
  const bySha = new Map();
  for (const r of refs) {
    if (!bySha.has(r.sha)) bySha.set(r.sha, []);
    bySha.get(r.sha).push(r);
  }

  const ledger = [];
  const counts = {};
  for (const [sha, group] of bySha) {
    const subject = git(["log", "-1", "--format=%s", sha], { allowFail: true }) || "(unknown)";
    const verdict = classify(sha, group[0].created, subject);
    counts[verdict.classification] = (counts[verdict.classification] || 0) + 1;
    ledger.push({
      sha,
      subject,
      refs: group.map((g) => g.ref),
      ref_count: group.length,
      ...verdict,
    });
  }

  ledger.sort((a, b) => a.classification.localeCompare(b.classification) || a.sha.localeCompare(b.sha));

  const unknown = ledger.filter((l) => !l.classification).length;
  const report = {
    base: BASE,
    namespaces: NAMESPACES,
    generated_at: new Date().toISOString(),
    total_refs: refs.length,
    distinct_commits: ledger.length,
    unknown,
    counts,
    ledger,
  };

  const jsonPath = arg("--json", null);
  if (jsonPath) {
    writeFileSync(jsonPath, JSON.stringify(report, null, 2));
    console.log(`reconcile: wrote ${jsonPath}`);
  }

  console.log(`reconcile: base=${BASE}`);
  console.log(`reconcile: ${refs.length} refs -> ${ledger.length} distinct commits`);
  for (const [k, v] of Object.entries(counts).sort((a, b) => b[1] - a[1])) {
    console.log(`  ${String(v).padStart(4)}  ${k}`);
  }
  console.log(`  UNKNOWN: ${unknown}`);

  // Zero UNKNOWN is the completion bar for a reconciliation.
  if (unknown > 0) process.exitCode = 1;
}

main();

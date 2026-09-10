#!/usr/bin/env node
/**
 * recovery-ledger-report.mjs
 *
 * Turns a recovery ledger produced by reconcile-rescue-refs.mjs into:
 *   1. a human-readable markdown summary (committed alongside the JSON), and
 *   2. a compact `coordination_tasks` INSERT for the durable queue-side ledger.
 *
 * The SQL is deliberately compact: one row per evidence item carrying the
 * timestamp key, short sha, classification and file count, plus a pointer to
 * the committed JSON ledger which holds the full record. Long ref names and
 * subjects live in git, not in the queue table.
 *
 * Usage:
 *   node scripts/recovery-ledger-report.mjs --ledger docs/recovery-ledger-X.json \
 *        [--md docs/recovery-ledger-X.md] [--sql /tmp/ledger.sql] [--project tomorrow]
 */

import { readFileSync, writeFileSync } from 'node:fs';

const args = process.argv.slice(2);
const argOf = (n, d) => {
  const i = args.indexOf(`--${n}`);
  return i >= 0 && args[i + 1] ? args[i + 1] : d;
};

const LEDGER = argOf('ledger');
if (!LEDGER) {
  console.error('--ledger is required');
  process.exit(2);
}
const MD = argOf('md', LEDGER.replace(/\.json$/, '.md'));
const SQL = argOf('sql', '');
const PROJECT = argOf('project', 'unknown');

/**
 * Two reconcilers in this repo emit recovery ledgers and they do not agree on
 * field names. scripts/reconcile-rescue-refs.mjs writes {audit_fingerprint,
 * total_items, unknown_items, summary, records[{source_sha, source_subject,
 * touched_file_count}]}; tools/reconcile-local-evidence.mjs writes {fingerprint,
 * total, unknown, counts, items[{sha, subject, files}]}. Both classify the same
 * five buckets over the same kinds of evidence, so the reporting layer should
 * read either rather than forcing a caller to pick the one reconciler this
 * script happened to be written against — pointing it at a local-evidence
 * ledger previously died on `ledger.records.filter is not a function`, which
 * left the local-branches and rescue-refs kinds with no reporting path at all.
 *
 * Normalising on read (rather than changing either producer) keeps ledgers of
 * both shapes that are already on disk readable. A ledger is an audit record;
 * rewriting old ones to suit a new reader would defeat the point of keeping it.
 */
function normaliseLedger(raw) {
  if (Array.isArray(raw.records)) return raw; // already the reference shape

  const items = Array.isArray(raw.items) ? raw.items : [];
  return {
    ...raw,
    audit_fingerprint: raw.audit_fingerprint ?? raw.fingerprint ?? '',
    total_items: raw.total_items ?? raw.total ?? items.length,
    // `unknown` is a count, and 0 is the success case — ?? not ||.
    unknown_items: raw.unknown_items ?? raw.unknown ?? 0,
    summary: raw.summary ?? raw.counts ?? {},
    generator: raw.generator ?? 'reconcile-local-evidence.mjs',
    records: items.map((it) => ({
      ...it,
      source: it.source ?? it.ref ?? '',
      source_sha: it.source_sha ?? it.sha ?? '',
      source_subject: it.source_subject ?? it.subject ?? '',
      touched_file_count:
        it.touched_file_count ?? it.file_count ?? (Array.isArray(it.files) ? it.files.length : 0),
    })),
  };
}

const ledger = normaliseLedger(JSON.parse(readFileSync(LEDGER, 'utf8')));

const ORDER = [
  'RECOVERABLE_VALUE',
  'CONFLICTED_NEEDS_FOCUSED_TASK',
  'ACTIVE_IN_ANOTHER_TASK',
  'SUPERSEDED_BY_NEWER',
  'ALREADY_PRESENT',
];

const DISPOSITION = {
  ALREADY_PRESENT: 'no action — value already on the default branch',
  SUPERSEDED_BY_NEWER: 'no action — newer implementation on the default branch wins',
  ACTIVE_IN_ANOTHER_TASK: 'no action — leave to the owning branch/task; do not duplicate',
  RECOVERABLE_VALUE: 'queue a focused recovery task; apply in a fresh isolated worktree',
  CONFLICTED_NEEDS_FOCUSED_TASK: 'queue a focused conflict-resolution task; never force-overwrite',
};

const CODE = {
  ALREADY_PRESENT: 'P',
  SUPERSEDED_BY_NEWER: 'S',
  ACTIVE_IN_ANOTHER_TASK: 'A',
  RECOVERABLE_VALUE: 'R',
  CONFLICTED_NEEDS_FOCUSED_TASK: 'C',
};

const remaining = ledger.records.filter(
  (r) => r.classification === 'RECOVERABLE_VALUE' || r.classification === 'CONFLICTED_NEEDS_FOCUSED_TASK',
);

const esc = (s) => String(s ?? '').replace(/\|/g, '\\|');

function markdown() {
  const l = [];
  l.push(`# ChatGPT/Codex local build-evidence reconciliation — ${PROJECT}`, '');
  l.push(`Audit fingerprint: \`${ledger.audit_fingerprint}\``, '');
  l.push(`Base: \`${ledger.base}\` @ \`${ledger.base_sha.slice(0, 12)}\` · generated ${ledger.generated_at}`, '');
  l.push('Regenerate with:', '', '```bash');
  // Name the reconciler that actually produced this ledger. The two take
  // different flags (--json/--kind vs --out), so one hardcoded command cannot
  // reproduce both, and a regenerate hint that does not regenerate is worse
  // than none.
  if (ledger.generator === 'reconcile-local-evidence.mjs') {
    l.push(`node tools/reconcile-local-evidence.mjs --kind ${ledger.kind} \\`);
    l.push(`  --base ${ledger.base} \\`);
    l.push(`  --fingerprint ${ledger.audit_fingerprint} \\`);
    l.push(`  --json ${LEDGER}`);
  } else {
    l.push(`node scripts/reconcile-rescue-refs.mjs --base ${ledger.base} \\`);
    l.push(`  --fingerprint ${ledger.audit_fingerprint} \\`);
    l.push(`  --out ${LEDGER}`);
  }
  l.push(`node scripts/recovery-ledger-report.mjs --ledger ${LEDGER} --project ${PROJECT}`);
  l.push('```', '');
  l.push('## Result', '');
  l.push(
    `**${ledger.total_items} evidence items classified, ${ledger.unknown_items} UNKNOWN.** ` +
      'The evidence source was treated as read-only throughout — nothing was deleted, reset, cleaned, ' +
      'popped or moved. Classification is recomputed from live refs, not from the snapshot in the task prompt.',
    '',
  );
  l.push('| Classification | Count | Disposition |', '|---|---:|---|');
  for (const k of ORDER) if (ledger.summary[k]) l.push(`| ${k} | ${ledger.summary[k]} | ${DISPOSITION[k]} |`);
  l.push('');
  l.push('## Items with remaining value', '');
  if (!remaining.length) {
    l.push('None. Every item is already present, superseded by newer work on the default branch, or ' +
      'carried by a live agent branch — so re-applying any of it would duplicate queued work.', '');
  } else {
    l.push(
      `${remaining.length} item(s) below keep durable provenance in \`${LEDGER}\` (source ref, sha, ` +
        'subject, touched files, carrier branches). None were applied in this pass — per the coordination ' +
        'rule, conflicts get a focused follow-up rather than a forced overwrite.',
      '',
    );
    l.push('| Source ref | Class | Files | Subject |', '|---|---|---:|---|');
    for (const r of remaining) {
      l.push(
        `| \`${r.source.replace('refs/orch-rescue/', '')}\` | ${r.classification} | ` +
          `${r.touched_file_count} | ${esc(r.source_subject).slice(0, 80)} |`,
      );
    }
    l.push('');
  }
  l.push('## Notes', '');
  l.push('- `ACTIVE_IN_ANOTHER_TASK` items are already carried by a live `agent/*` branch; re-applying them here would duplicate queued work.');
  l.push('- `SUPERSEDED_BY_NEWER` is decided by commit time on the base for every source file the rescue commit touches — the newest/most complete implementation wins.');
  l.push('- Refs whose only content is generated (`node_modules`, `.vite`, `.nuxt`, `dist`, `coverage`, …) are classified `ALREADY_PRESENT`: a vitest cache is build noise, not lost work, and must not spawn a follow-up task that can never produce a meaningful diff.');
  l.push('');
  return l.join('\n');
}

/**
 * One coordination_tasks row per evidence item. Encoded as a single delimited
 * string expanded server-side so the statement stays small enough to ship in
 * one round trip even for 500+ item evidence sets.
 */
function sql() {
  const rows = ledger.records.map((r) =>
    [
      r.source.replace('refs/orch-rescue/', '').slice(0, 15),
      r.source_sha.slice(0, 12),
      CODE[r.classification],
      r.touched_file_count,
    ].join('~'),
  );
  const lit = (s) => `'${String(s).replace(/'/g, "''")}'`;
  return (
    'INSERT INTO coordination_tasks (task_type,payload,status,created_at,updated_at) ' +
    "SELECT 'recovery_ledger', jsonb_build_object(" +
    `'fp',${lit(ledger.audit_fingerprint.slice(0, 16))},` +
    `'proj',${lit(PROJECT)},` +
    `'ledger',${lit(LEDGER)},` +
    `'base_sha',${lit(ledger.base_sha.slice(0, 12))},` +
    "'ts',p[1],'sha',p[2]," +
    "'cls',(CASE p[3] WHEN 'P' THEN 'ALREADY_PRESENT' WHEN 'S' THEN 'SUPERSEDED_BY_NEWER' " +
    "WHEN 'A' THEN 'ACTIVE_IN_ANOTHER_TASK' WHEN 'R' THEN 'RECOVERABLE_VALUE' " +
    "ELSE 'CONFLICTED_NEEDS_FOCUSED_TASK' END)," +
    "'files',p[4]::int)::text, " +
    "(CASE WHEN p[3] IN ('R','C') THEN 'pending' ELSE 'resolved' END), now(), now() " +
    `FROM (SELECT string_to_array(x,'~') AS p FROM unnest(string_to_array(${lit(rows.join('|'))},'|')) AS x) q;`
  );
}

writeFileSync(MD, markdown());
const statement = sql();
if (SQL) writeFileSync(SQL, `${statement}\n`);

console.log(`markdown -> ${MD}`);
console.log(`items: ${ledger.total_items} · unknown: ${ledger.unknown_items} · remaining-value: ${remaining.length}`);
console.log(`sql: ${statement.length} bytes${SQL ? ` -> ${SQL}` : ' (pass --sql <path> to write)'}`);

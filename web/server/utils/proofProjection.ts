/**
 * proofProjection.ts — the operator-facing half of the canonical proof ledger.
 *
 * This is a deliberate mirror of runner/canonical_proof_ledger.py. The snapshot API and
 * the proof UI used to compute "is it shipped?" independently of the runner, which is how
 * the same task could read shipped in the dashboard and unverified in the promotion scan.
 * Both sides now implement the SAME five rules, and the fixtures on both sides assert the
 * same verdicts, so a change to one that is not made to the other fails a test.
 *
 * THE RULES:
 *   1. Every PASS links to its receipt. No receipt, no pass — enforced, not documented.
 *   2. Unknown evidence renders UNKNOWN or PENDING. Never PASS.
 *   3. MERGED proves integration reachability only.
 *   4. DEPLOYED_AND_VERIFIED needs the exact live release sha AND a task-defined
 *      production journey receipt. Either alone is PENDING.
 *   5. Every ledger read is paginated — PostgREST silently caps a response at 1000 rows,
 *      so an un-paginated read reports "no evidence" for everything past row 1000.
 */

export type Verdict = 'PASS' | 'PENDING' | 'UNKNOWN' | 'FAIL';

export type ProofLevel =
  | 'NO_EVIDENCE'
  | 'ARTIFACT'
  | 'MERGED'
  | 'RELEASED'
  | 'DEPLOYED_AND_VERIFIED';

/** Weakest to strongest. Order is asserted by the fixtures. */
export const LEVELS: readonly ProofLevel[] = [
  'NO_EVIDENCE',
  'ARTIFACT',
  'MERGED',
  'RELEASED',
  'DEPLOYED_AND_VERIFIED',
] as const;

export const VERDICTS: readonly Verdict[] = ['PASS', 'PENDING', 'UNKNOWN', 'FAIL'] as const;

/** PostgREST's implicit response cap. Reads that ignore it silently truncate. */
export const POSTGREST_IMPLICIT_LIMIT = 1000;

/** deploy_status values that mean the release is actually live. */
const LIVE_RELEASE_STATES = new Set(['success', 'deployed', 'ready', 'deployed_and_verified']);
/** deploy_status values that positively disprove liveness. */
const DEAD_RELEASE_STATES = new Set(['error', 'failed', 'canceled', 'cancelled', 'blocked']);

export const STALE_RELEASE_NOTE = 'release predates the artifact it would certify';

export interface Receipt {
  kind: string;
  /** What an auditor can go look at: a commit sha, a release id, a URL. */
  ref: string;
  detail: string;
}

export interface TaskRow {
  slug?: string | null;
  id?: string | null;
  state?: string | null;
  artifact_commit?: string | null;
  artifact_branch?: string | null;
}

export interface ArtifactRow {
  slug?: string | null;
  branch?: string | null;
  commit_sha?: string | null;
  captured_at?: string | null;
}

export interface ReleaseRow {
  id?: string | null;
  project?: string | null;
  to_sha?: string | null;
  deploy_status?: string | null;
  vercel_url?: string | null;
  created_at?: string | null;
}

export interface JourneyRow {
  release_sha?: string | null;
  journey?: string | null;
  ok?: boolean | null;
  url?: string | null;
  recorded_at?: string | null;
}

export interface Evidence {
  artifacts: Map<string, ArtifactRow>;
  releases: ReleaseRow[];
  journeys: Map<string, JourneyRow[]>;
  /** Tables that could not be READ. Distinct from tables that read cleanly and are empty. */
  readErrors: string[];
}

export interface ProofEntry {
  slug: string;
  state: string;
  level: ProofLevel;
  verdict: Verdict;
  receipt: Receipt | null;
  reasons: string[];
}

export interface ProofLedger {
  project: string;
  entries: ProofEntry[];
  summary: Record<Verdict, number>;
  byLevel: Record<ProofLevel, number>;
  readErrors: string[];
}

export function levelRank(level: string): number {
  return (LEVELS as readonly string[]).indexOf(level);
}

/**
 * Build a receipt, or null when there is nothing to point at.
 *
 * A receipt with a blank ref is not a receipt: it is an empty promise, and letting one
 * through would satisfy rule 1 syntactically while defeating it entirely.
 */
export function makeReceipt(kind: string, ref: unknown, detail = ''): Receipt | null {
  const value = ref === null || ref === undefined ? '' : String(ref).trim();
  if (!value) return null;
  return { kind: String(kind), ref: value, detail: String(detail ?? '') };
}

function sha(value: unknown): string {
  return value === null || value === undefined ? '' : String(value).trim().toLowerCase();
}

/**
 * True when two shas name the same commit, allowing an abbreviated form.
 *
 * Abbreviation is accepted only at >= 7 characters, git's own minimum for an unambiguous
 * short sha. Below that a prefix match is noise, not evidence.
 */
export function shaMatches(left: unknown, right: unknown): boolean {
  const a = sha(left);
  const b = sha(right);
  if (!a || !b) return false;
  if (a === b) return true;
  const [shorter, longer] = a.length < b.length ? [a, b] : [b, a];
  return shorter.length >= 7 && longer.startsWith(shorter);
}

export type PageReader<T> = (limit: number, offset: number) => Promise<T[]>;

/**
 * Read every row, in pages, and report whether the read completed.
 *
 * Returns `{ rows, ok }`. `ok: false` means we could not finish reading — which the
 * caller must turn into UNKNOWN, never into an absence of evidence. That distinction is
 * the whole reason this returns a pair instead of an array.
 */
export async function paginate<T>(
  read: PageReader<T>,
  { pageSize = POSTGREST_IMPLICIT_LIMIT, maxRows = 200_000 } = {},
): Promise<{ rows: T[]; ok: boolean }> {
  const size = Math.max(1, Math.min(pageSize, POSTGREST_IMPLICIT_LIMIT));
  const rows: T[] = [];
  let offset = 0;
  for (;;) {
    const want = Math.min(size, maxRows - rows.length);
    if (want <= 0) break;
    let page: T[];
    try {
      page = (await read(want, offset)) ?? [];
    } catch {
      return { rows, ok: false };
    }
    rows.push(...page);
    if (page.length < want) break;
    offset += want;
  }
  return { rows, ok: true };
}

/** Index raw rows into the Evidence bundle the projection consumes. */
export function buildEvidence(
  artifacts: ArtifactRow[],
  releases: ReleaseRow[],
  journeys: JourneyRow[],
  readErrors: string[] = [],
): Evidence {
  const artifactIndex = new Map<string, ArtifactRow>();
  for (const row of artifacts ?? []) {
    if (row?.slug) artifactIndex.set(row.slug, row);
  }
  const journeyIndex = new Map<string, JourneyRow[]>();
  for (const row of journeys ?? []) {
    const key = sha(row?.release_sha);
    if (!key) continue;
    const list = journeyIndex.get(key) ?? [];
    list.push(row);
    journeyIndex.set(key, list);
  }
  return {
    artifacts: artifactIndex,
    releases: releases ?? [],
    journeys: journeyIndex,
    readErrors: readErrors ?? [],
  };
}

function liveReleaseFor(
  artifactSha: string,
  releases: ReleaseRow[],
  artifactAt?: string | null,
): { release: ReleaseRow | null; reason: string } {
  if (!sha(artifactSha)) return { release: null, reason: 'task has no artifact commit to look for' };

  const matching = (releases ?? []).filter(r => shaMatches(r?.to_sha, artifactSha));
  if (matching.length === 0) {
    return { release: null, reason: 'no release names this artifact commit as its head' };
  }

  for (const rel of matching) {
    const status = String(rel?.deploy_status ?? '').trim().toLowerCase();
    if (DEAD_RELEASE_STATES.has(status)) continue;
    if (!LIVE_RELEASE_STATES.has(status)) continue;
    // A release cut BEFORE the artifact was captured cannot certify it even though the
    // shas match — that combination means the sha was back-filled onto an older release
    // row, which is exactly the stale-release defect.
    const created = String(rel?.created_at ?? '');
    if (artifactAt && created && created < String(artifactAt)) continue;
    return { release: rel, reason: '' };
  }

  const stale = artifactAt
    ? matching.some(r => r?.created_at && String(r.created_at) < String(artifactAt))
    : false;
  if (stale) return { release: null, reason: STALE_RELEASE_NOTE };

  const dead = matching.find(r =>
    DEAD_RELEASE_STATES.has(String(r?.deploy_status ?? '').trim().toLowerCase()),
  );
  if (dead) {
    return {
      release: null,
      reason: `release ${dead.id} did not deploy (deploy_status=${dead.deploy_status})`,
    };
  }
  return { release: null, reason: 'release exists but its deploy_status does not say it is live' };
}

function journeyReceipt(
  releaseSha: unknown,
  journeys: Map<string, JourneyRow[]>,
  requiredJourney?: string | null,
): { receipt: Receipt | null; reason: string } {
  const rows = journeys.get(sha(releaseSha)) ?? [];
  if (rows.length === 0) {
    return { receipt: null, reason: 'no production journey receipt for this release sha' };
  }

  let candidates = rows;
  if (requiredJourney) {
    candidates = rows.filter(r => String(r?.journey ?? '') === String(requiredJourney));
    if (candidates.length === 0) {
      // A receipt for some OTHER journey does not satisfy a task-defined one; that
      // substitution is how a generic health check ends up certifying a feature nobody
      // exercised.
      return { receipt: null, reason: `no receipt for the task-defined journey "${requiredJourney}"` };
    }
  }

  const passing = candidates.filter(r => r?.ok === true);
  if (passing.length === 0) {
    return { receipt: null, reason: 'production journey receipt exists but did not pass' };
  }

  const row = passing[passing.length - 1]!;
  return {
    receipt: makeReceipt('production_journey', row.url ?? sha(releaseSha),
      `journey=${row.journey} recorded_at=${row.recorded_at}`),
    reason: '',
  };
}

/**
 * Project ONE task into a verdict. Never throws.
 *
 * PASS is only reachable from the branch that already holds a receipt, so rule 1 is a
 * property of the control flow rather than a check that can be forgotten.
 */
export function projectTask(
  task: TaskRow | null | undefined,
  evidence: Partial<Evidence>,
  requiredJourney?: string | null,
): ProofEntry {
  try {
    const row: TaskRow = task && typeof task === 'object' ? task : {};
    const slug = String(row.slug ?? row.id ?? '');
    const state = String(row.state ?? '').trim();
    const reasons: string[] = [];
    const readErrors = evidence?.readErrors ?? [];

    const artifact = evidence?.artifacts?.get(slug);
    const artifactSha = sha(artifact?.commit_sha ?? row.artifact_commit);

    if (!artifactSha) {
      let verdict: Verdict;
      if (readErrors.includes('task_artifacts')) {
        reasons.push('task_artifacts could not be read; evidence is unknown, not absent');
        verdict = 'UNKNOWN';
      } else {
        reasons.push('no artifact commit recorded for this task');
        verdict = state === 'MERGED' || state === 'DEPLOYED_AND_VERIFIED' ? 'UNKNOWN' : 'PENDING';
      }
      // A task claiming MERGED with no artifact is the phantom-merge defect. Reported at
      // NO_EVIDENCE regardless of the state column, because the state column is the
      // claim, not the proof.
      if (state === 'MERGED') {
        reasons.push('state says MERGED but there is no artifact — phantom merge');
      }
      return { slug, state, level: 'NO_EVIDENCE', verdict, receipt: null, reasons };
    }

    const artifactReceipt = makeReceipt('artifact_commit', artifactSha,
      `branch=${artifact?.branch ?? row.artifact_branch ?? ''}`);

    if (state !== 'MERGED' && state !== 'DEPLOYED_AND_VERIFIED') {
      reasons.push(`artifact exists; task state is ${state || 'unset'}, not merged`);
      return { slug, state, level: 'ARTIFACT', verdict: 'PENDING', receipt: artifactReceipt, reasons };
    }

    // Rule 3: MERGED is a receipted fact about the repository and nothing more. The level
    // stops here and nothing downstream may read it as production evidence.
    const { release, reason } = liveReleaseFor(artifactSha, evidence?.releases ?? [],
      artifact?.captured_at);
    if (!release) {
      reasons.push('MERGED proves integration reachability only');
      reasons.push(reason);
      let verdict: Verdict = 'PENDING';
      if (readErrors.includes('releases')) {
        reasons.push('releases could not be read; deployment evidence is unknown');
        verdict = 'UNKNOWN';
      }
      return { slug, state, level: 'MERGED', verdict, receipt: artifactReceipt, reasons };
    }

    const releaseReceipt = makeReceipt('release', release.id,
      `to_sha=${release.to_sha} status=${release.deploy_status} url=${release.vercel_url ?? ''}`);

    const journey = journeyReceipt(release.to_sha, evidence?.journeys ?? new Map(), requiredJourney);
    if (!journey.receipt) {
      reasons.push('live release contains the artifact commit');
      reasons.push(journey.reason);
      return { slug, state, level: 'RELEASED', verdict: 'PENDING', receipt: releaseReceipt, reasons };
    }

    reasons.push('exact live release sha plus a passing production journey receipt');
    return {
      slug, state, level: 'DEPLOYED_AND_VERIFIED', verdict: 'PASS',
      receipt: journey.receipt, reasons,
    };
  } catch (error) {
    // UNKNOWN rather than PENDING on purpose: a crash means we do not know, and "we do
    // not know" must never look like progress.
    return {
      slug: String(task?.slug ?? ''), state: '', level: 'NO_EVIDENCE', verdict: 'UNKNOWN',
      receipt: null, reasons: [`projection failed: ${String(error)}`],
    };
  }
}

export function buildLedger(
  tasks: TaskRow[],
  evidence: Evidence,
  project = '',
  requiredJourneys: Record<string, string> = {},
): ProofLedger {
  const entries = (tasks ?? []).map(t => projectTask(t, evidence, requiredJourneys[String(t?.slug ?? '')]));

  const summary = { PASS: 0, PENDING: 0, UNKNOWN: 0, FAIL: 0 } as Record<Verdict, number>;
  const byLevel = {
    NO_EVIDENCE: 0, ARTIFACT: 0, MERGED: 0, RELEASED: 0, DEPLOYED_AND_VERIFIED: 0,
  } as Record<ProofLevel, number>;
  for (const entry of entries) {
    summary[entry.verdict] += 1;
    byLevel[entry.level] += 1;
  }

  return { project, entries, summary, byLevel, readErrors: evidence?.readErrors ?? [] };
}

/**
 * Assert the ledger's own invariants. Returns violations; empty means clean.
 *
 * Safe to call in production — it reads, it does not write. An invariant that lives only
 * in a docstring is an invariant that drifts.
 */
export function auditLedger(ledger: Pick<ProofLedger, 'entries'> | null | undefined): string[] {
  const violations: string[] = [];
  for (const entry of ledger?.entries ?? []) {
    if (entry.verdict === 'PASS' && !entry.receipt) {
      violations.push(`${entry.slug}: PASS without a receipt`);
    }
    if (entry.verdict === 'PASS' && entry.level !== 'DEPLOYED_AND_VERIFIED') {
      violations.push(`${entry.slug}: PASS at level ${entry.level}, only DEPLOYED_AND_VERIFIED may pass`);
    }
    if (entry.level === 'MERGED' && entry.verdict === 'PASS') {
      violations.push(`${entry.slug}: MERGED rendered as PASS — MERGED proves reachability only`);
    }
    if (!(VERDICTS as readonly string[]).includes(entry.verdict)) {
      violations.push(`${entry.slug}: unrecognised verdict ${entry.verdict}`);
    }
    if (levelRank(entry.level) < 0) {
      violations.push(`${entry.slug}: unrecognised level ${entry.level}`);
    }
    if (entry.receipt && !entry.receipt.ref) {
      violations.push(`${entry.slug}: receipt with a blank ref`);
    }
  }
  return violations;
}

/**
 * Shape the ledger for the snapshot API and the proof UI.
 *
 * Lossy in one direction only: it drops internal fields, never a reason. The UI's job is
 * to show WHY something is not proven, so the reasons are the payload.
 */
export function snapshot(ledger: ProofLedger | null | undefined) {
  return {
    project: ledger?.project ?? '',
    summary: ledger?.summary ?? { PASS: 0, PENDING: 0, UNKNOWN: 0, FAIL: 0 },
    byLevel: ledger?.byLevel ?? {},
    readErrors: ledger?.readErrors ?? [],
    entries: (ledger?.entries ?? []).map(e => ({
      slug: e.slug,
      level: e.level,
      verdict: e.verdict,
      receipt: e.receipt,
      reasons: e.reasons,
    })),
  };
}

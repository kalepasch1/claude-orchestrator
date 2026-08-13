/**
 * Regression fixtures for proofProjection — the operator-facing half of the ledger.
 *
 * Same four defects as runner/tests/test_canonical_proof_ledger.py, asserted to the same
 * verdicts. The pairing is the point: if one side's rules change and the other's do not,
 * one of these two suites goes red.
 */
import { describe, expect, it } from 'vitest';

import {
  POSTGREST_IMPLICIT_LIMIT,
  STALE_RELEASE_NOTE,
  auditLedger,
  buildEvidence,
  buildLedger,
  levelRank,
  makeReceipt,
  paginate,
  projectTask,
  shaMatches,
  snapshot,
  type ArtifactRow,
  type JourneyRow,
  type ReleaseRow,
  type TaskRow,
} from './proofProjection';

const SHA = 'a'.repeat(40);
const OTHER_SHA = 'b'.repeat(40);

const artifact = (slug: string, commit_sha: string, captured_at = '2026-08-01T00:00:00Z'): ArtifactRow =>
  ({ slug, commit_sha, branch: 'agent/x', captured_at });

const release = (
  id: string, to_sha: string, deploy_status = 'success', created_at = '2026-08-02T00:00:00Z',
): ReleaseRow => ({ id, project: 'beethoven', to_sha, deploy_status, created_at, vercel_url: `https://example.invalid/${id}` });

const journey = (
  release_sha: string, name = 'checkout', ok = true,
): JourneyRow => ({ release_sha, journey: name, ok, url: `https://example.invalid/j/${name}`, recorded_at: '2026-08-03T00:00:00Z' });

const task = (slug: string, state: string, artifact_commit?: string): TaskRow =>
  ({ id: slug, slug, state, artifact_commit: artifact_commit ?? null, artifact_branch: 'agent/x' });

/** A page reader that behaves like PostgREST: never returns more than the implicit cap. */
function pageReaderOver<T>(rows: T[], fail = false) {
  return async (limit: number, offset: number): Promise<T[]> => {
    if (fail) throw new Error('unreadable');
    return rows.slice(offset, offset + Math.min(limit, POSTGREST_IMPLICIT_LIMIT));
  };
}

describe('phantom MERGED', () => {
  const evidence = buildEvidence([artifact('real', SHA)], [], []);

  it('is not a pass', () => {
    const entry = projectTask(task('phantom', 'MERGED'), evidence);
    expect(entry.verdict).not.toBe('PASS');
    expect(entry.level).toBe('NO_EVIDENCE');
  });

  it('is named as such, so the UI can say why', () => {
    const entry = projectTask(task('phantom', 'MERGED'), evidence);
    expect(entry.reasons.some(r => r.includes('phantom merge'))).toBe(true);
  });

  it('carries no receipt', () => {
    expect(projectTask(task('phantom', 'MERGED'), evidence).receipt).toBeNull();
  });
});

describe('missing artifact', () => {
  it('treats an unreadable table as UNKNOWN, not as absent', () => {
    const evidence = buildEvidence([], [], [], ['task_artifacts']);
    const entry = projectTask(task('t1', 'MERGED'), evidence);
    expect(entry.verdict).toBe('UNKNOWN');
    expect(entry.reasons.some(r => r.includes('unknown, not absent'))).toBe(true);
  });

  it('treats a clean empty read on a queued task as PENDING', () => {
    const evidence = buildEvidence([artifact('other', SHA)], [], []);
    expect(projectTask(task('t1', 'QUEUED'), evidence).verdict).toBe('PENDING');
  });

  it('does not confuse an empty table with an unreadable one', async () => {
    expect(await paginate(pageReaderOver<ArtifactRow>([]))).toEqual({ rows: [], ok: true });
    expect(await paginate(pageReaderOver<ArtifactRow>([], true))).toEqual({ rows: [], ok: false });
  });
});

describe('stale release', () => {
  it('does not let a release cut before the artifact certify it', () => {
    const evidence = buildEvidence(
      [artifact('t1', SHA, '2026-08-05T00:00:00Z')],
      [release('r1', SHA, 'success', '2026-08-01T00:00:00Z')],
      [journey(SHA)],
    );
    const entry = projectTask(task('t1', 'MERGED', SHA), evidence);
    expect(entry.level).toBe('MERGED');
    expect(entry.verdict).not.toBe('PASS');
    expect(entry.reasons).toContain(STALE_RELEASE_NOTE);
  });

  it('reports a failed release with its status', () => {
    const evidence = buildEvidence([artifact('t1', SHA)], [release('r1', SHA, 'error')], [journey(SHA)]);
    const entry = projectTask(task('t1', 'MERGED', SHA), evidence);
    expect(entry.verdict).not.toBe('PASS');
    expect(entry.reasons.some(r => r.includes('did not deploy'))).toBe(true);
  });

  it('does not accept a release for a different sha', () => {
    const evidence = buildEvidence([artifact('t1', SHA)], [release('r1', OTHER_SHA)], [journey(OTHER_SHA)]);
    const entry = projectTask(task('t1', 'MERGED', SHA), evidence);
    expect(entry.level).toBe('MERGED');
    expect(entry.reasons.some(r => r.includes('no release names this artifact commit'))).toBe(true);
  });
});

describe('evidence beyond PostgREST row 1000', () => {
  const artifacts = Array.from({ length: 1500 }, (_, i) => artifact(`t${i}`, i.toString(16).padStart(40, '0')));

  it('pins the premise: one unpaginated read truncates at the cap', async () => {
    const read = pageReaderOver(artifacts);
    expect((await read(5000, 0)).length).toBe(POSTGREST_IMPLICIT_LIMIT);
  });

  it('reads past the cap', async () => {
    const { rows, ok } = await paginate(pageReaderOver(artifacts));
    expect(ok).toBe(true);
    expect(rows.length).toBe(1500);
  });

  it('verifies evidence sitting at row 1400', async () => {
    const sha1400 = (1400).toString(16).padStart(40, '0');
    const { rows } = await paginate(pageReaderOver(artifacts));
    const evidence = buildEvidence(rows, [release('r', sha1400)], [journey(sha1400)]);
    const entry = projectTask(task('t1400', 'MERGED', sha1400), evidence);
    expect(entry.level).toBe('DEPLOYED_AND_VERIFIED');
    expect(entry.verdict).toBe('PASS');
    expect(entry.receipt).not.toBeNull();
  });

  it('respects maxRows', async () => {
    const { rows } = await paginate(pageReaderOver(artifacts), { maxRows: 1200 });
    expect(rows.length).toBe(1200);
  });

  it('returns what it read when a later page fails, and says it did not finish', async () => {
    let calls = 0;
    const flaky = async (limit: number, offset: number) => {
      calls += 1;
      if (calls > 1) throw new Error('boom');
      return artifacts.slice(offset, offset + limit);
    };
    const { rows, ok } = await paginate(flaky);
    expect(ok).toBe(false);
    expect(rows.length).toBe(POSTGREST_IMPLICIT_LIMIT);
  });
});

describe('MERGED proves integration reachability only', () => {
  it('is PENDING at level MERGED when no release contains it', () => {
    const evidence = buildEvidence([artifact('t1', SHA)], [], []);
    const entry = projectTask(task('t1', 'MERGED', SHA), evidence);
    expect(entry.level).toBe('MERGED');
    expect(entry.verdict).toBe('PENDING');
    expect(entry.reasons).toContain('MERGED proves integration reachability only');
  });

  it('is rejected by the audit if something forges it into a PASS', () => {
    const forged = {
      entries: [{
        slug: 'x', state: 'MERGED', level: 'MERGED' as const, verdict: 'PASS' as const,
        receipt: makeReceipt('artifact_commit', SHA), reasons: [],
      }],
    };
    expect(auditLedger(forged).some(v => v.includes('MERGED rendered as PASS'))).toBe(true);
  });
});

describe('DEPLOYED_AND_VERIFIED needs both halves', () => {
  const withEvidence = (releases: ReleaseRow[], journeys: JourneyRow[], required?: string) =>
    projectTask(task('t1', 'MERGED', SHA), buildEvidence([artifact('t1', SHA)], releases, journeys), required);

  it('passes when the live release sha and a passing journey receipt are both present', () => {
    const entry = withEvidence([release('r1', SHA)], [journey(SHA)]);
    expect(entry.level).toBe('DEPLOYED_AND_VERIFIED');
    expect(entry.verdict).toBe('PASS');
    expect(entry.receipt?.kind).toBe('production_journey');
  });

  it('is PENDING with a release but no journey receipt', () => {
    const entry = withEvidence([release('r1', SHA)], []);
    expect(entry.level).toBe('RELEASED');
    expect(entry.verdict).toBe('PENDING');
  });

  it('does not pass on a failing journey receipt', () => {
    const entry = withEvidence([release('r1', SHA)], [journey(SHA, 'checkout', false)]);
    expect(entry.verdict).not.toBe('PASS');
    expect(entry.reasons.some(r => r.includes('did not pass'))).toBe(true);
  });

  it('does not let another journey satisfy a task-defined one', () => {
    const entry = withEvidence([release('r1', SHA)], [journey(SHA, 'healthcheck')], 'checkout');
    expect(entry.level).toBe('RELEASED');
    expect(entry.verdict).not.toBe('PASS');
    expect(entry.reasons.some(r => r.includes('checkout'))).toBe(true);
  });

  it('accepts an abbreviated release sha but not a 6-character prefix', () => {
    expect(withEvidence([release('r1', SHA.slice(0, 12))], [journey(SHA.slice(0, 12))]).verdict).toBe('PASS');
    expect(shaMatches(SHA, SHA.slice(0, 6))).toBe(false);
    expect(shaMatches(SHA, SHA.slice(0, 7))).toBe(true);
  });
});

describe('invariants', () => {
  it('never emits a PASS without a receipt', () => {
    const artifacts = Array.from({ length: 20 }, (_, i) => artifact(`t${i}`, i.toString(16).padStart(40, '0')));
    const releases = Array.from({ length: 10 }, (_, i) => release(`r${i}`, i.toString(16).padStart(40, '0')));
    const journeys = Array.from({ length: 5 }, (_, i) => journey(i.toString(16).padStart(40, '0')));
    const tasks = Array.from({ length: 20 }, (_, i) => task(`t${i}`, 'MERGED', i.toString(16).padStart(40, '0')));

    const ledger = buildLedger(tasks, buildEvidence(artifacts, releases, journeys), 'beethoven');
    expect(auditLedger(ledger)).toEqual([]);
    for (const entry of ledger.entries) {
      if (entry.verdict === 'PASS') expect(entry.receipt?.ref).toBeTruthy();
    }
  });

  it('rejects a receipt with a blank ref', () => {
    expect(makeReceipt('artifact_commit', '')).toBeNull();
    expect(makeReceipt('artifact_commit', null)).toBeNull();
    expect(makeReceipt('artifact_commit', '   ')).toBeNull();
  });

  it('never throws, and never passes, on garbage input', () => {
    for (const bad of [null, undefined, {} as TaskRow, { slug: null } as TaskRow]) {
      const entry = projectTask(bad, buildEvidence([], [], []));
      expect(['PASS', 'PENDING', 'UNKNOWN', 'FAIL']).toContain(entry.verdict);
      expect(entry.verdict).not.toBe('PASS');
    }
  });

  it('counts every entry exactly once', () => {
    const evidence = buildEvidence([artifact('t1', SHA)], [], []);
    const ledger = buildLedger([task('t1', 'MERGED', SHA), task('t2', 'QUEUED')], evidence);
    expect(Object.values(ledger.summary).reduce((a, b) => a + b, 0)).toBe(2);
    expect(Object.values(ledger.byLevel).reduce((a, b) => a + b, 0)).toBe(2);
  });

  it('keeps the reasons in the snapshot the UI renders', () => {
    const ledger = buildLedger([task('t1', 'MERGED')], buildEvidence([], [], []));
    const snap = snapshot(ledger);
    expect(snap.entries[0]!.reasons.length).toBeGreaterThan(0);
    expect(Object.keys(snap.entries[0]!).sort())
      .toEqual(['level', 'reasons', 'receipt', 'slug', 'verdict']);
  });

  it('orders levels weakest to strongest', () => {
    expect(levelRank('NO_EVIDENCE')).toBeLessThan(levelRank('MERGED'));
    expect(levelRank('MERGED')).toBeLessThan(levelRank('DEPLOYED_AND_VERIFIED'));
    expect(levelRank('NOT_A_LEVEL')).toBe(-1);
  });
});

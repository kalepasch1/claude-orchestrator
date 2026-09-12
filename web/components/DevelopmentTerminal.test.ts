import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import {
  completionProofSummary,
  completionToEvents,
  projectCompletionSteps,
  toChecklistStatus,
  type CompletionRecord,
} from './developmentTerminalProof';

const SFC = join(__dirname, 'DevelopmentTerminal.vue');

describe('Madeus terminal — proof projection', () => {
  it('a completion with no evidence renders no passes at all', () => {
    const steps = projectCompletionSteps({ slug: 'x', state: 'DONE' });
    expect(steps.length).toBeGreaterThan(0);
    expect(steps.filter((s) => s.status === 'pass')).toHaveLength(0);
    expect(steps.every((s) => s.status === 'pending' || s.status === 'fail')).toBe(true);
  });

  it('MERGED alone does not turn the whole checklist green', () => {
    const steps = projectCompletionSteps({ slug: 'x', state: 'MERGED' });
    const green = steps.filter((s) => s.status === 'pass').map((s) => s.key);
    expect(green).toEqual(['merged']);
    expect(completionProofSummary({ slug: 'x', state: 'MERGED' }).proven).toBe(false);
  });

  it('a failing test run shows fail, not pending and not pass', () => {
    const steps = projectCompletionSteps({
      slug: 'x', state: 'DONE', test_command: 'vitest run', tests_passed: false,
    });
    expect(steps.find((s) => s.key === 'tests_passed')!.status).toBe('fail');
  });

  it('a fully evidenced completion is fully green', () => {
    const rec: CompletionRecord = {
      slug: 'x', state: 'MERGED', commit: 'deadbee', branch: 'agent/x',
      test_command: 'vitest run', tests_passed: true, test_artifact_url: 'https://a.test/log',
      integration_proof_url: 'https://p.test', release_sha: 'abc1234',
      production_url: 'https://prod.test', verified_at: '2026-08-25T00:00:00Z',
    };
    const steps = projectCompletionSteps(rec);
    expect(steps.every((s) => s.status === 'pass')).toBe(true);
    expect(completionProofSummary(rec).proven).toBe(true);
  });

  it('unknown maps to pending, which renders neutral rather than skipped', () => {
    expect(toChecklistStatus('unknown')).toBe('pending');
    expect(toChecklistStatus('pass')).toBe('pass');
    expect(toChecklistStatus('fail')).toBe('fail');
  });

  it('completionToEvents emits monotonic cursors and no events for an empty record', () => {
    expect(completionToEvents({})).toHaveLength(0);
    const events = completionToEvents({ state: 'MERGED', commit: 'c', release_sha: 's' });
    expect(events.map((e) => e.cursor)).toEqual([1, 2, 3]);
  });

  it('tolerates a null-heavy record without throwing', () => {
    expect(() => projectCompletionSteps({
      slug: 'x', commit: null, branch: null, tests_passed: null, release_sha: null,
    })).not.toThrow();
  });
});

describe('Madeus terminal — the component itself', () => {
  const source = readFileSync(SFC, 'utf8');

  it('no longer hardcodes checklist passes', () => {
    expect(source).not.toMatch(/status:\s*'pass'/);
  });

  it('projects its checklist through the shared client', () => {
    expect(source).toContain('projectCompletionSteps');
    expect(source).toContain('./developmentTerminalProof');
  });

  it('still renders the panels the session view is meant to show', () => {
    for (const panel of ['VerificationChecklist', 'QAResultsPanel', 'CostRoutingPanel',
      'TerminalStreamOutput', 'FleetTopologyMap']) {
      expect(source).toContain(panel);
    }
  });

  it('does not shell out or open a raw SQL connection from the web app', () => {
    expect(source).not.toMatch(/child_process|execSync|\bspawn\(/);
    expect(source).not.toMatch(/service[_-]?role/i);
  });
});

import { describe, it, expect, vi } from 'vitest';
import {
  applyEvent,
  applyEvents,
  ariaStatusMessage,
  assertBrokerSafe,
  AuthRequiredError,
  createDevelopmentSessionClient,
  emptySessionState,
  isFullyProven,
  MAX_OUTPUT_LINES,
  outputAriaAttributes,
  pageOutput,
  projectVerificationSteps,
  proofSummary,
  resumeCursor,
  UnsafeTransportError,
  type SessionEvent,
} from './developmentSessionClient';

const out = (cursor: number, text: string): SessionEvent =>
  ({ cursor, type: 'output', kind: 'stdout', text });

describe('transport safety — the web app is a viewer, not an executor', () => {
  it('accepts an https broker', () => {
    expect(() => assertBrokerSafe({ brokerUrl: 'https://broker.internal' })).not.toThrow();
    expect(() => assertBrokerSafe({ brokerUrl: 'wss://broker.internal' })).not.toThrow();
  });

  it('refuses shell, file and raw postgres transports', () => {
    for (const url of ['shell://run', 'file:///etc/passwd', 'postgres://user@host/db']) {
      expect(() => assertBrokerSafe({ brokerUrl: url })).toThrow(UnsafeTransportError);
    }
  });

  it('refuses a service-role credential', () => {
    expect(() => assertBrokerSafe({
      brokerUrl: 'https://broker.internal', token: 'eyJ.service_role.xyz',
    })).toThrow(UnsafeTransportError);
  });

  it('requires a broker url', () => {
    expect(() => assertBrokerSafe({ brokerUrl: '' })).toThrow(UnsafeTransportError);
  });
});

describe('auth', () => {
  it('refuses to construct without a token', () => {
    expect(() => createDevelopmentSessionClient({
      sessionId: 's1', brokerUrl: 'https://broker.internal',
    })).toThrow(AuthRequiredError);
  });

  it('sends the bearer token on replay', async () => {
    const fetchImpl = vi.fn().mockResolvedValue({ status: 200, json: async () => ({ events: [] }) });
    const c = createDevelopmentSessionClient({
      sessionId: 's1', brokerUrl: 'https://broker.internal', token: 'tok', fetchImpl: fetchImpl as any,
    });
    await c.reconnect();
    const [, init] = fetchImpl.mock.calls[0];
    expect(init.headers.Authorization).toBe('Bearer tok');
  });

  it('surfaces a 401 as AuthRequiredError', async () => {
    const fetchImpl = vi.fn().mockResolvedValue({ status: 401, json: async () => ({}) });
    const c = createDevelopmentSessionClient({
      sessionId: 's1', brokerUrl: 'https://broker.internal', token: 'stale', fetchImpl: fetchImpl as any,
    });
    await expect(c.reconnect()).rejects.toBeInstanceOf(AuthRequiredError);
  });
});

describe('cursor replay', () => {
  it('advances the cursor monotonically', () => {
    const s = applyEvents(emptySessionState('s1'), [out(1, 'a'), out(2, 'b'), out(3, 'c')]);
    expect(s.cursor).toBe(3);
    expect(s.output.map((o) => o.text)).toEqual(['a', 'b', 'c']);
  });

  it('discards replayed events instead of duplicating output', () => {
    let s = applyEvents(emptySessionState('s1'), [out(1, 'a'), out(2, 'b')]);
    s = applyEvents(s, [out(1, 'a'), out(2, 'b'), out(3, 'c')]);
    expect(s.output.map((o) => o.text)).toEqual(['a', 'b', 'c']);
    expect(s.duplicateEvents).toBe(2);
  });

  it('counts malformed events as dropped rather than crashing', () => {
    const s = applyEvent(emptySessionState('s1'), { type: 'output' } as any);
    expect(s.droppedEvents).toBe(1);
    expect(s.output).toHaveLength(0);
  });

  it('resumeCursor reports where a reconnect should pick up', async () => {
    const fetchImpl = vi.fn().mockResolvedValue({
      status: 200, json: async () => ({ events: [out(3, 'c'), out(4, 'd')] }),
    });
    const c = createDevelopmentSessionClient({
      sessionId: 's1', brokerUrl: 'https://broker.internal/', token: 'tok', fetchImpl: fetchImpl as any,
    });
    c.ingest([out(1, 'a'), out(2, 'b')]);
    expect(resumeCursor(c.getState())).toBe(2);
    await c.reconnect();
    expect(fetchImpl.mock.calls[0][0]).toContain('cursor=2');
    expect(c.getState().output.map((o) => o.text)).toEqual(['a', 'b', 'c', 'd']);
  });

  it('a disconnect and resume loses no output', () => {
    const c = createDevelopmentSessionClient({
      sessionId: 's1', brokerUrl: 'wss://broker.internal', token: 'tok',
    });
    c.ingest([out(1, 'a'), out(2, 'b')]);
    c.setConnected(false);
    // broker replays from cursor 1, overlapping what we already have
    const s = c.ingest([out(2, 'b'), out(3, 'c')]);
    expect(s.output.map((o) => o.text)).toEqual(['a', 'b', 'c']);
    expect(s.connected).toBe(false);
  });

  it('bounds the output buffer', () => {
    const events = Array.from({ length: MAX_OUTPUT_LINES + 50 }, (_, i) => out(i + 1, `line ${i}`));
    const s = applyEvents(emptySessionState('s1'), events);
    expect(s.output).toHaveLength(MAX_OUTPUT_LINES);
    expect(s.output[s.output.length - 1].text).toBe(`line ${MAX_OUTPUT_LINES + 49}`);
  });
});

describe('session facets', () => {
  it('starts with everything unknown', () => {
    const s = emptySessionState('s1');
    expect(s.phase).toBe('unknown');
    expect(s.host).toBeNull();
    expect(s.generation).toBeNull();
    expect(s.adapter).toBeNull();
    expect(s.release.sha).toBeNull();
  });

  it('records host, generation, adapter, plan, steering, worktree, release and journey', () => {
    const s = applyEvents(emptySessionState('s1'), [
      { cursor: 1, type: 'session', phase: 'executing', host: 'mac-mini', generation: 'g7', adapter: 'claude-code' },
      { cursor: 2, type: 'plan', planId: 'p1', digest: 'abc', slices: 3 },
      { cursor: 3, type: 'steering', receipt: { gate: 'release', decision: 'allow', digest: 'd1' } },
      { cursor: 4, type: 'worktree', branch: 'agent/x', commit: 'deadbee', diffStat: '2 files' },
      { cursor: 5, type: 'release', sha: 'abc1234', url: 'https://example.test/d' },
      { cursor: 6, type: 'journey', productionUrl: 'https://prod.test', verifiedAt: '2026-08-25T00:00:00Z' },
    ]);
    expect(s.phase).toBe('executing');
    expect(s.host).toBe('mac-mini');
    expect(s.generation).toBe('g7');
    expect(s.adapter).toBe('claude-code');
    expect(s.plan.slices).toBe(3);
    expect(s.steering[0].decision).toBe('allow');
    expect(s.worktree.branch).toBe('agent/x');
    expect(s.release.sha).toBe('abc1234');
    expect(s.journey.productionUrl).toBe('https://prod.test');
  });

  it('keeps stdout, stderr and tool actions distinguishable', () => {
    const s = applyEvents(emptySessionState('s1'), [
      { cursor: 1, type: 'output', kind: 'stdout', text: 'building' },
      { cursor: 2, type: 'output', kind: 'stderr', text: 'warning' },
      { cursor: 3, type: 'output', kind: 'tool', text: 'Edit(file.ts)', tool: 'Edit' },
    ]);
    expect(s.output.map((o) => o.kind)).toEqual(['stdout', 'stderr', 'tool']);
    expect(s.output[2].tool).toBe('Edit');
  });
});

describe('pagination', () => {
  const state = applyEvents(emptySessionState('s1'),
    Array.from({ length: 25 }, (_, i) => out(i + 1, `l${i}`)));

  it('returns a bounded page with a hasMore flag', () => {
    const p = pageOutput(state, 0, 10);
    expect(p.lines).toHaveLength(10);
    expect(p.total).toBe(25);
    expect(p.hasMore).toBe(true);
  });

  it('reports the last page as complete', () => {
    const p = pageOutput(state, 20, 10);
    expect(p.lines).toHaveLength(5);
    expect(p.hasMore).toBe(false);
  });

  it('tolerates nonsense offsets and limits', () => {
    expect(pageOutput(state, -5, 0).offset).toBe(0);
    expect(pageOutput(state, -5, 0).limit).toBe(1);
    expect(pageOutput(state, 999, 10).lines).toHaveLength(0);
  });
});

describe('proof projection — UNKNOWN stays UNKNOWN', () => {
  it('projects a bare session as entirely unknown, never green', () => {
    const steps = projectVerificationSteps(emptySessionState('s1'));
    expect(steps.every((s) => s.status === 'unknown')).toBe(true);
    expect(isFullyProven(steps)).toBe(false);
    expect(proofSummary(steps).pass).toBe(0);
  });

  it('a failing test run projects as fail, not unknown and not pass', () => {
    const s = applyEvents(emptySessionState('s1'), [
      { cursor: 1, type: 'tests', command: 'vitest run', passed: false },
    ]);
    const step = projectVerificationSteps(s).find((x) => x.key === 'tests_passed')!;
    expect(step.status).toBe('fail');
  });

  it('only real evidence produces a pass', () => {
    const s = applyEvents(emptySessionState('s1'), [
      { cursor: 1, type: 'worktree', branch: 'agent/x', commit: 'deadbee' },
      { cursor: 2, type: 'tests', command: 'vitest run', passed: true, artifactUrl: 'https://a.test/log' },
      { cursor: 3, type: 'integration', proofUrl: 'https://p.test', merged: true },
      { cursor: 4, type: 'release', sha: 'abc1234' },
      { cursor: 5, type: 'journey', productionUrl: 'https://prod.test', verifiedAt: '2026-08-25T00:00:00Z' },
    ]);
    const steps = projectVerificationSteps(s);
    expect(steps.every((x) => x.status === 'pass')).toBe(true);
    expect(isFullyProven(steps)).toBe(true);
  });

  it('one missing facet keeps the session unproven', () => {
    const s = applyEvents(emptySessionState('s1'), [
      { cursor: 1, type: 'worktree', branch: 'agent/x', commit: 'deadbee' },
      { cursor: 2, type: 'tests', command: 'vitest run', passed: true, artifactUrl: 'https://a.test/log' },
    ]);
    const steps = projectVerificationSteps(s);
    expect(isFullyProven(steps)).toBe(false);
    expect(proofSummary(steps).unknown).toBeGreaterThan(0);
  });

  it('every step carries its evidence or an explicit null', () => {
    const steps = projectVerificationSteps(emptySessionState('s1'));
    for (const s of steps) expect(s.evidence).toBeNull();
  });
});

describe('accessibility', () => {
  it('marks the output region as a polite log while streaming', () => {
    const attrs = outputAriaAttributes(true);
    expect(attrs.role).toBe('log');
    expect(attrs['aria-live']).toBe('polite');
    expect(attrs['aria-label']).toBeTruthy();
  });

  it('stops announcing when the stream is idle', () => {
    expect(outputAriaAttributes(false)['aria-live']).toBe('off');
  });

  it('describes an unknown session honestly', () => {
    const msg = ariaStatusMessage(emptySessionState('s1'));
    expect(msg).toContain('state unknown');
    expect(msg).toContain('disconnected');
  });
});

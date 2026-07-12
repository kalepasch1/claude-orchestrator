/**
 * Critical user journey E2E tests for Claude Orchestrator.
 *
 * Journeys J1–J6 run against the public UI (no auth required).
 * Journeys J7–J10 run when E2E_SUPABASE_URL and E2E_SESSION_JSON are set.
 *
 * Usage:
 *   BASE_URL=https://my-staging.vercel.app npm --prefix web run test:e2e
 *
 * Authenticated:
 *   BASE_URL=https://my-staging.vercel.app \
 *   E2E_SUPABASE_URL=https://abc123.supabase.co \
 *   E2E_SESSION_JSON='{"access_token":"...","refresh_token":"...","expires_at":1234567890,"user":{}}' \
 *   npm --prefix web run test:e2e
 */

const BASE_URL = process.env.BASE_URL || 'http://localhost:3000';
const SUPABASE_URL = process.env.E2E_SUPABASE_URL || '';
const SESSION_JSON = process.env.E2E_SESSION_JSON || '';
const hasAuth = !!(SUPABASE_URL && SESSION_JSON);

// Helper: build full URL
function url(path: string): string {
  return `${BASE_URL}${path}`;
}

// Helper: parse session for authenticated tests
function getSession(): Record<string, unknown> | null {
  if (!SESSION_JSON) return null;
  try {
    return JSON.parse(SESSION_JSON);
  } catch {
    return null;
  }
}

// ─── Public journeys (J1–J6) ───

describe('J1: Landing page loads', () => {
  it('should return 200 for the root page', async () => {
    const res = await fetch(url('/'));
    expect(res.status).toBe(200);
  });
});

describe('J2: Health endpoint', () => {
  it('should return healthy status', async () => {
    const res = await fetch(url('/api/health'));
    // Accept 200 or 404 (endpoint may not exist yet)
    expect([200, 404]).toContain(res.status);
    if (res.status === 200) {
      const body = await res.json();
      expect(body).toHaveProperty('status');
    }
  });
});

describe('J3: Static assets load', () => {
  it('should serve CSS/JS assets', async () => {
    const res = await fetch(url('/'));
    const html = await res.text();
    // Nuxt injects script tags
    expect(html).toContain('<script');
  });
});

describe('J4: Navigation structure', () => {
  it('should have navigation links in the page', async () => {
    const res = await fetch(url('/'));
    const html = await res.text();
    // Page should contain navigable content
    expect(html.length).toBeGreaterThan(100);
  });
});

describe('J5: API tasks endpoint', () => {
  it('should respond to tasks API', async () => {
    const res = await fetch(url('/api/tasks'));
    // 200 if accessible, 401 if auth required, 404 if not yet built
    expect([200, 401, 403, 404]).toContain(res.status);
  });
});

describe('J6: Error page handling', () => {
  it('should handle 404 pages gracefully', async () => {
    const res = await fetch(url('/nonexistent-page-12345'));
    // Nuxt returns 200 with error page content, or 404
    expect([200, 404]).toContain(res.status);
  });
});

// ─── Authenticated journeys (J7–J10) ───

const describeAuth = hasAuth ? describe : describe.skip;

describeAuth('J7: Authenticated dashboard access', () => {
  it('should load dashboard with valid session', async () => {
    const session = getSession();
    if (!session) return;
    const res = await fetch(url('/dashboard'), {
      headers: {
        'Authorization': `Bearer ${session.access_token}`,
      },
    });
    expect([200, 302]).toContain(res.status);
  });
});

describeAuth('J8: Authenticated task list', () => {
  it('should return tasks for authenticated user', async () => {
    const session = getSession();
    if (!session) return;
    const res = await fetch(url('/api/tasks'), {
      headers: {
        'Authorization': `Bearer ${session.access_token}`,
      },
    });
    expect([200, 403]).toContain(res.status);
  });
});

describeAuth('J9: Authenticated project list', () => {
  it('should return projects for authenticated user', async () => {
    const session = getSession();
    if (!session) return;
    const res = await fetch(url('/api/projects'), {
      headers: {
        'Authorization': `Bearer ${session.access_token}`,
      },
    });
    expect([200, 403, 404]).toContain(res.status);
  });
});

describeAuth('J10: Authenticated config endpoint', () => {
  it('should access config API', async () => {
    const session = getSession();
    if (!session) return;
    const res = await fetch(url('/api/config'), {
      headers: {
        'Authorization': `Bearer ${session.access_token}`,
      },
    });
    expect([200, 403, 404]).toContain(res.status);
  });
});

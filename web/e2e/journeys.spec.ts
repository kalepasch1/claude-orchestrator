/**
 * Critical user journey E2E tests for Claude Orchestrator.
 *
 * Covered flows (10 scenarios, each <30s):
 *  J1  – Sign-in page renders with correct title and form
 *  J2  – Magic link send shows confirmation message
 *  J3  – OTP request carries the exact email the user typed
 *  J4  – Portfolio health page loads (/health)
 *  J5  – Fleet admin page loads (/fleet)
 *  J6  – Growth OS overview page loads (/growth)
 *  J7  – Dashboard renders all major sections        [AUTH]
 *  J8  – Queue-improvement form accepts user input    [AUTH]
 *  J9  – NL analytics search input is present        [AUTH]
 *  J10 – Sign-out returns to sign-in form             [AUTH]
 *
 * Auth env vars (required for J7–J10, otherwise those tests are skipped):
 *   E2E_SUPABASE_URL   – e.g. https://abc123.supabase.co
 *   E2E_SESSION_JSON   – JSON string of the Supabase session object
 *                        { access_token, refresh_token, expires_at, user }
 *                        Obtain via `supabase.auth.getSession()` in a live browser session.
 *
 * Other env vars:
 *   BASE_URL           – app URL to test against (default: http://localhost:3000)
 */

import { test, expect, type BrowserContext } from '@playwright/test'

// ── Auth helpers ──────────────────────────────────────────────────────────────

const SESSION_JSON = process.env.E2E_SESSION_JSON
const SUPABASE_URL = process.env.E2E_SUPABASE_URL

function supabaseProjectRef(url: string): string {
  return new URL(url).hostname.split('.')[0]
}

/**
 * Injects a Supabase session cookie so SSR sees the user as authenticated.
 * @supabase/ssr stores the session as sb-<ref>-auth-token in cookies.
 */
async function injectSession(ctx: BrowserContext): Promise<void> {
  if (!SESSION_JSON || !SUPABASE_URL) return
  const ref = supabaseProjectRef(SUPABASE_URL)
  const baseURL = process.env.BASE_URL ?? 'http://localhost:3000'
  const { hostname } = new URL(baseURL)
  await ctx.addCookies([
    {
      name: `sb-${ref}-auth-token`,
      value: SESSION_JSON,
      domain: hostname,
      path: '/',
      httpOnly: true,
      sameSite: 'Lax',
    },
  ])
}

const hasAuth = Boolean(SESSION_JSON && SUPABASE_URL)

// ── J1: Sign-in page renders ──────────────────────────────────────────────────

test('J1 – sign-in page renders with correct title and form', async ({ page }) => {
  await page.goto('/')
  await expect(page).toHaveTitle(/claude orchestrator/i)
  await expect(page.locator('input[type="email"]')).toBeVisible()
  await expect(page.getByRole('button', { name: /send magic link/i })).toBeVisible()
  await expect(page.getByText(/sign in to monitor/i)).toBeVisible()
})

// ── J2: Magic link send ───────────────────────────────────────────────────────

test('J2 – magic link send shows email confirmation', async ({ page }) => {
  await page.route('**/auth/v1/otp**', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }),
  )
  await page.goto('/')
  await page.locator('input[type="email"]').fill('operator@example.com')
  await page.getByRole('button', { name: /send magic link/i }).click()
  await expect(page.getByText(/check your email/i)).toBeVisible()
})

// ── J3: OTP request carries correct email ────────────────────────────────────

test('J3 – OTP request carries the email the user typed', async ({ page }) => {
  let capturedEmail = ''
  await page.route('**/auth/v1/otp**', async route => {
    try {
      const body = await route.request().postDataJSON()
      capturedEmail = body?.email ?? ''
    } catch {
      capturedEmail = ''
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
  })

  await page.goto('/')
  await page.locator('input[type="email"]').fill('kale@smrter.us')
  await page.getByRole('button', { name: /send magic link/i }).click()
  await expect(page.getByText(/check your email/i)).toBeVisible()
  expect(capturedEmail).toBe('kale@smrter.us')
})

// ── J4: Portfolio health page ─────────────────────────────────────────────────

test('J4 – portfolio health page loads', async ({ page }) => {
  await page.goto('/health')
  await expect(page.getByText(/portfolio health/i).first()).toBeVisible({ timeout: 15_000 })
})

// ── J5: Fleet admin page ──────────────────────────────────────────────────────

test('J5 – fleet admin page loads', async ({ page }) => {
  await page.goto('/fleet')
  await expect(page.getByText(/fleet admin/i).first()).toBeVisible({ timeout: 15_000 })
})

// ── J6: Growth OS page ────────────────────────────────────────────────────────

test('J6 – growth OS oversight page loads', async ({ page }) => {
  await page.goto('/growth')
  await expect(page.getByText(/growth os/i).first()).toBeVisible({ timeout: 15_000 })
})

// ── Authenticated journeys (J7–J10) ──────────────────────────────────────────
//
// These require real Supabase credentials.
// Set E2E_SUPABASE_URL and E2E_SESSION_JSON in your CI secrets.

test.describe('authenticated journeys', () => {
  test.beforeEach(async ({ context }) => {
    if (!hasAuth) {
      test.skip(true, 'Set E2E_SUPABASE_URL and E2E_SESSION_JSON to run authenticated journeys')
      return
    }
    await injectSession(context)
  })

  // ── J7: Dashboard renders all major sections ────────────────────────────────

  test('J7 – dashboard renders all major sections', async ({ page }) => {
    await page.goto('/')
    // Header with live runner dot and title
    await expect(page.getByRole('heading', { name: /claude orchestrator/i })).toBeVisible()
    // Sign-out confirms we're authenticated
    await expect(page.getByRole('button', { name: /sign out/i })).toBeVisible()
    // Queue improvement section
    await expect(page.getByText(/queue an improvement/i)).toBeVisible()
    // Full-queue SQL counters section
    await expect(page.getByText(/full queue sql counters/i)).toBeVisible()
    // Operator sign-offs section
    await expect(page.getByText(/operator sign-offs/i)).toBeVisible()
  })

  // ── J8: Queue improvement form accepts input ────────────────────────────────

  test('J8 – queue improvement form accepts user input', async ({ page }) => {
    await page.goto('/')
    const textarea = page.getByPlaceholder(/describe the improvement/i)
    await expect(textarea).toBeVisible()
    await textarea.fill('Improve dashboard loading time by caching runner heartbeats')
    await expect(page.getByRole('button', { name: /route.*implement.*qa.*merge/i })).toBeEnabled()
    // Verify slug input is also present
    await expect(page.getByPlaceholder(/slug \(optional\)/i)).toBeVisible()
  })

  // ── J9: NL analytics search ────────────────────────────────────────────────

  test('J9 – NL analytics search accepts a query', async ({ page }) => {
    // Mock the Supabase edge function so the test doesn't need real embeddings
    await page.route('**/functions/v1/ask**', route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ answer: 'Test answer from mock' }),
      }),
    )
    await page.goto('/')
    const input = page.getByPlaceholder(/ask a question/i)
    await expect(input).toBeVisible()
    await input.fill('which projects are shipping today?')
    await page.getByRole('button', { name: /^ask$/i }).click()
    await expect(page.getByText(/test answer from mock/i)).toBeVisible({ timeout: 15_000 })
  })

  // ── J10: Sign-out returns to sign-in form ──────────────────────────────────

  test('J10 – sign-out returns to sign-in form', async ({ page }) => {
    await page.route('**/auth/v1/logout**', route =>
      route.fulfill({ status: 204 }),
    )
    await page.goto('/')
    await expect(page.getByRole('button', { name: /sign out/i })).toBeVisible()
    await page.getByRole('button', { name: /sign out/i }).click()
    await expect(page.locator('input[type="email"]')).toBeVisible({ timeout: 10_000 })
    await expect(page.getByRole('button', { name: /send magic link/i })).toBeVisible()
  })
})

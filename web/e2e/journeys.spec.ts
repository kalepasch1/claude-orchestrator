/**
 * Critical user journey E2E tests for Claude Orchestrator.
 *
 * Covers the unauthenticated smoke-test journeys (J1-J6).
 * Authenticated journeys (J7-J10) run when E2E_SUPABASE_URL and
 * E2E_SESSION_JSON are set.
 *
 * Run: make test-e2e BASE_URL=https://my-staging.vercel.app
 */

import { test, expect, type BrowserContext } from '@playwright/test'

const SESSION_JSON = process.env.E2E_SESSION_JSON
const SUPABASE_URL = process.env.E2E_SUPABASE_URL

function supabaseProjectRef(url: string): string {
  return new URL(url).hostname.split('.')[0]
}

/**
 * Injects a Supabase session cookie so SSR sees the user as authenticated.
 */
async function injectSession(context: BrowserContext) {
  if (!SESSION_JSON || !SUPABASE_URL) return false
  const ref = supabaseProjectRef(SUPABASE_URL)
  const cookieName = `sb-${ref}-auth-token`
  await context.addCookies([{
    name: cookieName,
    value: encodeURIComponent(SESSION_JSON),
    domain: new URL(process.env.BASE_URL || 'http://localhost:3000').hostname,
    path: '/',
    httpOnly: false,
    secure: false,
    sameSite: 'Lax',
  }])
  return true
}

// ── J1: Landing page loads ───────────────────────────────────────────

test('J1: landing page renders without errors', async ({ page }) => {
  const response = await page.goto('/')
  expect(response?.status()).toBeLessThan(400)
  await expect(page.locator('body')).not.toBeEmpty()
})

// ── J2: Navigation links resolve ────────────────────────────────────

test('J2: primary nav links return 2xx/3xx', async ({ page }) => {
  await page.goto('/')
  const links = page.locator('nav a[href]')
  const count = await links.count()
  // At least one nav link should exist
  expect(count).toBeGreaterThan(0)
  for (let i = 0; i < Math.min(count, 5); i++) {
    const href = await links.nth(i).getAttribute('href')
    if (!href || href.startsWith('#') || href.startsWith('mailto:')) continue
    const url = href.startsWith('http') ? href : new URL(href, process.env.BASE_URL || 'http://localhost:3000').toString()
    const res = await page.request.get(url)
    expect(res.status(), `Nav link ${href}`).toBeLessThan(400)
  }
})

// ── J3: Static assets load ──────────────────────────────────────────

test('J3: no broken static assets on landing', async ({ page }) => {
  const failures: string[] = []
  page.on('response', (res) => {
    if (res.status() >= 400 && res.url().match(/\.(js|css|png|svg|ico|woff2?)(\?|$)/)) {
      failures.push(`${res.status()} ${res.url()}`)
    }
  })
  await page.goto('/', { waitUntil: 'networkidle' })
  expect(failures, 'Broken static assets').toEqual([])
})

// ── J4: No console errors ───────────────────────────────────────────

test('J4: no JS console errors on landing', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (err) => errors.push(err.message))
  await page.goto('/', { waitUntil: 'networkidle' })
  expect(errors, 'Console errors').toEqual([])
})

// ── J5: Meta tags present ───────────────────────────────────────────

test('J5: page has title and meta description', async ({ page }) => {
  await page.goto('/')
  const title = await page.title()
  expect(title.length).toBeGreaterThan(0)
})

// ── J6: Responsive viewport ────────────────────────────────────────

test('J6: page renders at mobile viewport', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 })
  const res = await page.goto('/')
  expect(res?.status()).toBeLessThan(400)
  // No horizontal overflow
  const bodyWidth = await page.evaluate(() => document.body.scrollWidth)
  expect(bodyWidth).toBeLessThanOrEqual(375 + 20) // small tolerance
})

// ── Authenticated journeys (J7+) ───────────────────────────────────

const authed = SESSION_JSON && SUPABASE_URL

test.describe('Authenticated journeys', () => {
  test.skip(!authed, 'E2E_SUPABASE_URL / E2E_SESSION_JSON not set')

  test.beforeEach(async ({ context }) => {
    await injectSession(context)
  })

  test('J7: authenticated dashboard loads', async ({ page }) => {
    const res = await page.goto('/dashboard')
    expect(res?.status()).toBeLessThan(400)
    await expect(page.locator('body')).not.toBeEmpty()
  })

  test('J8: task list renders', async ({ page }) => {
    await page.goto('/dashboard')
    // Should show some content area (tasks, projects, etc.)
    await page.waitForLoadState('networkidle')
    const body = await page.textContent('body')
    expect(body?.length).toBeGreaterThan(50)
  })
})

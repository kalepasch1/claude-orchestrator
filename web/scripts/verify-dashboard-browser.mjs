#!/usr/bin/env node
import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import { mkdir, writeFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright-core'

const HERE = dirname(fileURLToPath(import.meta.url))
const WEB_ROOT = resolve(HERE, '..')
const REPO_ROOT = resolve(WEB_ROOT, '..')
const RUNTIME = resolve(REPO_ROOT, '.runtime')
const OUT_DIR = resolve(RUNTIME, 'browser-verification')
const STATUS_FILE = resolve(RUNTIME, 'browser_verify.json')

function arg(name, fallback = '') {
  const idx = process.argv.indexOf(name)
  return idx >= 0 ? (process.argv[idx + 1] || fallback) : fallback
}

function findBrowser() {
  const candidates = [
    process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Chromium.app/Contents/MacOS/Chromium',
    '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
    '/Applications/Brave Browser.app/Contents/MacOS/Brave Browser',
  ].filter(Boolean)
  return candidates.find((p) => existsSync(p)) || ''
}

async function waitForUrl(url, timeoutMs) {
  const started = Date.now()
  let last = ''
  while (Date.now() - started < timeoutMs) {
    try {
      const res = await fetch(url, { method: 'GET' })
      if (res.ok) return true
      last = `${res.status} ${res.statusText}`
    } catch (e) {
      last = e?.message || String(e)
    }
    await new Promise((resolve) => setTimeout(resolve, 500))
  }
  throw new Error(`dev server did not become ready: ${last}`)
}

function startServer(port) {
  const useDev = process.argv.includes('--dev')
  const script = useDev ? 'dev' : 'preview'
  const child = spawn('npm', ['run', script, '--', '--host=127.0.0.1', `--port=${port}`], {
    cwd: WEB_ROOT,
    env: {
      ...process.env,
      BROWSER: 'none',
      HOST: '127.0.0.1',
      NITRO_HOST: '127.0.0.1',
      NITRO_PORT: String(port),
      NUXT_IGNORE_LOCK: '1',
    },
    detached: true,
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  let log = ''
  child.stdout.on('data', (d) => { log += d.toString() })
  child.stderr.on('data', (d) => { log += d.toString() })
  return { child, log: () => log.slice(-4000) }
}

async function writeStatus(payload) {
  await mkdir(RUNTIME, { recursive: true })
  await writeFile(STATUS_FILE, JSON.stringify(payload, null, 2))
}

async function main() {
  const port = Number(arg('--port', process.env.DASHBOARD_VERIFY_PORT || '3456'))
  const explicitUrl = arg('--url', process.env.DASHBOARD_URL || '')
  const url = explicitUrl || `http://127.0.0.1:${port}/`
  const timeoutMs = Number(arg('--timeout-ms', process.env.DASHBOARD_VERIFY_TIMEOUT_MS || '45000'))
  const shouldStart = !explicitUrl && process.argv.indexOf('--no-start') < 0
  const authState = arg('--auth-state', process.env.BROWSER_VERIFY_AUTH_STATE || '')
  const expectedText = arg('--expect-text', process.env.BROWSER_VERIFY_EXPECT_TEXT || 'Claude Orchestrator')
  const browserPath = findBrowser()
  let server = null
  let browser = null
  const startedAt = new Date().toISOString()
  await mkdir(OUT_DIR, { recursive: true })
  const screenshot = resolve(OUT_DIR, `dashboard-${startedAt.replace(/[:.]/g, '-')}.png`)

  try {
    if (shouldStart) server = startServer(port)
    await waitForUrl(url, timeoutMs)
    browser = await chromium.launch({
      headless: true,
      ...(browserPath ? { executablePath: browserPath } : {}),
    })
    const contextOptions = authState && existsSync(authState) ? { storageState: authState } : {}
    const context = await browser.newContext(contextOptions)
    const page = await context.newPage()
    const consoleErrors = []
    page.on('console', (msg) => {
      if (msg.type() === 'error') consoleErrors.push(msg.text())
    })
    page.on('pageerror', (err) => consoleErrors.push(err.message))
    await page.goto(url, { waitUntil: 'networkidle', timeout: timeoutMs })
    const bodyText = (await page.locator('body').innerText({ timeout: 5000 }).catch(() => '')).trim()
    const hasOverlay = await page.locator('.vite-error-overlay, [data-nextjs-dialog], #webpack-dev-server-client-overlay').count()
    const expectedVisible = expectedText ? bodyText.includes(expectedText) : bodyText.length > 0
    await page.screenshot({ path: screenshot, fullPage: true })
    const ok = bodyText.length > 0 && !hasOverlay && expectedVisible && consoleErrors.length === 0
    const payload = {
      status: ok ? 'ok' : 'failed',
      updated_at: new Date().toISOString(),
      url,
      screenshot,
      browser: browserPath || 'playwright-default',
      expectedText,
      bodyLength: bodyText.length,
      expectedVisible,
      errorOverlay: Boolean(hasOverlay),
      consoleErrors: consoleErrors.slice(0, 8),
      serverLog: server?.log?.() || '',
    }
    await writeStatus(payload)
    console.log(JSON.stringify(payload, null, 2))
    if (!ok) process.exitCode = 1
  } catch (e) {
    const payload = {
      status: 'failed',
      updated_at: new Date().toISOString(),
      url,
      screenshot: existsSync(screenshot) ? screenshot : '',
      error: e?.message || String(e),
      browser: browserPath || 'playwright-default',
      serverLog: server?.log?.() || '',
    }
    await writeStatus(payload)
    console.error(JSON.stringify(payload, null, 2))
    process.exitCode = 1
  } finally {
    await browser?.close?.().catch(() => {})
    if (server?.child && !server.child.killed) {
      try {
        process.kill(-server.child.pid, 'SIGTERM')
      } catch {
        server.child.kill('SIGTERM')
      }
    }
  }
}

main()

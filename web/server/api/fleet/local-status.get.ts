import { readdir, readFile, stat } from 'node:fs/promises'
import { join, resolve } from 'node:path'

async function readJson(path: string) {
  try {
    return JSON.parse(await readFile(path, 'utf8'))
  } catch {
    return null
  }
}

async function pendingIntake(root: string) {
  const intakeDir = join(root, 'intake')
  try {
    const names = (await readdir(intakeDir)).filter((n) => n.endsWith('.md')).sort()
    const batches = []
    for (const name of names) {
      const path = join(intakeDir, name)
      const text = await readFile(path, 'utf8').catch(() => '')
      const st = await stat(path).catch(() => null)
      batches.push({
        file: name,
        tasks: (text.match(/^\s*-\s*id:\s*/gm) || []).length,
        projects: Array.from(new Set(Array.from(text.matchAll(/^PROJECT:\s*(.+)$/gm)).map((m) => m[1].trim()))),
        updatedAt: st?.mtime?.toISOString?.() || null,
      })
    }
    return {
      pendingBatches: batches.length,
      pendingTasks: batches.reduce((n, b) => n + b.tasks, 0),
      batches,
    }
  } catch {
    return { pendingBatches: 0, pendingTasks: 0, batches: [] }
  }
}

export default defineEventHandler(async () => {
  const root = resolve(process.cwd(), '..')
  const runtime = join(root, '.runtime')
  const [dbHealth, intakeStatus, browserVerify, pending] = await Promise.all([
    readJson(join(runtime, 'db_health.json')),
    readJson(join(runtime, 'intake_status.json')),
    readJson(join(runtime, 'browser_verify.json')),
    pendingIntake(root),
  ])

  return {
    ok: true,
    generatedAt: new Date().toISOString(),
    dbHealth,
    intake: {
      ...(intakeStatus || {}),
      pendingBatches: intakeStatus?.pending_batches ?? pending.pendingBatches,
      pendingTasks: intakeStatus?.pending_tasks ?? pending.pendingTasks,
      batches: intakeStatus?.batches ?? pending.batches,
    },
    browserVerify,
  }
})


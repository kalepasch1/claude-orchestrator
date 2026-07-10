import { existsSync, readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'

function readJson(path: string, fallback: any) {
  try {
    if (!existsSync(path)) return fallback
    return JSON.parse(readFileSync(path, 'utf8'))
  } catch (e: any) {
    return { ...fallback, error: e?.message || String(e) }
  }
}

function lineCount(path: string) {
  try {
    if (!existsSync(path)) return 0
    const text = readFileSync(path, 'utf8')
    return text ? text.trim().split(/\n+/).filter(Boolean).length : 0
  } catch {
    return 0
  }
}

export default defineEventHandler(() => {
  const cwd = process.cwd()
  const repoRoot = cwd.endsWith('/web') ? dirname(cwd) : cwd
  const runtime = resolve(repoRoot, '.runtime')
  const mesh = readJson(resolve(runtime, 'resilience_mesh.json'), null)
  const db = readJson(resolve(runtime, 'db_health.json'), null)
  const spoolPath = resolve(runtime, 'offline_spool', 'resilience_actions.jsonl')
  return {
    updatedAt: new Date().toISOString(),
    mesh,
    db,
    spoolDepth: lineCount(spoolPath),
  }
})

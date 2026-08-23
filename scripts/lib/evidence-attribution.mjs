#!/usr/bin/env node
/**
 * Attribute a piece of evidence back to the work that produced it.
 *
 * Rescue-ref names are not opaque. They are minted as
 * `<UTC timestamp>-<slug>[-<short sha>]`, and the slug is almost always the
 * task slug the agent was working — `20260803T004053-improve-common-brain-
 * regulatory-determination-hive-c84d80ad`. That means an unrecovered item can
 * usually be routed back to the task that lost it instead of landing in a queue
 * as an anonymous ref.
 *
 * Why that matters more than it looks: routing a recovered change to whoever is
 * free means someone re-derives context that already exists. Routing it back to
 * its own task means the follow-up already knows what the work was FOR — and if
 * that task is still live, the right action is usually to let it finish rather
 * than to open a second one, which is the duplicate-work failure the whole
 * coordination rule exists to prevent.
 *
 * Parsing only, no lookups. Whether the named task is still live is a question
 * for the caller with a task list, and this deliberately does not guess.
 */

/** `20260803T004053` — the sweep's UTC stamp. */
const STAMP = /^(\d{8}T\d{6})-/
/** A trailing short sha the sweep appends to disambiguate. */
const TRAILING_SHA = /-([0-9a-f]{6,12})$/i
/** A bare 20-hex machine/run id, which is not a task slug. */
const OPAQUE_ID = /^[0-9a-f]{16,}$/i

export const ATTRIBUTION_KINDS = ['task_slug', 'run_id', 'repo_name', 'branch', 'unattributable']

/**
 * Known non-task slugs the sweep uses. These name a machine or a maintenance
 * pass, not a piece of intended work, and attributing them to a "task" would
 * put noise into the routing.
 */
const NON_TASK_SLUGS = new Set([
  'apparently',
  'tomorrow',
  'smarter',
  'illuminati',
  'darwn',
  'work',
  'dev-merge',
  'author-identity',
  'main',
  'master',
])

export function parseTimestamp(stamp) {
  const match = /^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})$/.exec(stamp)
  if (!match) return null
  const [, y, mo, d, h, mi, s] = match
  const iso = `${y}-${mo}-${d}T${h}:${mi}:${s}.000Z`
  return Number.isNaN(Date.parse(iso)) ? null : iso
}

/**
 * Attribute one evidence source.
 *
 * Returns `{ kind, slug, at, shortSha }`. `kind` says how much the attribution
 * is worth: `task_slug` is routable, `repo_name` and `run_id` are not, and
 * `unattributable` is honest rather than a guess.
 */
export function attribute(source) {
  const name = String(source).replace(/^refs\/orch-rescue\//, '').replace(/^orch-rescue\//, '')

  if (String(source).startsWith('worktree:')) {
    return { kind: 'unattributable', slug: null, at: null, shortSha: null, note: 'uncommitted path' }
  }
  if (/^stash@\{/.test(name)) {
    return { kind: 'unattributable', slug: null, at: null, shortSha: null, note: 'stash entry' }
  }
  if (/^refs\/heads\/|^refs\/remotes\//.test(String(source)) || /^(agent|chatgpt|codex)\//.test(name)) {
    const slug = name.replace(/^refs\/(heads|remotes\/origin)\//, '').replace(/^(agent|chatgpt|codex)\//, '')
    return { kind: 'branch', slug: slug || null, at: null, shortSha: null }
  }

  const stampMatch = STAMP.exec(name)
  if (!stampMatch) {
    return { kind: 'unattributable', slug: null, at: null, shortSha: null, note: 'no sweep stamp' }
  }

  const at = parseTimestamp(stampMatch[1])
  let rest = name.slice(stampMatch[0].length)

  let shortSha = null
  const shaMatch = TRAILING_SHA.exec(rest)
  if (shaMatch) {
    shortSha = shaMatch[1]
    rest = rest.slice(0, shaMatch.index)
  }

  if (!rest) return { kind: 'unattributable', slug: null, at, shortSha, note: 'stamp only' }
  if (OPAQUE_ID.test(rest)) return { kind: 'run_id', slug: rest, at, shortSha }
  if (NON_TASK_SLUGS.has(rest)) return { kind: 'repo_name', slug: rest, at, shortSha }

  return { kind: 'task_slug', slug: rest, at, shortSha }
}

/**
 * Group evidence by the task it came from.
 *
 * One task frequently produced many rescue refs — the sweep fires on a timer
 * while the task runs — so this is the difference between "244 items to triage"
 * and "N pieces of work, one of which produced 40 of them".
 */
export function attributeLedger(ledger) {
  const attributed = ledger.items
    .filter(
      item =>
        item.classification === 'RECOVERABLE_VALUE' ||
        item.classification === 'CONFLICTED_NEEDS_FOCUSED_TASK',
    )
    .map(item => ({ ...attribute(item.source), source: item.source, sha: item.sha ?? null, kind_: item.kind }))

  const byKind = Object.fromEntries(ATTRIBUTION_KINDS.map(name => [name, 0]))
  const tasks = new Map()

  for (const entry of attributed) {
    byKind[entry.kind] += 1
    if (entry.kind !== 'task_slug') continue
    const existing = tasks.get(entry.slug)
    if (existing) {
      existing.items.push(entry.source)
      if (entry.at && (!existing.lastSeenAt || entry.at > existing.lastSeenAt)) existing.lastSeenAt = entry.at
      if (entry.at && (!existing.firstSeenAt || entry.at < existing.firstSeenAt)) existing.firstSeenAt = entry.at
    } else {
      tasks.set(entry.slug, {
        slug: entry.slug,
        items: [entry.source],
        firstSeenAt: entry.at,
        lastSeenAt: entry.at,
      })
    }
  }

  const grouped = [...tasks.values()].sort(
    (a, b) => b.items.length - a.items.length || a.slug.localeCompare(b.slug),
  )

  return {
    auditFingerprint: ledger.auditFingerprint ?? null,
    attributedAt: new Date().toISOString(),
    totals: {
      considered: attributed.length,
      byKind,
      distinctTasks: grouped.length,
      /** Honest count of what could not be routed anywhere. */
      unattributable: byKind.unattributable,
    },
    tasks: grouped,
    items: attributed,
  }
}

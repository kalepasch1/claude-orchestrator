#!/usr/bin/env node
/**
 * Evidence sources specific to the ChatGPT/Codex sandbox hand-off.
 *
 * The sandbox has no outbound network, so a session there cannot push. It emits
 * a patch into the bridge drop-box instead, and this Mac turns that into a
 * `chatgpt/<slug>` branch (see CHATGPT.md and tools/chatgpt-bridge). That gives
 * two evidence kinds the generic rescue-ref sweep never sees:
 *
 *   chatgpt_bridge_artifact          a patch/diff/archive in the drop-box, and
 *                                    any patch artifact committed in-repo
 *   unmerged_chatgpt_codex_branches  a chatgpt/* or codex/* branch whose tip is
 *                                    not an ancestor of the default branch
 *
 * A bridge artifact that was applied still matters: `_applied/` proves the work
 * landed, `_failed/` proves it did not, and a loose file in the drop-box root
 * proves nobody has looked at it yet. Only the last of those is unaccounted for.
 *
 * READ-ONLY. Nothing here deletes, moves, or re-applies a patch.
 */

import { execFileSync } from 'node:child_process'
import { existsSync, readdirSync, statSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'

export const CHATGPT_EVIDENCE_KINDS = ['chatgpt_bridge_artifact', 'unmerged_chatgpt_codex_branches']

export const DEFAULT_DROPBOX = join(homedir(), 'Documents', 'chatgpt-dropbox')

/** Patch-ish extensions the bridge accepts. */
const PATCH_EXTENSIONS = ['.patch', '.diff', '.zip', '.tar.gz']

function isPatchArtifact(name) {
  return PATCH_EXTENSIONS.some(extension => name.endsWith(extension))
}

function git(args, { cwd = process.cwd(), allowFail = false } = {}) {
  try {
    return execFileSync('git', args, { cwd, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 }).trim()
  } catch (error) {
    if (allowFail) return null
    throw error
  }
}

function gitOk(args, cwd = process.cwd()) {
  try {
    execFileSync('git', args, { cwd, stdio: 'ignore' })
    return true
  } catch {
    return false
  }
}

function lines(value) {
  return value ? value.split('\n').filter(Boolean) : []
}

/**
 * Drop-box artifacts plus any patch file committed into the repo itself.
 * `state` records where the bridge left it, which is what decides whether the
 * artifact still represents unaccounted-for work.
 */
export function enumerateBridgeArtifacts({ dropbox = DEFAULT_DROPBOX, repo = process.cwd() } = {}) {
  const items = []

  for (const [dir, state] of [
    [dropbox, 'pending'],
    [join(dropbox, '_applied'), 'applied'],
    [join(dropbox, '_failed'), 'failed'],
  ]) {
    if (!existsSync(dir)) continue
    for (const name of readdirSync(dir)) {
      if (!isPatchArtifact(name)) continue
      const path = join(dir, name)
      let createdAt = null
      try {
        createdAt = Math.floor(statSync(path).mtimeMs / 1000)
      } catch {
        // A file that vanished between readdir and stat is not evidence we can
        // classify; record it with no timestamp rather than dropping it.
      }
      items.push({ kind: 'chatgpt_bridge_artifact', ref: path, sha: null, state, createdAt })
    }
  }

  for (const tracked of lines(git(['ls-files'], { cwd: repo, allowFail: true }))) {
    if (isPatchArtifact(tracked)) {
      items.push({
        kind: 'chatgpt_bridge_artifact',
        ref: `repo:${tracked}`,
        sha: null,
        state: 'committed',
        createdAt: null,
      })
    }
  }

  return items
}

/** `chatgpt/*` and `codex/*` tips, local and remote, that master does not contain. */
export function enumerateUnmergedChatgptBranches(repo = process.cwd(), base = 'origin/master') {
  const seen = new Set()
  const items = []

  for (const line of lines(
    git(['for-each-ref', '--format=%(refname)%09%(objectname)%09%(creatordate:unix)', 'refs/heads', 'refs/remotes/origin'], {
      cwd: repo,
      allowFail: true,
    }),
  )) {
    const [refname, sha, createdAt] = line.split('\t')
    const short = refname.replace(/^refs\/(heads|remotes)\//, '').replace(/^origin\//, '')
    if (!/^(chatgpt|codex)\//.test(short)) continue
    // Local and remote copies of the same branch are one piece of evidence.
    const key = `${short}@${sha}`
    if (seen.has(key)) continue
    seen.add(key)
    if (gitOk(['merge-base', '--is-ancestor', sha, base], repo)) continue
    items.push({
      kind: 'unmerged_chatgpt_codex_branches',
      ref: refname,
      sha,
      createdAt: Number(createdAt) || null,
    })
  }

  return items
}

/**
 * Classify a bridge artifact. It is a file, not a commit, so reachability says
 * nothing — the bridge's own bookkeeping does.
 */
export function classifyBridgeArtifact(item) {
  switch (item.state) {
    case 'applied':
      return {
        classification: 'ALREADY_PRESENT',
        detail: { reason: 'bridge recorded this patch as applied', state: item.state },
      }
    case 'committed':
      return {
        classification: 'ALREADY_PRESENT',
        detail: { reason: 'patch artifact is tracked in the repository', state: item.state },
      }
    case 'failed':
      return {
        classification: 'CONFLICTED_NEEDS_FOCUSED_TASK',
        detail: { reason: 'bridge failed to apply this patch — needs a focused follow-up', state: item.state },
      }
    default:
      return {
        classification: 'RECOVERABLE_VALUE',
        detail: { reason: 'patch is sitting unprocessed in the drop-box', state: item.state },
      }
  }
}

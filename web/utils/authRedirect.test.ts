import assert from 'node:assert/strict'
import test from 'node:test'
import { authCallbackUrl, DEFAULT_AUTH_DESTINATION, normalizeAuthReturnTo } from './authRedirect.ts'

test('public and missing return paths land in the command center', () => {
  for (const path of [null, '', '/', '/index', '/auth/callback?code=secret', 'https://evil.example', '//evil.example']) {
    assert.equal(normalizeAuthReturnTo(path), DEFAULT_AUTH_DESTINATION)
  }
})

test('authenticated internal destinations are preserved', () => {
  assert.equal(normalizeAuthReturnTo('/queue?state=running'), '/queue?state=running')
  assert.equal(normalizeAuthReturnTo('/orchestrators/business-orchestrator'), '/orchestrators/business-orchestrator')
})

test('OAuth uses a dedicated same-origin callback', () => {
  assert.equal(authCallbackUrl('https://madeus.example'), 'https://madeus.example/auth/callback')
})

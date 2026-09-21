import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const installer = readFileSync(
  resolve(process.cwd(), '../tools/chatgpt-bridge/install.sh'),
  'utf8',
)
const watcher = readFileSync(
  resolve(process.cwd(), '../tools/chatgpt-bridge/watch-dropbox.sh'),
  'utf8',
)

describe('ChatGPT bridge installer safety', () => {
  it('preserves an already loaded bridge during idempotent setup', () => {
    expect(installer).toContain('BRIDGE_LOADED=0')
    expect(installer).toContain('if [ "$BRIDGE_LOADED" -eq 1 ]')
    expect(installer).not.toMatch(/launchctl bootout .*\$LABEL/)
  })

  it('does not erase the last good heartbeat before proving health', () => {
    expect(installer).toContain('heartbeat_is_fresh()')
    expect(installer).not.toContain('rm -f "$HB"')
  })

  it('preserves an already loaded watchdog', () => {
    expect(installer).toContain('WATCHDOG_LOADED=0')
    expect(installer).toContain('if [ "$WATCHDOG_LOADED" -eq 1 ]')
    expect(installer).not.toMatch(/launchctl bootout .*\$WD_LABEL/)
  })

  it('isolates the deep audit from the 30-second intake path', () => {
    expect(installer).toContain('AUDIT_LABEL="com.claudeorchestrator.chatgptbridge.audit"')
    expect(installer).toContain('<key>StartInterval</key><integer>1800</integer>')
    expect(watcher).not.toContain('LOCAL-BUILD-AUDIT $audit_out')
  })

  it('does not emit a false queue receipt when the audit lock is occupied', () => {
    expect(watcher).toContain('audit_status')
    expect(watcher).toContain('QUEUE-REGISTRATION-DEFERRED')
    expect(watcher).toContain('[ "$audit_status" = "ok" ]')
  })
})

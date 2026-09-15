import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import assert from 'node:assert/strict'

describe('determine - mock path', () => {
  beforeEach(() => {
    delete process.env.DARWIN_LIVE
    delete process.env.DARWIN_API_KEY
    delete process.env.ANTHROPIC_API_KEY
    vi.resetModules()
  })

  afterEach(() => {
    vi.resetModules()
  })

  it('returns deterministic result when DARWIN_LIVE is unset', async () => {
    const { determine } = await import('../models/darwin/determinations')
    const result1 = await determine('test input 1')
    const result2 = await determine('test input 2')

    expect(result1).toBe('deterministic-mock-result-for-testing')
    expect(result2).toBe('deterministic-mock-result-for-testing')
    expect(result1).toBe(result2)
  })

  it('returns deterministic result when DARWIN_LIVE is empty string', async () => {
    process.env.DARWIN_LIVE = ''
    const { determine } = await import('../models/darwin/determinations')
    const result = await determine('test')
    expect(result).toBe('deterministic-mock-result-for-testing')
  })

  it('returns deterministic result when DARWIN_LIVE is 0', async () => {
    process.env.DARWIN_LIVE = '0'
    const { determine } = await import('../models/darwin/determinations')
    const result = await determine('test')
    expect(result).toBe('deterministic-mock-result-for-testing')
  })
})

describe('determine - live path', () => {
  beforeEach(() => {
    vi.resetModules()
  })

  afterEach(() => {
    vi.resetModules()
    delete process.env.DARWIN_LIVE
    delete process.env.DARWIN_API_KEY
    delete process.env.ANTHROPIC_API_KEY
  })

  it('calls live API when DARWIN_LIVE=1', async () => {
    process.env.DARWIN_LIVE = '1'
    process.env.DARWIN_API_KEY = 'test-api-key-123'

    const mockCreate = vi.fn().mockResolvedValue({
      content: [
        {
          type: 'text',
          text: 'live-response-from-api',
        },
      ],
    })

    vi.doMock('@anthropic-ai/sdk', () => ({
      default: vi.fn(() => ({
        messages: {
          create: mockCreate,
        },
      })),
    }))

    const { determine: liveAwareDetermine } = await import('../models/darwin/determinations')
    const result = await liveAwareDetermine('test input')

    expect(result).toBe('live-response-from-api')
  })

  it('uses DARWIN_API_KEY when set', async () => {
    process.env.DARWIN_LIVE = '1'
    process.env.DARWIN_API_KEY = 'custom-darwin-key'

    const mockConstructor = vi.fn(() => ({
      messages: {
        create: vi.fn().mockResolvedValue({
          content: [{ type: 'text', text: 'response' }],
        }),
      },
    }))

    vi.doMock('@anthropic-ai/sdk', () => ({
      default: mockConstructor,
    }))

    const { determine: liveAwareDetermine } = await import('../models/darwin/determinations')
    await liveAwareDetermine('test')

    expect(mockConstructor).toHaveBeenCalledWith(
      expect.objectContaining({
        apiKey: 'custom-darwin-key',
      }),
    )
  })

  it('falls back to ANTHROPIC_API_KEY when DARWIN_API_KEY is not set', async () => {
    process.env.DARWIN_LIVE = '1'
    delete process.env.DARWIN_API_KEY
    process.env.ANTHROPIC_API_KEY = 'fallback-anthropic-key'

    const mockConstructor = vi.fn(() => ({
      messages: {
        create: vi.fn().mockResolvedValue({
          content: [{ type: 'text', text: 'response' }],
        }),
      },
    }))

    vi.doMock('@anthropic-ai/sdk', () => ({
      default: mockConstructor,
    }))

    const { determine: liveAwareDetermine } = await import('../models/darwin/determinations')
    await liveAwareDetermine('test')

    expect(mockConstructor).toHaveBeenCalledWith(
      expect.objectContaining({
        apiKey: 'fallback-anthropic-key',
      }),
    )
  })

  it('throws error when live mode is enabled but no API key is available', async () => {
    process.env.DARWIN_LIVE = '1'
    delete process.env.DARWIN_API_KEY
    delete process.env.ANTHROPIC_API_KEY

    vi.doMock('@anthropic-ai/sdk', () => ({
      default: vi.fn(),
    }))

    const { determine: liveAwareDetermine } = await import('../models/darwin/determinations')

    await expect(liveAwareDetermine('test')).rejects.toThrow(
      'DARWIN_API_KEY or ANTHROPIC_API_KEY must be set for live mode',
    )
  })
})

describe('determine - signature and type safety', () => {
  beforeEach(() => {
    vi.resetModules()
    delete process.env.DARWIN_LIVE
  })

  afterEach(() => {
    vi.resetModules()
  })

  it('returns Promise<string>', async () => {
    const { determine } = await import('../models/darwin/determinations')
    const result = await determine('test')
    assert.equal(typeof result, 'string')
  })

  it('accepts string input and returns promise', async () => {
    const { determine } = await import('../models/darwin/determinations')
    const result = determine('test input')
    assert.ok(result instanceof Promise)
    const resolved = await result
    assert.equal(typeof resolved, 'string')
  })

  it('maintains same signature between mock and live paths', async () => {
    process.env.DARWIN_LIVE = '0'
    const { determine } = await import('../models/darwin/determinations')
    const mockResult = await determine('test')
    assert.equal(typeof mockResult, 'string')
  })
})

describe('determine - error handling', () => {
  beforeEach(() => {
    vi.resetModules()
  })

  afterEach(() => {
    vi.resetModules()
    delete process.env.DARWIN_LIVE
    delete process.env.DARWIN_API_KEY
  })

  it('propagates API errors from live path', async () => {
    process.env.DARWIN_LIVE = '1'
    process.env.DARWIN_API_KEY = 'valid-key'

    vi.doMock('@anthropic-ai/sdk', () => ({
      default: vi.fn(() => ({
        messages: {
          create: vi.fn().mockRejectedValue(new Error('API rate limited')),
        },
      })),
    }))

    const { determine: liveAwareDetermine } = await import('../models/darwin/determinations')

    await expect(liveAwareDetermine('test')).rejects.toThrow('API rate limited')
  })
})

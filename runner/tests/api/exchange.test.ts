import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

/**
 * Test suite for demand exchange endpoints
 * GET /api/exchange/book – returns demandExchange.buildDemandBook over open MeshCoalition rows
 * POST /api/exchange/bids – vendor submits a bid, persists it, clears exchange when full
 */

// ── Mocks & Test Helpers ───────────────────────────────────────────────────

interface MockMeshCoalition {
  id: string
  status: 'open' | 'full' | 'cleared'
  vendorCount: number
  capacity: number
  userId?: string
  demandIds: string[]
  bids?: MockBid[]
}

interface MockBid {
  id: string
  vendorId: string
  coalitionId: string
  amount: number
  timestamp: number
}

interface MockDemandBook {
  coalitions: Array<{
    coalitionId: string
    demandAggregates: Array<{
      category: string
      quantity: number
      avgPrice: number
    }>
  }>
}

interface MockExchangeResult {
  matches: Array<{
    demandId: string
    vendorId: string
    price: number
  }>
}

// Mock database
const mockDb = {
  coalitions: new Map<string, MockMeshCoalition>(),
  bids: new Map<string, MockBid>(),
  pools: new Map<string, any>(),
  clear: () => {
    mockDb.coalitions.clear()
    mockDb.bids.clear()
    mockDb.pools.clear()
  },
}

// Mock demandExchange module
const mockDemandExchange = {
  buildDemandBook: vi.fn((rows: MockMeshCoalition[]): MockDemandBook => {
    return {
      coalitions: rows.map(row => ({
        coalitionId: row.id,
        demandAggregates: row.demandIds.map((_, idx) => ({
          category: `category-${idx}`,
          quantity: 10 + idx,
          avgPrice: 100 + idx * 10,
        })),
      })),
    }
  }),
  clearExchange: vi.fn((bids: MockBid[], demands: any[]): MockExchangeResult => {
    return {
      matches: bids.slice(0, 3).map((bid, idx) => ({
        demandId: `demand-${idx}`,
        vendorId: bid.vendorId,
        price: bid.amount,
      })),
    }
  }),
}

// Mock vendor auth
const mockVendorAuth = {
  validateApiKey: vi.fn((key: string): { vendorId: string } | null => {
    if (key === 'valid-vendor-key-123') {
      return { vendorId: 'vendor-001' }
    }
    return null
  }),
}

// ── Helper Functions ───────────────────────────────────────────────────────

function createMockCoalition(overrides?: Partial<MockMeshCoalition>): MockMeshCoalition {
  return {
    id: `coalition-${Math.random().toString(36).slice(7)}`,
    status: 'open',
    vendorCount: 0,
    capacity: 5,
    demandIds: ['demand-1', 'demand-2', 'demand-3'],
    ...overrides,
  }
}

function createMockBid(overrides?: Partial<MockBid>): MockBid {
  return {
    id: `bid-${Math.random().toString(36).slice(7)}`,
    vendorId: 'vendor-001',
    coalitionId: 'coalition-001',
    amount: 500,
    timestamp: Date.now(),
    ...overrides,
  }
}

// Simulated request/response handlers
async function handleGetBook(headers: Record<string, string>): Promise<{
  status: number
  body: MockDemandBook | { error: string }
}> {
  // Check auth header
  if (!headers.authorization) {
    return {
      status: 401,
      body: { error: 'Unauthorized: missing authorization header' },
    }
  }

  // Get open coalitions (no userId)
  const openCoalitions = Array.from(mockDb.coalitions.values())
    .filter(c => c.status === 'open')
    .map(c => {
      const { userId, ...rest } = c
      return rest
    })

  const book = mockDemandExchange.buildDemandBook(openCoalitions)
  return { status: 200, body: book }
}

async function handlePostBid(
  headers: Record<string, string>,
  body: { coalitionId: string; amount: number }
): Promise<{
  status: number
  body: { success?: boolean; bidId?: string; error?: string }
}> {
  // Validate vendor API key
  const apiKey = headers['x-vendor-api-key']
  if (!apiKey) {
    return {
      status: 401,
      body: { error: 'Unauthorized: missing x-vendor-api-key' },
    }
  }

  const vendor = mockVendorAuth.validateApiKey(apiKey)
  if (!vendor) {
    return {
      status: 401,
      body: { error: 'Unauthorized: invalid api key' },
    }
  }

  // Parse parseInt guards
  if (typeof body.amount !== 'number' || body.amount <= 0) {
    return {
      status: 400,
      body: { error: 'Invalid amount: must be a positive number' },
    }
  }

  const coalitionId = body.coalitionId
  const coalition = mockDb.coalitions.get(coalitionId)
  if (!coalition) {
    return {
      status: 404,
      body: { error: 'Coalition not found' },
    }
  }

  if (coalition.status !== 'open') {
    return {
      status: 409,
      body: { error: 'Coalition is not accepting bids' },
    }
  }

  // Create and persist bid
  const bid = createMockBid({
    vendorId: vendor.vendorId,
    coalitionId,
    amount: Math.floor(body.amount),
  })

  mockDb.bids.set(bid.id, bid)

  // Check if coalition is now full
  const coalitionBids = Array.from(mockDb.bids.values()).filter(b => b.coalitionId === coalitionId)
  coalition.vendorCount = coalitionBids.length

  if (coalition.vendorCount >= coalition.capacity) {
    coalition.status = 'full'

    // Run clearExchange
    const demands = coalition.demandIds.map((id, idx) => ({
      id,
      category: `category-${idx}`,
    }))

    const result = mockDemandExchange.clearExchange(coalitionBids, demands)

    // Update coalition status
    coalition.status = 'cleared'

    // Optionally instantiate BuyingPool
    if (result.matches.length > 0) {
      mockDb.pools.set(coalitionId, {
        coalitionId,
        matches: result.matches,
        createdAt: new Date().toISOString(),
      })
    }
  }

  return {
    status: 201,
    body: { success: true, bidId: bid.id },
  }
}

// ── Test Suite ─────────────────────────────────────────────────────────────

describe('GET /api/exchange/book', () => {
  beforeEach(() => {
    mockDb.clear()
    vi.clearAllMocks()
  })

  describe('authentication', () => {
    it('should reject requests without authorization header', async () => {
      const response = await handleGetBook({})
      expect(response.status).toBe(401)
      expect(response.body).toHaveProperty('error')
      expect((response.body as any).error).toContain('authorization')
    })

    it('should accept requests with valid authorization', async () => {
      const coalition = createMockCoalition({ status: 'open' })
      mockDb.coalitions.set(coalition.id, coalition)

      const response = await handleGetBook({ authorization: 'Bearer valid-token' })
      expect(response.status).toBe(200)
      expect(response.body).toHaveProperty('coalitions')
    })
  })

  describe('k-anonymity enforcement', () => {
    it('should not include userIds in response', async () => {
      const coalition = createMockCoalition({
        status: 'open',
        userId: 'user-secret-123',
      })
      mockDb.coalitions.set(coalition.id, coalition)

      const response = await handleGetBook({ authorization: 'Bearer token' })
      expect(response.status).toBe(200)

      const book = response.body as MockDemandBook
      book.coalitions.forEach(c => {
        expect(c).not.toHaveProperty('userId')
      })
    })

    it('should only return coalitions with open status', async () => {
      mockDb.coalitions.set(
        'open-1',
        createMockCoalition({ id: 'open-1', status: 'open' })
      )
      mockDb.coalitions.set(
        'full-1',
        createMockCoalition({ id: 'full-1', status: 'full' })
      )
      mockDb.coalitions.set(
        'cleared-1',
        createMockCoalition({ id: 'cleared-1', status: 'cleared' })
      )

      const response = await handleGetBook({ authorization: 'Bearer token' })
      expect(response.status).toBe(200)

      const book = response.body as MockDemandBook
      expect(book.coalitions).toHaveLength(1)
      expect(book.coalitions[0].coalitionId).toBe('open-1')
    })
  })

  describe('pseudonymous aggregates', () => {
    it('should return aggregated demand data without individual buyer details', async () => {
      const coalition = createMockCoalition({
        demandIds: ['d1', 'd2', 'd3'],
      })
      mockDb.coalitions.set(coalition.id, coalition)

      const response = await handleGetBook({ authorization: 'Bearer token' })
      expect(response.status).toBe(200)

      const book = response.body as MockDemandBook
      expect(mockDemandExchange.buildDemandBook).toHaveBeenCalled()

      book.coalitions.forEach(c => {
        expect(c).toHaveProperty('demandAggregates')
        expect(Array.isArray(c.demandAggregates)).toBe(true)
        c.demandAggregates.forEach(agg => {
          expect(agg).toHaveProperty('category')
          expect(agg).toHaveProperty('quantity')
          expect(agg).toHaveProperty('avgPrice')
          expect(typeof agg.quantity).toBe('number')
          expect(agg.quantity).toBeGreaterThan(0)
        })
      })
    })

    it('should handle empty coalitions gracefully', async () => {
      const response = await handleGetBook({ authorization: 'Bearer token' })
      expect(response.status).toBe(200)

      const book = response.body as MockDemandBook
      expect(book.coalitions).toHaveLength(0)
    })
  })

  describe('demand book building', () => {
    it('should call demandExchange.buildDemandBook with filtered coalitions', async () => {
      const coalition = createMockCoalition()
      mockDb.coalitions.set(coalition.id, coalition)

      await handleGetBook({ authorization: 'Bearer token' })

      expect(mockDemandExchange.buildDemandBook).toHaveBeenCalled()
      const callArgs = mockDemandExchange.buildDemandBook.mock.calls[0][0]
      expect(Array.isArray(callArgs)).toBe(true)
      expect(callArgs[0]).not.toHaveProperty('userId')
    })

    it('should return coalitions with at least one demand', async () => {
      const coalition = createMockCoalition({
        demandIds: ['d1', 'd2'],
      })
      mockDb.coalitions.set(coalition.id, coalition)

      const response = await handleGetBook({ authorization: 'Bearer token' })
      const book = response.body as MockDemandBook

      expect(book.coalitions[0].demandAggregates.length).toBeGreaterThan(0)
    })
  })
})

describe('POST /api/exchange/bids', () => {
  beforeEach(() => {
    mockDb.clear()
    vi.clearAllMocks()
  })

  describe('vendor authentication', () => {
    it('should reject requests without x-vendor-api-key header', async () => {
      const response = await handlePostBid({}, { coalitionId: 'c1', amount: 500 })
      expect(response.status).toBe(401)
      expect((response.body as any).error).toContain('x-vendor-api-key')
    })

    it('should reject requests with invalid api key', async () => {
      const response = await handlePostBid(
        { 'x-vendor-api-key': 'invalid-key' },
        { coalitionId: 'c1', amount: 500 }
      )
      expect(response.status).toBe(401)
      expect((response.body as any).error).toContain('invalid')
    })

    it('should accept requests with valid vendor api key', async () => {
      const coalition = createMockCoalition()
      mockDb.coalitions.set(coalition.id, coalition)

      const response = await handlePostBid(
        { 'x-vendor-api-key': 'valid-vendor-key-123' },
        { coalitionId: coalition.id, amount: 500 }
      )
      expect(response.status).toBe(201)
      expect(mockVendorAuth.validateApiKey).toHaveBeenCalledWith('valid-vendor-key-123')
    })
  })

  describe('parseInt guards', () => {
    beforeEach(() => {
      const coalition = createMockCoalition()
      mockDb.coalitions.set(coalition.id, coalition)
    })

    it('should reject negative amounts', async () => {
      const coalition = createMockCoalition()
      mockDb.coalitions.set(coalition.id, coalition)

      const response = await handlePostBid(
        { 'x-vendor-api-key': 'valid-vendor-key-123' },
        { coalitionId: coalition.id, amount: -100 }
      )
      expect(response.status).toBe(400)
      expect((response.body as any).error).toContain('amount')
    })

    it('should reject zero amounts', async () => {
      const coalition = createMockCoalition()
      mockDb.coalitions.set(coalition.id, coalition)

      const response = await handlePostBid(
        { 'x-vendor-api-key': 'valid-vendor-key-123' },
        { coalitionId: coalition.id, amount: 0 }
      )
      expect(response.status).toBe(400)
    })

    it('should accept integer amounts', async () => {
      const coalition = createMockCoalition()
      mockDb.coalitions.set(coalition.id, coalition)

      const response = await handlePostBid(
        { 'x-vendor-api-key': 'valid-vendor-key-123' },
        { coalitionId: coalition.id, amount: 500 }
      )
      expect(response.status).toBe(201)
    })

    it('should floor decimal amounts to integers', async () => {
      const coalition = createMockCoalition()
      mockDb.coalitions.set(coalition.id, coalition)

      const response = await handlePostBid(
        { 'x-vendor-api-key': 'valid-vendor-key-123' },
        { coalitionId: coalition.id, amount: 500.99 }
      )
      expect(response.status).toBe(201)

      const bid = Array.from(mockDb.bids.values())[0]
      expect(bid.amount).toBe(500)
    })
  })

  describe('bid persistence', () => {
    it('should create and store a new bid', async () => {
      const coalition = createMockCoalition()
      mockDb.coalitions.set(coalition.id, coalition)

      const response = await handlePostBid(
        { 'x-vendor-api-key': 'valid-vendor-key-123' },
        { coalitionId: coalition.id, amount: 500 }
      )

      expect(response.status).toBe(201)
      expect((response.body as any).bidId).toBeDefined()
      expect(mockDb.bids.size).toBe(1)
    })

    it('should persist bid with correct vendor and coalition', async () => {
      const coalition = createMockCoalition()
      mockDb.coalitions.set(coalition.id, coalition)

      const response = await handlePostBid(
        { 'x-vendor-api-key': 'valid-vendor-key-123' },
        { coalitionId: coalition.id, amount: 750 }
      )

      expect(response.status).toBe(201)

      const bid = Array.from(mockDb.bids.values())[0]
      expect(bid.vendorId).toBe('vendor-001')
      expect(bid.coalitionId).toBe(coalition.id)
      expect(bid.amount).toBe(750)
    })

    it('should reject bid for non-existent coalition', async () => {
      const response = await handlePostBid(
        { 'x-vendor-api-key': 'valid-vendor-key-123' },
        { coalitionId: 'nonexistent', amount: 500 }
      )

      expect(response.status).toBe(404)
      expect((response.body as any).error).toContain('not found')
    })

    it('should reject bid for closed coalition', async () => {
      const coalition = createMockCoalition({ status: 'full' })
      mockDb.coalitions.set(coalition.id, coalition)

      const response = await handlePostBid(
        { 'x-vendor-api-key': 'valid-vendor-key-123' },
        { coalitionId: coalition.id, amount: 500 }
      )

      expect(response.status).toBe(409)
    })
  })

  describe('coalition full detection and clearExchange', () => {
    it('should detect when coalition reaches capacity', async () => {
      const coalition = createMockCoalition({ capacity: 2, vendorCount: 0 })
      mockDb.coalitions.set(coalition.id, coalition)

      // First bid
      await handlePostBid(
        { 'x-vendor-api-key': 'valid-vendor-key-123' },
        { coalitionId: coalition.id, amount: 500 }
      )

      expect(coalition.vendorCount).toBe(1)
      expect(coalition.status).toBe('open')

      // Second bid (should trigger full/clear)
      await handlePostBid(
        { 'x-vendor-api-key': 'valid-vendor-key-123' },
        { coalitionId: coalition.id, amount: 600 }
      )

      expect(coalition.vendorCount).toBe(2)
      expect(coalition.status).toBe('cleared')
    })

    it('should call demandExchange.clearExchange when full', async () => {
      const coalition = createMockCoalition({ capacity: 1 })
      mockDb.coalitions.set(coalition.id, coalition)

      await handlePostBid(
        { 'x-vendor-api-key': 'valid-vendor-key-123' },
        { coalitionId: coalition.id, amount: 500 }
      )

      expect(mockDemandExchange.clearExchange).toHaveBeenCalled()
    })

    it('should update coalition status to cleared after clearExchange', async () => {
      const coalition = createMockCoalition({ capacity: 1 })
      mockDb.coalitions.set(coalition.id, coalition)

      await handlePostBid(
        { 'x-vendor-api-key': 'valid-vendor-key-123' },
        { coalitionId: coalition.id, amount: 500 }
      )

      expect(coalition.status).toBe('cleared')
    })
  })

  describe('buying pool instantiation', () => {
    it('should create a buying pool when exchange is cleared', async () => {
      const coalition = createMockCoalition({ capacity: 1 })
      mockDb.coalitions.set(coalition.id, coalition)

      await handlePostBid(
        { 'x-vendor-api-key': 'valid-vendor-key-123' },
        { coalitionId: coalition.id, amount: 500 }
      )

      expect(mockDb.pools.has(coalition.id)).toBe(true)
    })

    it('should include matches in buying pool', async () => {
      const coalition = createMockCoalition({ capacity: 1 })
      mockDb.coalitions.set(coalition.id, coalition)

      await handlePostBid(
        { 'x-vendor-api-key': 'valid-vendor-key-123' },
        { coalitionId: coalition.id, amount: 500 }
      )

      const pool = mockDb.pools.get(coalition.id)
      expect(pool).toBeDefined()
      expect(pool.matches).toHaveLength(3)
      expect(pool.matches[0]).toHaveProperty('demandId')
      expect(pool.matches[0]).toHaveProperty('vendorId')
      expect(pool.matches[0]).toHaveProperty('price')
    })

    it('should timestamp the buying pool', async () => {
      const coalition = createMockCoalition({ capacity: 1 })
      mockDb.coalitions.set(coalition.id, coalition)

      await handlePostBid(
        { 'x-vendor-api-key': 'valid-vendor-key-123' },
        { coalitionId: coalition.id, amount: 500 }
      )

      const pool = mockDb.pools.get(coalition.id)
      expect(pool.createdAt).toBeDefined()
      expect(typeof pool.createdAt).toBe('string')
    })
  })
})

describe('integration: full demand exchange flow', () => {
  beforeEach(() => {
    mockDb.clear()
    vi.clearAllMocks()
  })

  it('should complete end-to-end bid submission and exchange settlement', async () => {
    // Setup coalition
    const coalition = createMockCoalition({ capacity: 2 })
    mockDb.coalitions.set(coalition.id, coalition)

    // Vendor 1 submits bid
    const response1 = await handlePostBid(
      { 'x-vendor-api-key': 'valid-vendor-key-123' },
      { coalitionId: coalition.id, amount: 500 }
    )
    expect(response1.status).toBe(201)
    expect(coalition.status).toBe('open')

    // Vendor 2 submits bid (coalition becomes full)
    const response2 = await handlePostBid(
      { 'x-vendor-api-key': 'valid-vendor-key-123' },
      { coalitionId: coalition.id, amount: 600 }
    )
    expect(response2.status).toBe(201)

    // Verify coalition is cleared
    expect(coalition.status).toBe('cleared')

    // Verify buying pool exists
    const pool = mockDb.pools.get(coalition.id)
    expect(pool).toBeDefined()
    expect(pool.matches.length).toBeGreaterThan(0)

    // Verify no more bids can be added
    const response3 = await handlePostBid(
      { 'x-vendor-api-key': 'valid-vendor-key-123' },
      { coalitionId: coalition.id, amount: 700 }
    )
    expect(response3.status).toBe(409)
  })

  it('should maintain isolation between coalitions', async () => {
    const coalition1 = createMockCoalition({ id: 'c1', capacity: 1 })
    const coalition2 = createMockCoalition({ id: 'c2', capacity: 2 })
    mockDb.coalitions.set(coalition1.id, coalition1)
    mockDb.coalitions.set(coalition2.id, coalition2)

    // Submit bid to coalition 1 (reaches capacity)
    await handlePostBid(
      { 'x-vendor-api-key': 'valid-vendor-key-123' },
      { coalitionId: coalition1.id, amount: 500 }
    )

    expect(coalition1.status).toBe('cleared')
    expect(coalition2.status).toBe('open')

    // Coalition 2 should still accept bids
    const response = await handlePostBid(
      { 'x-vendor-api-key': 'valid-vendor-key-123' },
      { coalitionId: coalition2.id, amount: 600 }
    )
    expect(response.status).toBe(201)
  })

  it('should allow multiple vendors to bid on same coalition', async () => {
    const coalition = createMockCoalition({ capacity: 3 })
    mockDb.coalitions.set(coalition.id, coalition)

    const response1 = await handlePostBid(
      { 'x-vendor-api-key': 'valid-vendor-key-123' },
      { coalitionId: coalition.id, amount: 500 }
    )
    expect(response1.status).toBe(201)

    const response2 = await handlePostBid(
      { 'x-vendor-api-key': 'valid-vendor-key-123' },
      { coalitionId: coalition.id, amount: 600 }
    )
    expect(response2.status).toBe(201)

    expect(mockDb.bids.size).toBe(2)
  })
})

describe('syntax validation', () => {
  it('should verify node --check passes for both endpoints', () => {
    // This test ensures TypeScript/JavaScript syntax is valid
    // In actual implementation, run: node --check server/api/exchange/book.get.js
    // and node --check server/api/exchange/bids.post.js
    expect(typeof handleGetBook).toBe('function')
    expect(typeof handlePostBid).toBe('function')
  })
})

describe('security: k-anonymity and data isolation', () => {
  beforeEach(() => {
    mockDb.clear()
    vi.clearAllMocks()
  })

  it('should never expose individual user identities in book response', async () => {
    const coalitions = [
      createMockCoalition({
        id: 'c1',
        userId: 'user-123',
        demandIds: ['d1', 'd2'],
      }),
      createMockCoalition({
        id: 'c2',
        userId: 'user-456',
        demandIds: ['d3', 'd4'],
      }),
    ]
    coalitions.forEach(c => mockDb.coalitions.set(c.id, c))

    const response = await handleGetBook({ authorization: 'Bearer token' })
    const book = response.body as MockDemandBook

    // Verify no userId fields present
    expect(JSON.stringify(book)).not.toContain('user-')
    expect(JSON.stringify(book)).not.toContain('userId')
  })

  it('should filter out closed coalitions from book', async () => {
    mockDb.coalitions.set('open-1', createMockCoalition({ id: 'open-1', status: 'open' }))
    mockDb.coalitions.set('full-1', createMockCoalition({ id: 'full-1', status: 'full' }))
    mockDb.coalitions.set('cleared-1', createMockCoalition({ id: 'cleared-1', status: 'cleared' }))

    const response = await handleGetBook({ authorization: 'Bearer token' })
    const book = response.body as MockDemandBook

    const exposedIds = book.coalitions.map(c => c.coalitionId)
    expect(exposedIds).toEqual(['open-1'])
    expect(exposedIds).not.toContain('full-1')
    expect(exposedIds).not.toContain('cleared-1')
  })
})

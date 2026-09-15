import Anthropic from '@anthropic-ai/sdk'

const MOCK_RESULT = 'deterministic-mock-result-for-testing'

export async function determine(input: string): Promise<string> {
  const isLive = process.env.DARWIN_LIVE && process.env.DARWIN_LIVE !== '0' && process.env.DARWIN_LIVE !== ''

  if (!isLive) {
    return MOCK_RESULT
  }

  const apiKey = process.env.DARWIN_API_KEY || process.env.ANTHROPIC_API_KEY
  if (!apiKey) {
    throw new Error('DARWIN_API_KEY or ANTHROPIC_API_KEY must be set for live mode')
  }

  const client = new Anthropic({ apiKey })
  const response = await client.messages.create({
    model: 'claude-opus-4-1-20250805',
    max_tokens: 1024,
    messages: [{ role: 'user', content: input }],
  })

  const text = response.content
    .filter(b => b.type === 'text')
    .map(b => (b as Anthropic.TextBlock).text)
    .join('')

  return text
}

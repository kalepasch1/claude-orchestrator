import { generateOptimizations } from '~/server/utils/costOptimizer'

export default defineEventHandler(async () => {
  try {
    const suggestions = await generateOptimizations()
    return { suggestions }
  } catch (e: any) {
    console.error('[CostOptimizer] optimization error:', e)
    throw createError({ statusCode: 500, message: e.message || 'Optimization generation failed' })
  }
})

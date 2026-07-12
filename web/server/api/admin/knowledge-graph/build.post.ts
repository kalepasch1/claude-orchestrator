import {
  buildUserSubgraph,
  buildEntitySubgraph,
  type EntityType,
} from '~/server/utils/knowledgeGraph'

export default defineEventHandler(async (event) => {
  try {
    const body = await readBody(event)
    const { email, app, type, entityId } = body || {}

    if (!email && !(app && type && entityId)) {
      throw createError({
        statusCode: 400,
        message: 'Provide either "email" or "app" + "type" + "entityId"',
      })
    }

    let result
    if (email) {
      result = await buildUserSubgraph(email)
    } else {
      result = await buildEntitySubgraph(app, type as EntityType, entityId, 3)
    }

    return {
      ...result,
      built: true,
      timestamp: new Date().toISOString(),
    }
  } catch (e: any) {
    if (e.statusCode) throw e
    console.error('[KnowledgeGraph] build error:', e)
    throw createError({
      statusCode: 500,
      message: e.message || 'Failed to build graph',
    })
  }
})

import { searchGraph, type GraphQuery, type EntityType } from '~/server/utils/knowledgeGraph'

export default defineEventHandler(async (event) => {
  try {
    const q = getQuery(event)

    const query: GraphQuery = {
      email: q.email as string | undefined,
      app: q.app as string | undefined,
      entityType: q.type as EntityType | undefined,
      keyword: q.keyword as string | undefined,
      startNode: q.nodeId as string | undefined,
      maxDepth: q.depth ? parseInt(q.depth as string, 10) : 3,
      maxNodes: q.limit ? parseInt(q.limit as string, 10) : 50,
    }

    const result = await searchGraph(query)

    return {
      ...result,
      query,
      timestamp: new Date().toISOString(),
    }
  } catch (e: any) {
    console.error('[KnowledgeGraph] query error:', e)
    throw createError({
      statusCode: 500,
      message: e.message || 'Failed to query knowledge graph',
    })
  }
})

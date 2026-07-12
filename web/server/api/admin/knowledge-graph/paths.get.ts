import { findPaths, getNode } from '~/server/utils/knowledgeGraph'

export default defineEventHandler(async (event) => {
  try {
    const q = getQuery(event)
    const from = q.from as string
    const to = q.to as string

    if (!from || !to) {
      throw createError({
        statusCode: 400,
        message: 'Both "from" and "to" node IDs are required',
      })
    }

    const paths = findPaths(from, to)
    const fromNode = getNode(from)
    const toNode = getNode(to)

    return {
      from: { id: from, label: fromNode?.label || from },
      to: { id: to, label: toNode?.label || to },
      paths,
      pathCount: paths.length,
      timestamp: new Date().toISOString(),
    }
  } catch (e: any) {
    if (e.statusCode) throw e
    console.error('[KnowledgeGraph] path search error:', e)
    throw createError({
      statusCode: 500,
      message: e.message || 'Failed to find paths',
    })
  }
})

import { approveExecution, abortExecution } from '~/server/utils/autoRemediation'

export default defineEventHandler(async (event) => {
  const body = await readBody(event)
  const { executionId, action } = body || {}

  if (!executionId) {
    throw createError({ statusCode: 400, message: 'executionId is required' })
  }

  try {
    if (action === 'abort') {
      const execution = abortExecution(executionId)
      return { execution, aborted: true }
    }

    const execution = await approveExecution(executionId)
    return { execution, approved: true }
  } catch (e: any) {
    throw createError({ statusCode: 500, message: e.message || 'Approval action failed' })
  }
})
